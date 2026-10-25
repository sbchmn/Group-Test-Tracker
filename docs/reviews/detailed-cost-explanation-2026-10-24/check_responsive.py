"""Review collapsed/expanded math in both themes using temporary sample groups."""
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread

from werkzeug.serving import make_server, WSGIRequestHandler
from app import create_app, db, costs
from app.models import GroupTest, Participation, User


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


output = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as directory:
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'costs.db')})
    with app.app_context():
        db.create_all()
        admin = User(username='admin', email='admin@example.com', is_admin=True)
        donor = User(username='donor', email='donor@example.com')
        admin.set_password('secret123')
        donor.set_password('secret123')
        db.session.add_all([admin, donor])
        db.session.flush()
        single = GroupTest(title='Single participant example', created_by=admin.id, total_lab_cost=883, refund_per_donor=20, status='recruiting')
        mixed = GroupTest(title='Donor and shipping example', created_by=admin.id, total_lab_cost=100, shipping_cost=20, donor_shipping_cost=15, donor_shipping_reimbursement='credit', refund_per_donor=20, status='recruiting')
        older = GroupTest(title='Eight members, one vial donor', created_by=admin.id, total_lab_cost=883, refund_per_donor=20, status='recruiting')
        db.session.add_all([single, mixed, older])
        db.session.flush()
        db.session.add_all([
            Participation(group_test_id=single.id, user_id=admin.id, approved=True),
            Participation(group_test_id=mixed.id, user_id=admin.id, approved=True),
            Participation(group_test_id=mixed.id, user_id=donor.id, approved=True, vial_donor=True),
            Participation(group_test_id=older.id, user_id=admin.id, approved=True),
            Participation(group_test_id=older.id, user_id=donor.id, approved=True, vial_donor=True),
        ])
        for number in range(6):
            member = User(username=f'member{number}', email=f'member{number}@example.com', password_hash='hash')
            db.session.add(member)
            db.session.flush()
            db.session.add(Participation(group_test_id=older.id, user_id=member.id, approved=True))
        db.session.flush()
        costs.recalculate(single)
        costs.recalculate(older)
        older.status = 'ready_for_payment'
        costs.freeze(single, admin.id)
        single.status = 'ready_for_payment'
        costs.freeze(mixed, admin.id)
        mixed.status = 'ready_for_payment'
        additional = User(username='additional', email='additional@example.com', password_hash='hash')
        db.session.add(additional)
        db.session.flush()
        for group in (mixed, older):
            part = Participation(group_test_id=group.id, user_id=additional.id, name='Additional member example', approved=False)
            db.session.add(part)
            db.session.flush()
            costs.price_approval(part, override='75')
            part.approved = True
        db.session.commit()
        single_id, mixed_id, older_id = single.id, mixed.id, older.id
    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = r'''
const path = require('path');
const {chromium} = require(path.join(process.env.LOCALAPPDATA,'npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright'));
(async()=>{
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const page = await browser.newPage();
  const base = process.env.REVIEW_URL;
  await page.goto(base+'/login',{waitUntil:'networkidle'});
  await page.locator('#username').fill('admin');
  await page.locator('#password').fill('secret123');
  await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}),page.getByRole('button',{name:'Login',exact:true}).click()]);
  for (const mode of ['light','dark']) {
    await page.locator('.appearance-control select').selectOption(mode);
    await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}),page.locator('.appearance-control button').click()]);
    for (const [name,url] of [['single','/test/'+process.env.SINGLE_ID],['mixed','/test/'+process.env.MIXED_ID],['manage','/admin/manage-participants/'+process.env.MIXED_ID],['older-eight','/test/'+process.env.OLDER_ID],['older-manage','/admin/manage-participants/'+process.env.OLDER_ID]]) {
      const response = await page.goto(base+url,{waitUntil:'networkidle'});
      if(response.status()!==200) throw Error(`${url}: ${response.status()}`);
      const details = page.locator('details').filter({has:page.locator('summary', {hasText:'How the split works'})});
      if(await details.getAttribute('open')!==null) throw Error('Math is not initially collapsed');
      if(name!=='single' && await page.locator('.badge').filter({hasText:/^Additional member$/}).count()<1) throw Error(`${name} lacks the additional-member badge`);
      await details.locator('summary').click();
      if(await details.getAttribute('open')===null) throw Error('Math did not expand');
      if(name.startsWith('older') && !(await details.innerText()).includes('÷ 8 cost-sharing participants')) throw Error('Additional member entered the original eight-member cost basis');
      for(const width of [320,390,820,1024,1280,1440]) {
        await page.setViewportSize({width,height:1000});
        if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error(`${name} overflows at ${width}`);
        if([390,1440].includes(width)) await page.screenshot({path:path.join(process.env.REVIEW_OUTPUT,`${name}-${mode}-${width}.png`),fullPage:true});
        console.log(`${name} ${mode} ${width}px: collapsed/expanded math passed`);
      }
    }
  }
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
'''
    try:
        environment = dict(os.environ, REVIEW_URL=f'http://127.0.0.1:{server.server_port}', REVIEW_OUTPUT=str(output), SINGLE_ID=str(single_id), MIXED_ID=str(mixed_id), OLDER_ID=str(older_id))
        result = subprocess.run(['node', '-e', script], env=environment, capture_output=True, text=True)
        (output / 'browser-checks.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
        print(result.stdout + result.stderr)
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        server.shutdown()
        thread.join()
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
