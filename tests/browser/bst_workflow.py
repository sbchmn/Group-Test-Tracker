"""Local Chrome checks for mixed queue and BST administration; no live delivery."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from urllib.request import urlopen

from websockets.sync.client import connect
from werkzeug.serving import make_server, WSGIRequestHandler

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import create_app, db
from app.models import BSTTopic, BSTVendor, GroupTest, Participation, ResultAnalysisRun, User
from app import bst_service as bst


work = tempfile.TemporaryDirectory(prefix='gtm-bst-browser-')
folder = Path(work.name)
artifacts = Path(os.environ.get('BROWSER_ARTIFACTS_DIR') or tempfile.mkdtemp(prefix='gtm-bst-screenshots-'))
artifacts.mkdir(parents=True, exist_ok=True)
app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SECRET_KEY': 'browser-test-only',
                  'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(folder / 'browser.db'),
                  'NOTIFICATION_LOG_PATH': str(folder / 'notifications.log')})
bst._telegram_api_post = lambda method, payload: (True, {'result': {'id': 900, 'status': 'administrator', 'can_delete_messages': True}})
bst.send_notification_message = lambda *args, **kwargs: True
bst.send_mailjet_message = lambda *args, **kwargs: True
with app.app_context():
    db.create_all()
    admin = User(username='browser-admin', email='admin@example.com', is_admin=True, telegram_user_id='99')
    admin.set_password('secret')
    db.session.add(admin)
    topic = BSTTopic(chat_id='-1001', thread_id=7, name='Community BST Listings', code='testcode', enabled=True, options={})
    db.session.add(topic)
    db.session.flush()
    test = GroupTest(title='Shared queue recruiting test', status='recruiting', created_by=admin.id)
    db.session.add(test)
    db.session.flush()
    db.session.add(Participation(user_id=admin.id, group_test_id=test.id, name='Pending participant', approved=False, denied=False))
    db.session.add(ResultAnalysisRun(group_test_id=test.id, source_kind='link', source_reference='https://example.com/coa.pdf',
                                     provider='openai', provider_model='example-model', status='failed', error_message='Review this analysis failure.'))
    vendor = BSTVendor(topic_id=topic.id, telegram_user_id='42', status='pending', submitted_at=datetime.utcnow(),
                        draft={'vendor_name': 'Example vendor', 'email': 'vendor@example.com', 'guarantees': 'Replacement for damaged deliveries. ' * 20,
                               'dispute_contact': '@vendor_support', 'dispute_process': 'Contact support with order details within fourteen days.'})
    db.session.add(vendor)
    db.session.commit()
    topic_id, vendor_id = topic.id, vendor.id


class QuietHandler(WSGIRequestHandler):
    def log(self, *args):
        pass


server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'
profile = folder / 'chrome-profile'
log = open(folder / 'chrome.log', 'w')
chrome = subprocess.Popen([os.environ.get('CHROME_BINARY', r'C:\Program Files\Google\Chrome\Application\chrome.exe'),
    '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--no-sandbox', '--ignore-certificate-errors',
    '--remote-debugging-port=0', '--remote-allow-origins=*', '--user-data-dir=' + str(profile), 'about:blank'],
    stdout=subprocess.DEVNULL, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
ws = None
try:
    deadline = time.time() + 25
    while not (profile / 'DevToolsActivePort').exists() and time.time() < deadline:
        time.sleep(.1)
    port = (profile / 'DevToolsActivePort').read_text().splitlines()[0]
    tabs = json.load(urlopen('http://127.0.0.1:' + port + '/json/list'))
    ws = connect(next(tab['webSocketDebuggerUrl'] for tab in tabs if tab['type'] == 'page'), max_size=20000000, legacy=True, proxy=None, compression=None)
    sequence = 0
    exceptions = []

    def call(method, params=None):
        global sequence
        sequence += 1
        ident = sequence
        ws.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
        while True:
            result = json.loads(ws.recv(timeout=30))
            if result.get('method') == 'Runtime.exceptionThrown':
                exceptions.append(result['params'])
            if result.get('id') == ident:
                if 'error' in result:
                    raise RuntimeError(result['error'])
                return result.get('result', {})

    def js(expression):
        result = call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    def wait(expression):
        deadline = time.time() + 20
        while time.time() < deadline:
            if js(expression):
                return
            time.sleep(.1)
        raise RuntimeError('Timed out: ' + expression)

    def navigate(path):
        call('Page.navigate', {'url': base + path})
        wait('document.readyState === "complete" && location.pathname === ' + json.dumps(path.split('?')[0]))

    def value(selector, content):
        js('document.querySelector(' + json.dumps(selector) + ').value=' + json.dumps(content))

    call('Runtime.enable')
    navigate('/login')
    value('[name=username]', 'browser-admin')
    value('[name=password]', 'secret')
    js('document.querySelector("form").submit()')
    wait('location.pathname === "/dashboard" && document.readyState === "complete"')
    pages = ['/admin/action-queue', '/admin/bst', f'/admin/bst/topics/{topic_id}', '/admin/bst/vendors/new',
             f'/admin/bst/vendors/{vendor_id}?return_to=queue']
    for width in [320, 390, 820, 1440]:
        call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': width < 500})
        for number, path in enumerate(pages):
            navigate(path)
            wait('typeof bootstrap !== "undefined"')
            metrics = js('({width:innerWidth, page:document.documentElement.scrollWidth})')
            assert metrics['page'] <= width + 1, (path, width, metrics)
            if path == '/admin/action-queue':
                assert js('document.querySelectorAll("table").length === 1')
                assert js('document.querySelectorAll(".part-checkbox").length === 1')
                assert js('document.body.textContent.includes("BST Application") && document.body.textContent.includes("Inspect Failure")')
            data = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True})
            (artifacts / f'bst-{number}-{width}.png').write_bytes(base64.b64decode(data['data']))
    navigate(f'/admin/bst/vendors/{vendor_id}?return_to=queue&type=bst')
    value('[name=reason]', 'Please clarify your dispute process.')
    js('document.querySelector("button[value=changes]").click()')
    wait('location.pathname === "/admin/action-queue" && document.readyState === "complete"')
    assert js('!document.body.textContent.includes("BST Application")')
    navigate(f'/admin/bst/vendors/{vendor_id}')
    assert js('document.body.textContent.includes("Please clarify your dispute process.")')
    navigate('/admin/bst/vendors/new')
    for field, content in {'topic_id': str(topic_id), 'telegram_user_id': '12345', 'vendor_name': 'Preapproved vendor',
                            'email': 'preapproved@example.com', 'guarantees': 'Replacement guarantee',
                            'dispute_contact': '@support', 'dispute_process': 'Contact support within fourteen days.'}.items():
        value('[name=' + field + ']', content)
    js('document.querySelector("form").submit()')
    wait('location.pathname.startsWith("/admin/bst/vendors/") && !location.pathname.endsWith("new") && document.readyState === "complete"')
    assert js('document.body.textContent.includes("Posting: Approved")')
    assert not exceptions, exceptions
    print('BST browser checks passed: 20 responsive views, one mixed queue, change-request return, and admin preapproval.')
    print('Screenshots: ' + str(artifacts))
finally:
    if ws:
        try:
            ws.send(json.dumps({'id': 999999, 'method': 'Browser.close'}))
            chrome.wait(timeout=10)
        except Exception:
            chrome.terminate()
            chrome.wait(timeout=10)
        ws.close()
    else:
        chrome.terminate()
        chrome.wait(timeout=10)
    server.shutdown()
    log.close()
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    assert folder.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    work.cleanup()
