// Run after installing Playwright + Chromium: node tests/test_browser.cjs
// Uses only synthetic logger data and a temporary local server.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..');
const output = path.join(__dirname,'browser-artifacts');
fs.mkdirSync(output,{recursive:true});
const server = spawn(process.env.PYTHON || 'python', ['-m','uvicorn','SignalWorks_Studio_webserv_v4_4_5:app','--host','127.0.0.1','--port','8800'],{cwd:root,stdio:['ignore','ignore','pipe']});
let serverErrors='';server.stderr.on('data',b=>{serverErrors+=b;});
let browser;
(async()=>{
 for(let i=0;i<80;i++){
  try {if((await fetch('http://127.0.0.1:8800/api/health')).ok)break;}catch{}
  if(i===79)throw new Error('Server did not start: '+serverErrors);
  await new Promise(r=>setTimeout(r,250));
 }
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1740,height:1100}});
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const names=Array.from({length:16},(_,i)=>`L${i+1}_Urms[extremely_long_signal_name_for_readability_test]`);
 const csv='Timestamp,'+names.join(',')+'\n'+Array.from({length:120},(_,r)=>
  '02.09.2026 00:'+String(Math.floor(r/60)).padStart(2,'0')+':'+String(r%60).padStart(2,'0')+','+
  names.map((_,i)=>Math.sin(r/10)*5+i*20).join(',')).join('\n');
 await context.request.post('http://127.0.0.1:8800/upload',{multipart:{file:{name:'regression.csv',mimeType:'text/csv',buffer:Buffer.from(csv)}}});
 const form={};names.forEach((_,i)=>{form[`selected_${i}`]='on';form[`axis_${i}`]=i<8?'left':'right';});
 await context.request.post('http://127.0.0.1:8800/update/0',{form});
 async function open(tab=0){
  await page.goto('http://127.0.0.1:8800/?tab='+tab);
  await page.waitForFunction(()=>typeof interactiveViewReady!=='undefined' && interactiveViewReady);
 }
 await open();
 await page.screenshot({path:path.join(output,'initial-layout.png'),fullPage:true});
 assert.equal(await page.locator('.legend .legendtitletext').textContent(),'PRIMARY');
 assert.equal(await page.locator('.legend2 .legend2titletext').textContent(),'SECONDARY');
 const geometry=await page.evaluate(()=>{
  const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom};};
  return {legends:['.legend','.legend2'].map(selector=>({box:box(document.querySelector(selector)),
   rows:[...new Set([...document.querySelectorAll(selector+' .traces')].map(e=>Math.round(e.getBoundingClientRect().y)))],
   texts:[...document.querySelectorAll(selector+' .legendtext')].map(e=>e.textContent)})),
   plot:box(document.getElementById('interactivePlot'))};
 });
 assert(geometry.legends[0].box.bottom < geometry.legends[1].box.y,'Legends overlap');
 for(const legend of geometry.legends){assert(legend.rows.length<=3, 'More than 3 legend rows');assert(legend.box.bottom<=geometry.plot.bottom,'Legend clipped');}
 assert.deepEqual(geometry.legends[0].texts,names.slice(0,8));
 assert.deepEqual(geometry.legends[1].texts,names.slice(8));
 async function checkSignalLayout(){
  const rows=await page.locator('[data-signal-row]').evaluateAll(es=>es.map(e=>{
   const name=e.querySelector('.signal-check').getBoundingClientRect();const axis=e.querySelector('.axis-select').getBoundingClientRect();
   const row=e.getBoundingClientRect();const text=e.querySelector('.signal-name');
   return {nameWidth:name.width,rowWidth:row.width,nameBottom:name.bottom,axisY:axis.y,clipped:text.scrollWidth>text.clientWidth+1};
  }));
  rows.forEach(r=>{assert(r.nameWidth>r.rowWidth*.85);assert(r.axisY>=r.nameBottom);assert(!r.clipped);});
 }
 await checkSignalLayout();
 await page.screenshot({path:path.join(output,'desktop-light.png'),fullPage:true});
 await page.evaluate(()=>setThemeMode('dark'));
 await page.screenshot({path:path.join(output,'desktop-dark.png'),fullPage:true});
 await page.setViewportSize({width:1100,height:1000});
 await checkSignalLayout();
 await page.screenshot({path:path.join(output,'compact-dark.png'),fullPage:true});
 // Two legend containers must still use the same per-trace view persistence.
 await page.evaluate(async()=>{
  const p=document.getElementById('interactivePlot');
  await Plotly.relayout(p,{'yaxis.range':[10,80],'yaxis.autorange':false,dragmode:'pan'});
  await Plotly.restyle(p,{visible:'legendonly'},[8]);
 });
 await open(1);await open(0);
 const restored=await page.evaluate(()=>{const p=document.getElementById('interactivePlot');return {range:p.layout.yaxis.range,mode:p.layout.dragmode,visible:p.data[8].visible};});
 assert.deepEqual(restored,{range:[10,80],mode:'pan',visible:'legendonly'});
 // A Secondary-only page must display its heading even with a single signal.
 await context.request.post('http://127.0.0.1:8800/update/1',{form:{selected_8:'on',axis_8:'right'}});
 await open(1);
 assert.equal(await page.locator('.legend2 .legend2titletext').textContent(),'SECONDARY');
 assert.equal(await page.locator('.legend2 .legendtext').textContent(),names[8]);
 assert.deepEqual(errors,[]);
 console.log('PASS: browser legend routing/rows/geometry, full signal names, responsive controls, theme, zoom/visibility restoration and Secondary-only page');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.kill();});
