"""Run against an isolated local fixture; requires Chrome and websockets. See README.md."""
import base64, io, json, os, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from websockets.sync.client import connect
from werkzeug.serving import make_server, WSGIRequestHandler
from PIL import Image, ImageDraw
os.environ['GTT_DEPLOYMENT_MODE'] = 'standalone'
os.environ['GTT_MANAGED_INTEGRATIONS'] = '{}'
from app import create_app, db
from app.models import User, GroupTest, PaymentOption, Participation
import app.payments as payments
import app.routes as routes
import app.notifications as notifications

work = tempfile.TemporaryDirectory(prefix='gtt-payment-browser-')
folder = Path(work.name)
artifacts = Path(os.environ.get('BROWSER_ARTIFACTS_DIR') or tempfile.mkdtemp(prefix='gtt-browser-artifacts-'))
artifacts.mkdir(parents=True, exist_ok=True)
receipt = Image.new('RGB', (700, 850), 'white'); draw = ImageDraw.Draw(receipt)
draw.text((60, 80), 'PAYMENT RECEIPT', fill='black', font_size=36)
draw.text((60, 180), 'Lab fee payment: $50.00', fill='black', font_size=26)
draw.text((60, 240), 'Network: Base', fill='black', font_size=26)
draw.text((60, 300), 'Status: Sent', fill='green', font_size=26)
receipt_path = folder / 'receipt.jpg'; receipt.save(receipt_path)
payments.upload_payment_proof = lambda file: 'browser-proof.jpg'
payments.read_payment_proof = lambda key: receipt_path.read_bytes()
payments.payment_proof_storage_ready = lambda: True
routes._notify_payment_claim = lambda *args: None
notifications.send_notification_message = lambda *args: True
app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(folder / 'browser.db'), 'SECRET_KEY': 'browser-test-only', 'NOTIFICATION_LOG_PATH': str(folder / 'notifications.log')})
with app.app_context():
    db.drop_all(); db.create_all()
    member = User(username='browser-member', email='member@example.test'); member.set_password('secret')
    admin = User(username='browser-admin', email='admin@example.test', is_admin=True); admin.set_password('secret')
    db.session.add_all([member, admin]); db.session.flush()
    option = PaymentOption(label='Base lab wallet', method_type='crypto', network='Base', wallet_address='0x1234567890abcdef1234567890abcdef12345678', proof_image_enabled=True, proof_transaction_enabled=True, proof_requirement='either')
    test = GroupTest(title='Payment Proof Browser Review', created_by=admin.id, status='ready_for_payment', payment_options=[option, PaymentOption(label='PayPal laboratory account', method_type='paypal', account_handle='audit-collector')])
    db.session.add(test); db.session.flush()
    part = Participation(group_test_id=test.id, user_id=member.id, approved=True, amount_owed=50, name='Browser Participant')
    db.session.add(part)
    outsider = User(username='browser-pending',email='pending@example.test',password_hash=member.password_hash)
    db.session.add(outsider); db.session.flush()
    db.session.add(Participation(group_test_id=test.id,user_id=outsider.id,approved=False))
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
    def open_modal():
        click('[data-payment-part="' + str(part_id) + '"]'); wait("document.getElementById('paymentModal').classList.contains('show') && !document.getElementById('paymentContent').classList.contains('d-none')")
    def viewport(width, height): call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 600})
    def screenshot(name):
        time.sleep(.4)
        result = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False}); (artifacts / name).write_bytes(base64.b64decode(result['data']))
    def fits():
        return js("({viewport:innerWidth,page:document.documentElement.scrollWidth,modal:document.querySelector('#paymentModal .modal-content').getBoundingClientRect().width,footerBottom:document.querySelector('#paymentModal .modal-footer').getBoundingClientRect().bottom,height:innerHeight})")
    call('Page.enable'); call('Runtime.enable')
    viewport(1440, 1000); login('browser-member'); navigate('/test/' + str(test_id)); open_modal()
    assert js("document.getElementById('paymentMethod').value === '' && document.getElementById('paymentSubmit').disabled"), 'A new multi-method report must open with a valid unselected state'
    assert js("document.getElementById('paymentError').classList.contains('d-none')")
    screenshot('participant-desktop.png'); print('Desktop layout', fits(), flush=True)
    js("bootstrap.Modal.getInstance(document.getElementById('paymentModal')).hide()")
    wait("getComputedStyle(document.getElementById('paymentModal')).display === 'none'")
    js("window.auditOriginalFetch=window.fetch;window.fetch=()=>Promise.reject(new Error('Simulated connection failure'))")
    click('[data-payment-part="'+str(part_id)+'"]')
    wait("!document.getElementById('paymentError').classList.contains('d-none')")
    assert js("['paymentSubmit','paymentApprove','paymentDeny'].every(id=>document.getElementById(id).classList.contains('d-none'))"), 'Failed initialization exposed active decisions'
    js("window.fetch=window.auditOriginalFetch;bootstrap.Modal.getInstance(document.getElementById('paymentModal')).hide()")
    wait("getComputedStyle(document.getElementById('paymentModal')).display === 'none'")
    open_modal()
    value('#paymentMethod',str(option_id));js("document.getElementById('paymentMethod').dispatchEvent(new Event('change'))")
    assert js("!document.getElementById('paymentSubmit').disabled")

    viewport(768, 1024); screenshot('participant-tablet.png'); assert fits()['page'] <= 768
    viewport(320, 740); time.sleep(.3); screenshot('participant-320.png'); print('Small phone layout:', fits(), flush=True); assert fits()['page'] <= 320
    viewport(390, 844); screenshot('participant-mobile.png'); mobile = fits(); print('Mobile layout', mobile, flush=True)
    assert mobile['page'] <= 390 and mobile['footerBottom'] <= mobile['height'] + 1
    value('#paymentTransaction', '0x' + 'a' * 64)
    root = call('DOM.getDocument'); field = call('DOM.querySelector', {'nodeId': root['root']['nodeId'], 'selector': '#paymentImage'})
    call('DOM.setFileInputFiles', {'nodeId': field['nodeId'], 'files': [str(receipt_path)]})
    wait("!document.getElementById('paymentImagePreview').classList.contains('d-none')")
    click('#paymentSubmit'); wait("document.querySelector('[data-payment-part]').textContent.includes('Update Payment')")
    open_modal(); assert js("document.getElementById('paymentTransaction').value") == '0x' + 'a' * 64
    screenshot('participant-update-mobile.png')
    navigate('/logout'); login('browser-admin'); navigate('/admin/action-queue')
    click('#select-all')
    assert js("document.querySelectorAll('.part-checkbox').length===1 && document.querySelector('.part-checkbox').checked"), 'Bulk selection included a payment or omitted a join request'
    assert js("document.getElementById('queue-selection-count').textContent==='1 selected'")
    js("const bulk=document.getElementById('approve-selected-form');bulk.addEventListener('submit',e=>e.preventDefault(),{once:true});bulk.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
    assert js("document.querySelectorAll('#approve-selected-hidden input[name=part_ids]').length===1")
    open_modal()
    wait("document.querySelector('#paymentEvidence a[href^=\"https://basescan.org/tx/\"]') !== null")
    screenshot('admin-review-mobile.png'); assert fits()['page'] <= 390
    click('#paymentDeny'); value('#paymentReason', 'Please confirm the destination wallet.'); click('#paymentDeny')
    wait("getComputedStyle(document.getElementById('paymentModal')).display === 'none'")
    navigate('/logout'); login('browser-member'); navigate('/test/' + str(test_id)); open_modal()
    assert js("document.getElementById('paymentStatus').textContent.includes('Please confirm')")
    value('#paymentTransaction', '0x' + 'b' * 64); click('#paymentSubmit'); wait("document.querySelector('[data-payment-part]').textContent.includes('Update Payment')")
    navigate('/logout'); login('browser-admin'); navigate('/admin/manage-participants/' + str(test_id)); open_modal()
    viewport(320, 740); assert fits()['page'] <= 320; screenshot('admin-manage-mobile.png')
    viewport(1440, 1000); screenshot('admin-review-desktop.png'); click('#paymentApprove')
    wait("getComputedStyle(document.getElementById('paymentModal')).display === 'none'")
    navigate('/logout'); login('browser-member'); navigate('/test/' + str(test_id)); open_modal()
    assert js("document.getElementById('paymentStatus').textContent === 'Payment Verified'")
    assert js("document.getElementById('paymentReportForm').classList.contains('d-none')")
    navigate('/logout');login('browser-admin')
    for path in ['/admin/payment-options','/admin/payment-options/'+str(option_id)+'/edit']:
        for width,height in [(320,740),(820,1180),(1440,1000)]:
            viewport(width,height);navigate(path)
            assert js("!!document.querySelector('[data-proof-policy-preview]').textContent")
            js("document.querySelector('[name=proof_image_enabled]').checked=true;document.querySelector('[name=proof_transaction_enabled]').checked=true")
            for rule,expected in [('either','an image or a transaction ID'),('all','an image and a transaction ID'),('optional','Participants may provide')]:
                value('[name=proof_requirement]',rule)
                js("document.querySelector('[name=proof_requirement]').dispatchEvent(new Event('change',{bubbles:true}))")
                assert expected in js("document.querySelector('[data-proof-policy-preview]').textContent")
        # A missing optional helper must not abort unrelated modal setup.
        assert js("(async()=>{document.querySelector('[data-proof-policy-preview]').remove();const code=await(await fetch('/static/js/payments.js')).text();try{new Function(code)();return true}catch(e){return false}})()")
    viewport(390,844);navigate('/admin/users')
    click('[id^=userMore]')
    wait("document.querySelector('.dropdown-menu.show') !== null")
    call('Input.dispatchKeyEvent',{'type':'keyDown','key':'ArrowDown','code':'ArrowDown','windowsVirtualKeyCode':40})
    assert js("document.activeElement.classList.contains('dropdown-item')")
    call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
    wait("document.querySelector('.dropdown-menu.show') === null")
    assert not exceptions, exceptions
    print('Browser workflow passed: image + transaction submission, update, denial, resubmission, approval, read-only verified payment.', flush=True)
    print('Screenshots: ' + str(artifacts), flush=True)
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
