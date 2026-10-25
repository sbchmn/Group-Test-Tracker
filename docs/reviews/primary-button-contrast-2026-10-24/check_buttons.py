"""Verify rendered primary-button colors in both themes and interaction states."""
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread

from werkzeug.serving import make_server, WSGIRequestHandler
from app import create_app, db


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


output = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as directory:
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'buttons.db')})
    with app.app_context():
        db.create_all()
    server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = r'''
const path = require('path');
const { chromium } = require(path.join(process.env.LOCALAPPDATA, 'npm-cache/_npx/9833c18b2d85bc59/node_modules/playwright'));
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const page = await browser.newPage();
  await page.goto(process.env.REVIEW_URL+'/login',{waitUntil:'networkidle'});
  for (const mode of ['light','dark']) {
    await page.locator('.appearance-control select').selectOption(mode);
    await Promise.all([page.waitForNavigation({waitUntil:'networkidle'}),page.locator('.appearance-control button').click()]);
    for (const width of [390,820,1440]) {
      await page.setViewportSize({width,height:900});
      const button = page.locator('button.btn-primary');
      await page.mouse.move(0,0);
      await page.waitForTimeout(200);
      async function check(state) {
        const colors = await button.evaluate(element => {
          const style = getComputedStyle(element);
          return {foreground:style.color,background:style.backgroundColor};
        });
        const luminance = color => {
          const channels = color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
          return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
        };
        const values = [luminance(colors.foreground),luminance(colors.background)].sort((a,b)=>b-a);
        const ratio = (values[0]+.05)/(values[1]+.05);
        if (ratio < 4.5) throw Error(`${mode} ${state}: contrast ${ratio}`);
        if (mode === 'light' && colors.foreground !== 'rgb(255, 255, 255)') throw Error(`Light button label is not white: ${colors.foreground}`);
        console.log(`${mode} ${width}px ${state}: ${colors.foreground} on ${colors.background}, ${ratio.toFixed(2)}:1 passed`);
      }
      await check('normal');
      await page.screenshot({path:path.join(process.env.REVIEW_OUTPUT,`${mode}-${width}.png`),fullPage:true});
      await button.hover();
      await page.waitForTimeout(200);
      await check('hover');
      await page.mouse.down();
      await check('active');
      await page.mouse.move(0,0);
      await page.mouse.up();
      await button.evaluate(element=>element.disabled=true);
      await page.waitForTimeout(200);
      await check('disabled colors');
      await button.evaluate(element=>element.disabled=false);
    }
  }
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
'''
    try:
        environment = dict(os.environ, REVIEW_URL=f'http://127.0.0.1:{server.server_port}', REVIEW_OUTPUT=str(output))
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
