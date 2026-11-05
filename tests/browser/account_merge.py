"""Run against an isolated local fixture; requires Chrome and websockets. See README.md."""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from websockets.sync.client import connect
from werkzeug.serving import make_server, WSGIRequestHandler
os.environ['GTT_DEPLOYMENT_MODE'] = 'standalone'
os.environ['GTT_MANAGED_INTEGRATIONS'] = '{}'
from app import create_app, db
from app.models import User, GroupTest, PaymentOption, Participation, PaymentSubmission, AccountMergeAudit
import app.routes as routes
import app.notifications as notifications

work = tempfile.TemporaryDirectory(prefix='gtt-merge-browser-')
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
    test = GroupTest(title='Account Merge Browser Review', created_by=admin.id, status='recruiting', total_lab_cost=600, refund_per_donor=20, payment_options=[option, PaymentOption(label='PayPal laboratory account', method_type='paypal', account_handle='audit-collector')])
    db.session.add(test); db.session.flush()
    part = Participation(group_test_id=test.id, user_id=member.id, approved=False, vial_donor=True, amount_owed=0, name='Browser Participant')
    db.session.add(part)
    outsider = User(username='browser-pending',email='pending@example.test',password_hash=member.password_hash)
    db.session.add(outsider); db.session.flush()
    pending = Participation(group_test_id=test.id,user_id=outsider.id,approved=False, name='Pending non-donor'); db.session.add(pending); db.session.flush(); pending_id = pending.id
    late_user = User(username='late-buyer',email='late@example.test',password_hash=member.password_hash); db.session.add(late_user); db.session.flush()
    late = Participation(group_test_id=test.id,user_id=late_user.id,approved=False,name='Late access buyer'); db.session.add(late); db.session.flush(); late_id = late.id
    db.session.commit(); test_id = test.id; part_id = part.id; option_id = option.id
with app.app_context():
    from app import costs
    test=db.session.get(GroupTest,test_id)
    p=db.session.get(Participation,part_id);d=db.session.get(Participation,pending_id)
    p.approved=True;d.approved=True
    p.user.telegram_user_id='111';p.user.telegram_chat_id='111';d.user.telegram_user_id='222';d.user.telegram_chat_id='222'
    primary_id=p.user_id;duplicate_id=d.user_id
    costs.freeze(test,test.created_by);test.status='ready_for_payment'
    p.amount_owed=100;p.amount_paid=100;p.paid_lab=True
    d.amount_owed=120;d.amount_paid=25
    for part,amount,status in [(p,100,'approved'),(d,25,'pending')]:
        db.session.add(PaymentSubmission(participation=part,amount=amount,status=status,method_snapshot={'title':'Lab payment','network':'Base','method_type':'crypto'},transaction_id=part.name.replace(' ','')+'-tx'))
    unique_test=GroupTest(title='Paid transfer identity check',created_by=test.created_by,status='closed')
    db.session.add(unique_test);db.session.flush();unique_test_id=unique_test.id
    transferred=Participation(group_test_id=unique_test.id,user_id=duplicate_id,name=d.user.username,
        tg_username='old_handle',approved=True,amount_owed=75,amount_paid=75,paid_lab=True)
    db.session.add(transferred);db.session.flush();transferred_id=transferred.id
    db.session.add(PaymentSubmission(participation=transferred,amount=75,status='approved',
        method_snapshot={'title':'Original paid transfer'},transaction_id='original-paid-tx'))
    db.session.commit()
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
    results=[]
    def audit(label,path):
        for width,height in [(320,900),(390,1000),(820,1180),(1024,1100),(1440,1000)]:
            viewport(width,height);navigate(path);time.sleep(.3)
            metrics=js(metrics_code)
            assert metrics['pageWidth']<=width,(label,width,metrics)
            assert not metrics['overlaps'],(label,width,metrics['overlaps'])
            assert not metrics['clippedButtons'],(label,width,metrics['clippedButtons'])
            assert not metrics['offscreen'],(label,width,metrics['offscreen'])
            results.append({'label':label,**metrics})
            if width in [390,820,1440]:screenshot(label+'-'+str(width)+'.png')
            print(label+' '+str(width)+'px passed',flush=True)
    viewport(1440,1000);login('browser-admin')
    audit('manage-users','/admin/users')
    audit('merge-select','/admin/users/merge')
    preview_path='/admin/users/merge?primary_id='+str(primary_id)+'&duplicate_id='+str(duplicate_id)
    audit('merge-preview',preview_path)
    assert js("document.querySelectorAll('#paymentModal').length===1")
    for kind in ['membership','charge','payment']:value('[name='+kind+'_'+str(test_id)+']','primary')
    value('[name=link_telegram]','duplicate')
    js("document.querySelector('[name=confirm_merge]').checked=true")
    click('button[type=submit].btn-danger')
    wait("location.pathname === '/admin/users'")
    assert js("document.body.innerText.includes('Accounts merged')")
    with app.app_context():
        assert db.session.get(User,duplicate_id) is None
        assert db.session.get(User,primary_id).telegram_user_id=='222'
        assert AccountMergeAudit.query.count()==1
        kept=db.session.get(Participation,part_id)
        assert kept.amount_owed==100 and kept.amount_paid==100 and kept.paid_lab
        assert len(kept.payment_submissions)==2
        transferred=db.session.get(Participation,transferred_id)
        assert (transferred.user_id,transferred.name)==(primary_id,'browser-member')
        assert transferred.paid_lab and transferred.amount_paid==75 and transferred.amount_owed==75
        assert transferred.current_payment_submission.transaction_id=='original-paid-tx'
    for label,path in [('paid-transfer-group','/test/'+str(unique_test_id)),
                       ('paid-transfer-manage','/admin/manage-participants/'+str(unique_test_id))]:
        audit(label,path)
        assert js("document.querySelector('td[data-label=\"Name / TG\"]').textContent.trim().startsWith('browser-member')")
        assert js("!document.querySelector('td[data-label=\"Name / TG\"]').textContent.includes('browser-pending')")
        for width,height in [(390,1000),(820,1180),(1440,1000)]:
            viewport(width,height)
            js("document.querySelector('td[data-label=\"Name / TG\"]').scrollIntoView({block:'center'})")
            screenshot(label+'-participant-'+str(width)+'.png')
    navigate('/admin/manage-participants/'+str(test_id))
    click('[data-payment-part="'+str(part_id)+'"]')
    wait("document.getElementById('paymentModal').classList.contains('show') && !document.getElementById('paymentContent').classList.contains('d-none')")
    assert js("document.getElementById('paymentHistoryContent').textContent.includes('archived by account merge')")
    assert js("document.getElementById('paymentHistoryContent').querySelectorAll('details').length===1")
    for width,height in [(390,1000),(820,1180),(1440,1000)]:
        viewport(width,height);screenshot('merged-payment-history-'+str(width)+'.png')
    navigate('/logout');navigate('/register')
    value('[name=username]',' bad name ');value('[name=email]','new@example.test');value('[name=password]','secret123');value('[name=confirm_password]','secret123')
    click('button[type=submit]')
    wait("document.querySelector('.invalid-feedback')?.textContent.includes('whitespace')")
    for width,height in [(390,1000),(820,1180),(1440,1000)]:
        viewport(width,height);screenshot('username-validation-'+str(width)+'.png')
    assert not exceptions,exceptions
    (artifacts/'metrics.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('PASS: merge, conflict resolution, archived evidence and username rejection; '+str(len(results))+' responsive checks. Screenshots: '+str(artifacts),flush=True)
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
