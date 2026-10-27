/* Read-only HTML evaluation: interact in memory, never rewrite generated assets. */
const fs = require('fs');
const path = require('path');
const {pathToFileURL} = require('url');
const {chromium} = require('playwright');
const [rootArg, outArg, browserPath] = process.argv.slice(2);
(async () => {
  const root = path.resolve(rootArg), out = path.resolve(outArg);
  fs.mkdirSync(out, {recursive: false});
  const browser = await chromium.launch({headless: true, executablePath: browserPath});
  const reports = [];
  try {
    for (const name of fs.readdirSync(root).filter(n => fs.statSync(path.join(root,n)).isDirectory())) {
      for (const mode of ['baseline', 'native_controls_v1']) {
        const run = path.join(root,name,mode);
        const state = JSON.parse(fs.readFileSync(path.join(run,'ui_state.json'),'utf8'));
        const context = await browser.newContext({viewport: state.page_meta.viewport, serviceWorkers: 'block', acceptDownloads: false});
        const blocked = [], errors = [];
        await context.route('**/*', route => {
          const url = route.request().url();
          if (url === pathToFileURL(path.join(run,'final_code.html')).href || /^(data:|about:)/.test(url)) return route.continue();
          blocked.push(url.split('?')[0]); return route.abort();
        });
        const page = await context.newPage();
        page.on('pageerror', e => errors.push(e.message));
        page.on('dialog', d => d.dismiss());
        await page.goto(pathToFileURL(path.join(run,'final_code.html')).href, {waitUntil:'load'});
        const controls = page.locator('input:not([type="hidden"]),textarea,[contenteditable="true"]');
        const checks = [];
        for (let i=0; i<await controls.count(); i++) {
          const control = controls.nth(i);
          const item = await control.evaluate(n => ({id:n.id, tag:n.tagName, type:n.type || '', placeholder:n.getAttribute('placeholder'), box: {x:n.getBoundingClientRect().x, y:n.getBoundingClientRect().y, width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height}}));
          try { await control.click({timeout:1500}); item.click='passed'; }
          catch(e) { item.click='failed'; item.click_error=e.message.split('\n')[0]; }
          try {
            const sample = item.type === 'number' ? '42' : `mavis_check_${i}`;
            await control.fill(sample,{timeout:1500});
            const value = await control.evaluate(n => 'value' in n ? n.value : n.textContent);
            item.fill = value === sample ? 'passed' : 'failed';
          } catch(e) { item.fill='failed'; item.fill_error=e.message.split('\n')[0]; }
          checks.push(item);
        }
        await page.screenshot({path:path.join(out,`${name}_${mode}.png`)});
        reports.push({case:name,mode,checks,page_errors:errors,blocked_resources:[...new Set(blocked)]});
        await context.close();
      }
    }
    fs.writeFileSync(path.join(out,'native_controls.json'),JSON.stringify({browser_version:browser.version(),condition:'offline_external_resources_blocked',limits:'Native controls inspected independently of UI-State ids. Not full-page visual scoring; truncated outputs remain failures.',reports},null,2));
    console.log(JSON.stringify(reports));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
