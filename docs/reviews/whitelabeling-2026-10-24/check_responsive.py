"""End-to-end branding publication and responsive theme review with temporary data."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread

from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage
from werkzeug.serving import make_server, WSGIRequestHandler

from app import create_app, db
from app.branding import DEFAULTS, create_asset, validate_settings
from app.models import BrandingState, GroupTest, Participation, PaymentOption, User


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


output = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as directory:
    app = create_app({'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'browser.db'),
        'NOTIFICATION_LOG_PATH': str(Path(directory) / 'notifications.log')})
    with app.app_context():
        db.create_all()
        admin = User(username='admin', email='admin@example.com', is_admin=True)
        admin.set_password('secret123')
        db.session.add(admin)
        db.session.flush()
        image = Image.new('RGBA', (700, 180))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 15, 150, 165), radius=25, fill='#a98df5')
        draw.line((30, 125, 75, 45, 120, 125), fill='white', width=12)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        asset = create_asset(FileStorage(stream=buffer, filename='logo.png'))
        draft, errors = validate_settings({**DEFAULTS, 'enabled': True,
            'name': 'Northstar Community Laboratory Testing Cooperative', 'short_name': 'Northstar Labs',
            'tagline': 'Clear results. Shared progress.', 'font': 'figtree',
            'intro': 'Coordinate community lab testing, share costs, and follow every result in one place.',
            'light_accent': '#6545b8', 'light_nav': '#252036', 'dark_accent': '#b69cff',
            'dark_nav': '#14111e', 'dark_surface': '#211f2b', 'logo': asset.id,
            'operator_name': 'Northstar Community', 'legal_email': 'privacy@example.com'})
        assert not errors, errors
        db.session.add(BrandingState(id=1, draft=draft, published=dict(DEFAULTS)))
        wallet = PaymentOption(label='Community lab wallet', method_type='crypto', network='Base',
            wallet_address='0x123', proof_image_enabled=True, proof_transaction_enabled=True, proof_requirement='either')
        test = GroupTest(title='Community purity and sterility panel', created_by=admin.id,
            status='ready_for_payment', total_lab_cost=120, payment_options=[wallet])
        db.session.add(test)
        db.session.flush()
        db.session.add(Participation(group_test_id=test.id, user_id=admin.id, approved=True, amount_owed=42, name='Alex Community'))
        db.session.commit()
        test_id = test.id
    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = r'''
const path = require('path');
const { chromium } = require(path.join(process.env.LOCALAPPDATA, 'npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright'));
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = process.env.REVIEW_URL;
  const out = process.env.REVIEW_OUTPUT;
  const widths = [320, 390, 820, 1024, 1280, 1440];
  async function visit(url) {
    const response = await page.goto(base + url, { waitUntil: 'networkidle' });
    if (response.status() !== 200) throw Error(`${url}: HTTP ${response.status()}`);
    await page.evaluate(() => document.fonts.ready);
  }
  async function capture(name, screenshots=true) {
    for (const width of widths) {
      await page.setViewportSize({width, height:1000});
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        const bad = await page.locator('body *').evaluateAll(elements => elements.filter(e => e.getBoundingClientRect().right > innerWidth + 1 && getComputedStyle(e).display !== 'none').slice(0,10).map(e => `${e.tagName}.${e.className}`));
        throw Error(`${name} overflow at ${width}: ${bad.join(', ')}`);
      }
      if (screenshots && [390,820,1440].includes(width)) await page.screenshot({path:path.join(out,`${name}-${width}.png`),fullPage:true});
      if (name.startsWith('editor-') && width === 390) await page.screenshot({path:path.join(out,`${name}-390-viewport.png`)});
      console.log(`${name}: ${width}px passed`);
    }
  }
  async function theme(mode) {
    await page.locator('.appearance-control select').selectOption(mode);
    await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}), page.locator('.appearance-control button').click()]);
    if (await page.locator('html').getAttribute('data-bs-theme') !== mode) throw Error('Theme preference not applied');
  }
  await visit('/login');
  await page.locator('#username').fill('admin');
  await page.locator('#password').fill('secret123');
  await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}), page.getByRole('button',{name:'Login',exact:true}).click()]);
  await visit('/admin/branding');
  await page.getByRole('button',{name:'Publish saved draft',exact:true}).click();
  await page.getByText('Branding published.',{exact:false}).waitFor();
  if (process.env.REVIEW_PUBLIC_ONLY) {
    await page.locator('#name').fill('A'.repeat(80));
    await page.locator('#short_name').fill('B'.repeat(32));
    await page.locator('#font').selectOption('lora');
    await page.getByRole('button',{name:'Save draft',exact:true}).click();
    await page.getByText('Branding draft saved.',{exact:false}).waitFor();
    await visit('/admin/branding/preview/home?theme=dark');
    await capture('long-name-preview',true);
    await page.setViewportSize({width:320,height:1000});
    const navFits = await page.evaluate(() => {
      const brand = document.querySelector('.navbar-brand').getBoundingClientRect();
      const toggle = document.querySelector('.navbar-toggler').getBoundingClientRect();
      return brand.left < toggle.left && toggle.top < brand.bottom && toggle.bottom > brand.top;
    });
    if (!navFits) throw Error('Mobile menu button wrapped below the long brand name');
    await visit('/test/'+process.env.REVIEW_TEST_ID);
    await theme('dark');
    const badgesReadable = await page.locator('.badge.bg-info, .badge.bg-warning').evaluateAll(badges => {
      const light = color => {
        const values = color.match(/[\d.]+/g).slice(0,3).map(value => Number(value)/255).map(value => value <= .04045 ? value/12.92 : ((value+.055)/1.055)**2.4);
        return values[0]*.2126 + values[1]*.7152 + values[2]*.0722;
      };
      return badges.length > 0 && badges.every(badge => {
        const style = getComputedStyle(badge);
        const values = [light(style.color), light(style.backgroundColor)].sort((a,b)=>b-a);
        return (values[0]+.05)/(values[1]+.05) >= 4.5;
      });
    });
    if (!badgesReadable) throw Error('Status badge contrast failed in dark mode');
    await capture('detail-dark',true);
    await visit('/logout');
    for (const mode of ['light','dark']) {
      await theme(mode);
      await visit('/');
      if (await page.locator('.landing-logo-dark').isVisible() !== (mode === 'dark')) throw Error('Dark landing logo visibility is incorrect');
      if (await page.locator('.landing-logo-light').isVisible() !== (mode === 'light')) throw Error('Light landing logo visibility is incorrect');
      await capture('welcome-'+mode,true);
    }
    await browser.close();
    return;
  }
  for (const mode of ['light','dark']) {
    await theme(mode);
    for (const [name,url,shots] of [
      ['editor','/admin/branding',true],['dashboard','/dashboard',true],
      ['settings','/admin/settings',false],['users','/admin/users',false],
      ['profile','/profile',false],['queue','/admin/action-queue',false],
      ['detail','/test/'+process.env.REVIEW_TEST_ID,true]]) {
      await visit(url);
      await capture(name+'-'+mode,shots);
    }
    await page.locator('[data-payment-mode="report"]').first().click();
    await page.locator('#paymentModal.show').waitFor();
    await capture('payment-modal-'+mode,true);
    await page.locator('#paymentModal [data-bs-dismiss="modal"]').first().click();
    await page.locator('#paymentModal.show').waitFor({state:'hidden'});
  }
  await visit('/admin/branding');
  await page.locator('#font').selectOption('lora');
  await page.locator('#name').fill('A'.repeat(80));
  await page.locator('#short_name').fill('B'.repeat(32));
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await page.getByText('Branding draft saved.',{exact:false}).waitFor();
  const previewBody = page.frameLocator('#branding-preview').locator('body');
  await previewBody.waitFor();
  const loraLoaded = await previewBody.evaluate(async () => { await document.fonts.load('16px "GTM Lora"'); return document.fonts.check('16px "GTM Lora"'); });
  if (!loraLoaded) throw Error('Local Lora font failed to load');
  await visit('/admin/branding/preview/home?theme=dark');
  await capture('long-name-preview',true);
  await visit('/admin/branding');
  await page.locator('#preview-surface').selectOption('email');
  await page.frameLocator('#branding-preview').getByRole('heading',{name:'Sample email'}).waitFor();
  await page.locator('#preview-width').selectOption('820');
  await page.locator('#preview-theme').selectOption('dark');
  await page.frameLocator('#branding-preview').locator('html[data-bs-theme="dark"]').waitFor();
  if (!(await page.evaluate(() => document.fonts.check('16px "GTM Figtree"')))) throw Error('Local font failed to load');
  await visit('/logout');
  for (const mode of ['light','dark']) {
    await theme(mode);
    for (const [name,url] of [['welcome','/'],['login','/login'],['register','/register'],['terms','/terms']]) {
      await visit(url);
      await capture(name+'-'+mode, name !== 'terms');
    }
  }
  await page.locator('.appearance-control select').selectOption('system');
  await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}),page.locator('.appearance-control button').click()]);
  await page.emulateMedia({colorScheme:'dark'});
  await page.waitForFunction(() => document.documentElement.getAttribute('data-bs-theme') === 'dark');
  await page.emulateMedia({colorScheme:'light'});
  await page.waitForFunction(() => document.documentElement.getAttribute('data-bs-theme') === 'light');
  if (errors.length) throw Error(errors.join('\n'));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
'''
    try:
        environment = dict(os.environ, REVIEW_URL=f'http://127.0.0.1:{server.server_port}', REVIEW_OUTPUT=str(output), REVIEW_TEST_ID=str(test_id))
        result = subprocess.run(['node', '-e', script], env=environment, text=True, capture_output=True)
        report_name = 'public-logo-checks.txt' if os.environ.get('REVIEW_PUBLIC_ONLY') else 'browser-checks.txt'
        (output / report_name).write_text(result.stdout + result.stderr, encoding='utf-8')
        print(result.stdout + result.stderr)
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        server.shutdown()
        thread.join()
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
