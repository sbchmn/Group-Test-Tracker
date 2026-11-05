"""Run with system Python; uses the locally cached Playwright and Edge browser."""
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from datetime import datetime, timedelta

from werkzeug.serving import make_server
from app import create_app, db
from app.models import User, NotificationConfig


output = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as directory:
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'browser.db'),
        'NOTIFICATION_LOG_PATH': str(Path(directory) / 'notifications.log'),
    })
    with app.app_context():
        db.create_all()
        for channel in ('telegram', 'discord'):
            user = User(username=channel + '-member', email=channel + '@example.com',
                        pending_notification_channel=channel,
                        notification_setup_expires_at=datetime.utcnow() + timedelta(days=7))
            user.set_password('secret123')
            db.session.add(user)
        db.session.add_all([
            NotificationConfig(key='telegram_bot_token', value='test-token'),
            NotificationConfig(key='telegram_bot_username', value='example_bot'),
            NotificationConfig(key='discord_bot_token', value='test-discord-token'),
        ])
        db.session.commit()
    server = make_server('127.0.0.1', 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = r'''
const path = require('path');
const { chromium } = require(path.join(process.env.LOCALAPPDATA, 'npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright'));
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  const base = process.env.REVIEW_URL;
  const output = process.env.REVIEW_OUTPUT;
  const widths = [320, 390, 820, 1024, 1280, 1440];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function capture(name) {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 1000 });
      await page.screenshot({ path: path.join(output, `${name}-${width}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) throw Error(`${name} overflows at ${width}px`);
      console.log(`${name}: ${width}px passed`);
    }
  }
  await page.goto(base + '/register', { waitUntil: 'networkidle' });
  if (!(await page.locator('link[href*="bootstrap.min.css"]').evaluate(el => !!el.sheet))) throw Error('Bootstrap failed to load');
  await page.locator('#notification_channel').selectOption('telegram');
  await capture('register');
  await page.locator('#username').fill('TELEGRAM-MEMBER');
  await page.locator('#email').fill('new@example.com');
  await page.locator('#password').fill('secret123');
  await page.locator('#confirm_password').fill('secret123');
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  await page.getByText('Username is already in use.', { exact: true }).waitFor();
  await capture('register-validation');
  for (const channel of ['telegram', 'discord']) {
    await page.goto(base + '/login');
    await page.locator('#username').fill(channel + '-member');
    await page.locator('#password').fill('secret123');
    await page.getByRole('button', { name: 'Login', exact: true }).click();
    await page.waitForURL('**/notification-setup');
    await page.getByRole('button', { name: /^Generate .* link$/ }).click();
    await page.locator('#link-command').waitFor();
    await capture(channel + '-link');
    await page.getByRole('button', { name: 'Use email instead' }).click();
    await page.waitForURL('**/dashboard');
    await page.goto(base + '/logout');
  }
  if (errors.length) throw Error(errors.join('\n'));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
'''
    try:
        environment = dict(os.environ, REVIEW_URL=f'http://127.0.0.1:{server.server_port}', REVIEW_OUTPUT=str(output))
        result = subprocess.run(['node', '-e', script], env=environment, text=True, capture_output=True)
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
