/* Offline, read-only observation of a compiled, single-document prototype. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.MAVIS_PLAYWRIGHT_MODULE || 'playwright');

const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function locate(frame, ref) {
  const key = ref.group ? 'group' : 'region';
  if (!/^[\w-]{1,100}$/.test(ref[key]) || (ref.group && ref.region)) throw Error('Invalid target');
  const matches = frame.locator('[data-' + key + '="' + ref[key] + '"]');
  if (ref.index === undefined) return matches;
  if (!Number.isInteger(ref.index) || ref.index < 0) throw Error('Invalid instance index');
  return matches.nth(ref.index);
}

async function state(frame, check) {
  if (check.kind === 'feedback') {
    return frame.locator('[data-feedback-token]:visible').evaluateAll(es =>
      es.map(e => [e.dataset.feedbackToken, e.innerText]));
  }
  const target = locate(frame, check);
  if (await target.count() !== 1 || !(await target.isVisible())) throw Error('Unresolved observation target');
  if (check.kind === 'value') return target.inputValue();
  if (!['contains', 'text_changes'].includes(check.kind)) throw Error('Unsupported assertion');
  // Read visible business text only. Ignore instrumentation and hidden descendants.
  return target.evaluate(root => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const texts = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.parentElement.closest('[data-feedback-token],script,style')) continue;
      if (getComputedStyle(node.parentElement).visibility !== 'visible') continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      if (range.getBoundingClientRect().width > 0) texts.push(node.textContent.trim());
    }
    return texts.filter(Boolean).join(' ');
  });
}

async function act(frame, step) {
  const target = locate(frame, step);
  if (await target.count() !== 1) throw Error('Missing or ambiguous action target');
  if (step.op === 'fill') await target.fill(step.value);
  else if (step.op === 'select') await target.selectOption(step.value);
  else if (step.op === 'click') await target.click();
  else throw Error('Unsupported operation');
}

async function observe(browser, url, plan, item, directory, n) {
  const ctx = await browser.newContext({viewport:plan.viewport, serviceWorkers:'block'});
  const result = {id:item.id, status:'not_evaluated'};
  try {
    await ctx.route('**/*', route => route.request().url() === url ? route.continue() : route.abort());
    const page = await ctx.newPage();
    page.setDefaultTimeout(3000);
    await page.goto(url);
    const slot = page.locator('iframe[data-slot-id]');
    await slot.first().waitFor();
    if (await slot.count() !== 1) throw Error('Expected one compiled document');
    const frame = page.frameLocator('iframe[data-slot-id]');
    await frame.locator('body').waitFor();
    for (const step of item.setup || []) await act(frame, step);
    const check = item.expect;
    result.before = await state(frame, check);
    const matches = value => {
      if (check.kind === 'value') return value === check.value;
      if (check.kind === 'contains') {
        if (!check.value) throw Error('Empty expected text');
        return value.includes(check.value);
      }
      if (check.kind === 'feedback') return value.length > 0 && JSON.stringify(value) !== JSON.stringify(result.before);
      return value !== result.before;
    };
    if (matches(result.before)) throw Error('Precondition already satisfies assertion');
    result.beforeImage = n + '-before.png';
    await page.screenshot({path:path.join(directory,result.beforeImage)});
    await act(frame, item.action);
    const end = Date.now() + 1500;
    do {
      result.after = await state(frame, check);
      if (matches(result.after)) break;
      await page.waitForTimeout(75);
    } while (Date.now() < end);
    result.afterImage = n + '-after.png';
    await page.screenshot({path:path.join(directory,result.afterImage)});
    result.status = matches(result.after) ? 'passed' : 'failed';
  } catch (err) { result.reason = String(err); }
  finally { await ctx.close(); }
  return result;
}

async function main() {
  const [html, protocol, directory] = process.argv.slice(2);
  const plan = JSON.parse(fs.readFileSync(protocol,'utf8').replace(/^\uFEFF/,''));
  if (plan.version !== 1 || !Array.isArray(plan.actions) || plan.actions.length > 64) throw Error('Unsupported plan');
  fs.mkdirSync(directory,{recursive:true});
  const report = {schema:1, html:digest(fs.readFileSync(html)), protocol:digest(fs.readFileSync(protocol)),
    observer:digest(fs.readFileSync(__filename)), viewport:plan.viewport, results:[]};
  const browser = await chromium.launch({headless:true, executablePath:process.env.MAVIS_CHROMIUM_PATH || undefined});
  try {
    report.browser = browser.version();
    for (const [n,item] of plan.actions.entries()) {
      report.results.push(await observe(browser,pathToFileURL(path.resolve(html)).href,plan,item,directory,n));
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));
}
main().catch(error => {console.error(error);process.exitCode=1});
