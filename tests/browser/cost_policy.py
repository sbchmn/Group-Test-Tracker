"""Run against an isolated local fixture; requires Chrome and websockets. See README.md."""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from websockets.sync.client import connect
from werkzeug.serving import make_server, WSGIRequestHandler
os.environ['GTT_DEPLOYMENT_MODE'] = 'standalone'
os.environ['GTT_MANAGED_INTEGRATIONS'] = '{}'
from app import create_app, db
from app.models import User, GroupTest, PaymentOption, Participation
import app.routes as routes
import app.notifications as notifications

work = tempfile.TemporaryDirectory(prefix='gtt-cost-browser-')
folder = Path(work.name)
artifacts = Path(os.environ.get('BROWSER_ARTIFACTS_DIR') or tempfile.mkdtemp(prefix='gtt-browser-artifacts-'))
artifacts.mkdir(parents=True, exist_ok=True)
routes._notify_payment_claim = lambda *args: None
routes._notify_status_change_after_commit = lambda *args: None
notifications.send_notification_message = lambda *args: True
app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(folder / 'browser.db'), 'SECRET_KEY': 'browser-test-only', 'NOTIFICATION_LOG_PATH': str(folder / 'notifications.log')})
with app.app_context():
    db.drop_all(); db.create_all()
    member = User(username='browser-member', email='member@example.test'); member.set_password('secret')
    admin = User(username='browser-admin', email='admin@example.test', is_admin=True); admin.set_password('secret')
    db.session.add_all([member, admin]); db.session.flush()
    option = PaymentOption(label='Base lab wallet', method_type='crypto', network='Base', wallet_address='0x1234567890abcdef1234567890abcdef12345678', proof_image_enabled=True, proof_transaction_enabled=True, proof_requirement='either')
    test = GroupTest(title='Cost Freeze Browser Review', created_by=admin.id, status='recruiting', total_lab_cost=600, refund_per_donor=20, payment_options=[option, PaymentOption(label='PayPal laboratory account', method_type='paypal', account_handle='audit-collector')])
    db.session.add(test); db.session.flush()
    part = Participation(group_test_id=test.id, user_id=member.id, approved=False, vial_donor=True, amount_owed=0, name='Browser Participant')
    db.session.add(part)
    outsider = User(username='browser-pending',email='pending@example.test',password_hash=member.password_hash)
    db.session.add(outsider); db.session.flush()
    pending = Participation(group_test_id=test.id,user_id=outsider.id,approved=False, name='Pending non-donor'); db.session.add(pending); db.session.flush(); pending_id = pending.id
    late_user = User(username='late-buyer',email='late@example.test',password_hash=member.password_hash); db.session.add(late_user); db.session.flush()
    late = Participation(group_test_id=test.id,user_id=late_user.id,approved=False,name='Late access buyer'); db.session.add(late); db.session.flush(); late_id = late.id
    db.session.commit(); test_id = test.id; part_id = part.id; option_id = option.id
class QuietHandler(WSGIRequestHandler):
    def log(self, *args): pass
