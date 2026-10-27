/* Read-only evaluation of freshly generated files. No HTML repair. */
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {pathToFileURL}=require('url');
const {chromium}=require(process.env.MAVIS_PLAYWRIGHT_MODULE || 'playwright');
const [root,out,executablePath,networkMode]=process.argv.slice(2);
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath});
 const reports=[];
 try {for(const arm of fs.readdirSync(root)) {
  const run=path.join(root,arm),html=path.join(run,'final_code.html');
  if(!fs.existsSync(html))continue;
  const state=JSON.parse(fs.readFileSync(path.join(run,'ui_state.json'),'utf8')),before=sha(html);
  const ctx=await browser.newContext({viewport:state.page_meta.viewport,serviceWorkers:'block'});
  const errors=[],dialogs=[],blocked=[];
  await ctx.route('**/*',r=>(networkMode==='online'||/^(file:|data:|about:)/.test(r.request().url()))?r.continue():(blocked.push(r.request().url()),r.abort()));
  const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss();});
  await page.goto(pathToFileURL(path.resolve(html)).href,{waitUntil:'networkidle',timeout:30000});
  const elements=await page.evaluate(els=>els.map(e=>{
   const nodes=[...document.querySelectorAll('[id]')].filter(n=>n.id===e.id),n=nodes[0],r=n?.getBoundingClientRect();
   return {id:e.id,text:e.text,type:e.type,parent_id:e.parent_id,count:nodes.length,tag:n?.tagName,dom_parent:n?.getAttribute('data-parent-id'),rect:r?{x:r.x,y:r.y,width:r.width,height:r.height}:null};
  }),state.elements);
  const relations=[];
  for(const label of ['现在','预约','菜单','主界面','返回']){
   const child=elements.find(e=>e.text===label),parent=elements.find(e=>['现在','预约'].includes(label)?e.type==='card':['nav_bar','navigation_bar','navigation'].includes(e.type));
   const c=child?.rect,p=parent?.rect;
   relations.push({label,child:child?.id,parent:parent?.id,declared:!!parent&&child?.parent_id===parent.id,inside:!!c&&!!p&&c.x>=p.x-1&&c.y>=p.y-1&&c.x+c.width<=p.x+p.width+1&&c.y+c.height<=p.y+p.height+1});
  }
  const inputs=[];
  const controls=page.locator('input:not([type=hidden]),textarea,[contenteditable=true]');
  for(let i=0;i<await controls.count();i++){
   const n=controls.nth(i),item={id:await n.getAttribute('id')};
   try{await n.fill('mavis-input-check',{timeout:1500});item.fill=await n.evaluate(e=>(e.value??e.textContent)==='mavis-input-check');}catch(e){item.fill=false;item.error=e.message.split('\n')[0];}inputs.push(item);
  }
  const clicks=[];
  for(const label of ['现在','预约','菜单','主界面','返回']){
   const e=elements.find(e=>e.text===label);if(!e)continue;
   const start=dialogs.length;try{await page.locator('[id="'+e.id+'"]').click({timeout:1500});clicks.push({label,clicked:true,dialogs:dialogs.slice(start)});}catch(error){clicks.push({label,clicked:false,error:error.message.split('\n')[0]});}
  }
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,arm+'.png')});
  const vp=state.page_meta.viewport;
  reports.push({arm,elements,relations,inputs,clicks,errors,blocked,html_sha256:before,html_unchanged:sha(html)===before,out_of_bounds:elements.filter(e=>e.rect&&(e.rect.x<-.5||e.rect.y<-.5||e.rect.x+e.rect.width>vp.width+.5||e.rect.y+e.rect.height>vp.height+.5)).map(e=>e.id)});
  await ctx.close();
 }
 fs.writeFileSync(path.join(out,'audit.json'),JSON.stringify({browser:browser.version(),condition:(networkMode==='online'?'external resources allowed':'external resources blocked')+'; raw HTML unmodified',reports},null,2));
 console.log(JSON.stringify(reports.map(r=>({arm:r.arm,relations:r.relations,inputs:r.inputs,clicks:r.clicks,out_of_bounds:r.out_of_bounds,errors:r.errors,html_unchanged:r.html_unchanged})),null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
