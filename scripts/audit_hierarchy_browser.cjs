/* Read-only evaluation of freshly generated files. No HTML repair. */
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {pathToFileURL}=require('url');
const {chromium}=require(process.env.MAVIS_PLAYWRIGHT_MODULE || 'playwright');
const [root,out,executablePath,networkMode,profile='ride008']=process.argv.slice(2);
if(!['ride008','chat002'].includes(profile))throw Error('Unknown audit profile');
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
   const nodes=[...document.querySelectorAll('[id]')].filter(n=>n.id===e.id),n=nodes[0],r=n?.getBoundingClientRect(),css=n?getComputedStyle(n):null;
   return {id:e.id,text:e.text,action:e.rpa_action,type:e.type,parent_id:e.parent_id,count:nodes.length,tag:n?.tagName,dom_parent:n?.getAttribute('data-parent-id'),actual_parent:n?.parentElement?.id,appearance:css?{background:css.backgroundColor,border:css.borderTopWidth,border_style:css.borderTopStyle,color:css.color}:null,rect:r?{x:r.x,y:r.y,width:r.width,height:r.height}:null};
  }),state.elements);
  const relations=[];
  for(const label of (profile==='ride008'?['现在','预约','菜单','主界面','返回']:[])){
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
  const tasks=profile==='ride008'?['现在','预约','菜单','主界面','返回'].map(label=>({label,match:e=>e.text===label})):[
   ['返回',/返回|back/i],['搜索',/搜索|search/i],['历史入口',/历史|history|open_chat|对话[一二三\d]/i],
   ['个人资料入口',/我的|个人|资料|profile/i],['附件入口',/加号|附件|上传|attach|\+/i],
   ['语音入口',/麦克风|语音|microphone|voice|🎤/i],['发送入口',/发送|send|回车/i]
  ].map(([label,pattern])=>({label,match:e=>pattern.test((e.text||'')+' '+(e.action||''))}));
  for(const task of tasks){
   const candidates=elements.filter(task.match),e=candidates[0],label=task.label;
   if(!e){clicks.push({label,clicked:false,missing:true,candidates:[]});continue;}
   const start=dialogs.length,extra={selected_id:e.id,candidates:candidates.map(e=>e.id),ambiguous:candidates.length>1};
   try{await page.locator('[id="'+e.id+'"]').click({timeout:1500});clicks.push({label,...extra,clicked:true,dialogs:dialogs.slice(start),related_dialog:dialogs.slice(start).some(d=>d.includes(e.text||label))});}catch(error){clicks.push({label,...extra,clicked:false,error:error.message.split('\n')[0]});}
  }
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,arm+'.png')});
  const vp=state.page_meta.viewport;
  reports.push({arm,profile,viewport:vp,pc_canvas_matches:profile==='chat002'?vp.width===1440&&vp.height===900:null,
   matching_limits:'Chat candidate matching is a diagnostic aid, ambiguous or absent targets require evidence review; not the frozen ER/TR/SR/AS scoring.',
   elements,relations,inputs,clicks,errors,blocked,html_sha256:before,html_unchanged:sha(html)===before,out_of_bounds:elements.filter(e=>e.rect&&(e.rect.x<-.5||e.rect.y<-.5||e.rect.x+e.rect.width>vp.width+.5||e.rect.y+e.rect.height>vp.height+.5)).map(e=>e.id)});
  await ctx.close();
 }
 fs.writeFileSync(path.join(out,'audit.json'),JSON.stringify({browser:browser.version(),condition:(networkMode==='online'?'external resources allowed':'external resources blocked')+'; raw HTML unmodified',reports},null,2));
 console.log(JSON.stringify(reports.map(r=>({arm:r.arm,relations:r.relations,inputs:r.inputs,clicks:r.clicks,out_of_bounds:r.out_of_bounds,errors:r.errors,html_unchanged:r.html_unchanged})),null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