server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = 'http://127.0.0.1:' + str(server.server_port)
profile_work = tempfile.TemporaryDirectory(prefix='gtt-chrome-profile-', ignore_cleanup_errors=True)
profile = profile_work.name
chrome_log = open(folder / 'chrome.log', 'w')
chrome = subprocess.Popen([os.environ.get('CHROME_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'), '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--in-process-gpu', '--no-sandbox', '--ignore-certificate-errors', '--remote-debugging-port=0', '--remote-allow-origins=*', '--user-data-dir=' + profile, 'about:blank'], stdout=subprocess.DEVNULL, stderr=chrome_log, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    portfile = Path(profile) / 'DevToolsActivePort'
    for _ in range(200):
        if portfile.exists(): break
        time.sleep(.1)
    port = portfile.read_text().splitlines()[0]
    tabs = json.load(urllib.request.urlopen('http://127.0.0.1:' + port + '/json/list'))
    ws = connect(next(tab['webSocketDebuggerUrl'] for tab in tabs if tab['type'] == 'page'), max_size=20_000_000, legacy=True, proxy=None, compression=None)
    sequence = 0; exceptions = []
    def call(method, params=None):
        global sequence
        sequence += 1; ident = sequence; ws.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
        while True:
            result = json.loads(ws.recv(timeout=30))
            if result.get('method') == 'Runtime.exceptionThrown': exceptions.append(result['params'])
            if result.get('id') == ident:
                if 'error' in result: raise RuntimeError(result['error'])
                return result.get('result', {})
    def js(expression):
        result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
        if 'exceptionDetails' in result: raise RuntimeError(result['exceptionDetails'])
        return result.get('result', {}).get('value')
    def wait(expression, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if js(expression): return
            except RuntimeError: pass
            time.sleep(.1)
        raise RuntimeError('Timed out: ' + expression + ' page=' + str(js('location.href')))
    def navigate(path):
        call('Page.navigate', {'url': base + path}); time.sleep(.2)
        wait('document.readyState === "complete"'); wait('typeof bootstrap !== "undefined"')
    def login(username):
        navigate('/login')
        js("document.querySelector('[name=username]').value=" + json.dumps(username))
        js("document.querySelector('[name=password]').value='secret';document.querySelector('form').submit()")
        wait("location.pathname === '/dashboard'")
    def click(selector): js('document.querySelector(' + json.dumps(selector) + ').click()')
    def value(selector, text): js('document.querySelector(' + json.dumps(selector) + ').value=' + json.dumps(text))
    def viewport(width, height): call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 600})
    def screenshot(name):
        time.sleep(.4)
        result = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False}); (artifacts / name).write_bytes(base64.b64decode(result['data']))
    call('Page.enable'); call('Runtime.enable')
    metrics_code = Path(__file__).with_name('layout_metrics.js').read_text(encoding='utf-8')
    results = []
    def audit(label, path):
        for width,height in [(320,900),(390,1000),(820,1180),(1024,1100),(1440,1000)]:
            viewport(width,height); navigate(path); time.sleep(.3)
            metrics = js(metrics_code)
            assert metrics['pageWidth'] <= width, (label,width,metrics)
            assert not metrics['overlaps'], (label,width,metrics['overlaps'])
            assert not metrics['clippedButtons'], (label,width,metrics['clippedButtons'])
            assert not metrics['offscreen'], (label,width,metrics['offscreen'])
            results.append({'label':label,**metrics})
            print(label+' '+str(width)+'px passed',flush=True)
            if width in [390,820,1440]: screenshot(label+'-'+str(width)+'.png')
    viewport(1440,1000); login('browser-admin')
    audit('recruiting','/admin/manage-participants/'+str(test_id))
    click('form[action="/admin/approve-request/'+str(part_id)+'"] button[type=submit]')
    wait("!document.querySelector('form[action=\"/admin/approve-request/"+str(part_id)+"\"]')")
    navigate('/admin/action-queue'); js('window.confirm=()=>true')
    click('form[action="/admin/action-queue/approve/'+str(pending_id)+'"] button[type=submit]')
    wait("!document.querySelector('form[action=\"/admin/action-queue/approve/"+str(pending_id)+"\"]')")
    with app.app_context():
        assert db.session.get(Participation, part_id).amount_owed == 280
        assert db.session.get(Participation, pending_id).amount_owed == 320
    navigate('/admin/edit-test/'+str(test_id))
    value('[name=status]','ready_for_payment')
    js("document.querySelector('[name=status]').form.submit()")
    wait("location.pathname === '/test/"+str(test_id)+"'")
    audit('frozen-manage','/admin/manage-participants/'+str(test_id))
    audit('frozen-queue','/admin/action-queue')
    navigate('/admin/manage-participants/'+str(test_id))
    field='form[action="/admin/approve-request/'+str(late_id)+'"] [name=buy_in_amount]'
    assert js('document.querySelector('+json.dumps(field)+').value') == '320.00'
    value(field,'75.25')
    click('form[action="/admin/approve-request/'+str(late_id)+'"] button[type=submit]')
    wait("!document.querySelector('form[action=\"/admin/approve-request/"+str(late_id)+"\"]')")
    with app.app_context():
        assert db.session.get(Participation, late_id).amount_owed == 75.25
        assert db.session.get(Participation, pending_id).amount_owed == 320
    audit('group-detail','/test/'+str(test_id))
    assert js("[...document.querySelectorAll('th')].filter(e=>e.textContent.trim()==='Amount Owed').length") == 1
    for width,height in [(390,1000),(820,1180),(1440,1000)]:
        viewport(width,height);js("document.querySelector('td[data-label=\"Amount Owed\"]').closest('table').scrollIntoView()");screenshot('participant-balances-'+str(width)+'.png')
    audit('add-participant','/admin/add-participant/'+str(test_id))
    audit('edit-late-buyer','/admin/update-participant/'+str(late_id))
    navigate('/admin/edit-test/'+str(test_id))
    value('[name=total_lab_cost]','1200')
    js("document.querySelector('[name=status]').form.submit()")
    wait("location.pathname === '/test/"+str(test_id)+"'")
    audit('reprice-preview','/admin/recalculate-costs/'+str(test_id))
    assert js("document.body.innerText.includes('$620.00') && document.body.innerText.includes('$75.25')")
    click('button[type=submit].btn-warning')
    wait("location.pathname === '/admin/manage-participants/"+str(test_id)+"'")
    with app.app_context():
        assert db.session.get(Participation, pending_id).amount_owed == 620
        assert db.session.get(Participation, late_id).amount_owed == 75.25
        assert db.session.get(GroupTest,test_id).costs_locked
    navigate('/admin/edit-test/'+str(test_id));value('[name=status]','recruiting')
    js("document.querySelector('[name=status]').form.submit()")
    wait("location.pathname === '/test/"+str(test_id)+"'")
    audit('unlock-preview','/admin/recalculate-costs/'+str(test_id))
    assert js("document.body.innerText.includes('Confirm Unlock and Recalculate')")
    click('button[type=submit].btn-warning')
    wait("location.pathname === '/admin/manage-participants/"+str(test_id)+"'")
    with app.app_context(): assert not db.session.get(GroupTest,test_id).costs_locked
    assert not exceptions, exceptions
    (artifacts / 'metrics.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('PASS: real-browser approvals, freeze, late override, reprice, reopen and explicit unlock; '+str(len(results))+' responsive checks.',flush=True)
    print('Screenshots: '+str(artifacts),flush=True)
finally:
    try:
        ws.send(json.dumps({'id':999999,'method':'Browser.close'}))
        chrome.wait(timeout=10)
    except Exception:
        chrome.terminate(); chrome.wait(timeout=10)
    server.shutdown(); ws.close(); chrome_log.close()
    with app.app_context():
        db.session.remove(); db.engine.dispose()
    assert folder.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert Path(profile).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    profile_work.cleanup()
    work.cleanup()
