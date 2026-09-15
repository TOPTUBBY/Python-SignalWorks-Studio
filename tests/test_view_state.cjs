// Dependency-free checks for the production embedded JavaScript view functions.
// Run: node tests/test_view_state.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../SignalWorks_Studio_webserv_v4_4_5.py'),'utf8');
const start=source.indexOf('function plotViewStorageKey(');
const end=source.indexOf('function scheduleAnalysisUpdate()',start);
assert(start>0 && end>start);
const storage=new Map();
const plot={layout:{xaxis:{range:[10,20],autorange:false},yaxis:{range:[1,4],autorange:false},
 yaxis2:{range:[300,450],autorange:false},dragmode:'pan'},data:[{name:'Temp'},{name:'Voltage',visible:'legendonly'}]};
const calls=[];
const context={DATASET_TOKEN:'data1',TAB_VIEW_TOKENS:['v1','v2'],ACTIVE_TAB:0,
 interactiveViewReady:true,plotDivEl:()=>plot,
 sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
 Plotly:{relayout:async(p,v)=>calls.push(['layout',v]),restyle:async(p,v)=>calls.push(['style',v])}};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
(async()=>{
 context.savePlotViewState();
 const saved=JSON.parse(JSON.stringify(context.readStoredPlotView(0)));
 assert.deepEqual(saved.xaxis_range,[10,20]);assert.equal(saved.dragmode,'pan');
 assert.deepEqual(saved.visible_signals,{Temp:true,Voltage:false});
 assert.equal(context.readStoredPlotView(1),null);
 await context.restorePlotViewState(plot,0);
 assert.deepEqual(JSON.parse(JSON.stringify(calls[0][1]['yaxis2.range'])),[300,450]);
 assert.deepEqual(JSON.parse(JSON.stringify(calls[1][1].visible)),[true,'legendonly']);
 // Saving while a new plot is still loading must not overwrite a restored view.
 context.interactiveViewReady=false;plot.layout.xaxis.range=[100,200];context.savePlotViewState();
 assert.deepEqual(JSON.parse(JSON.stringify(context.readStoredPlotView(0).xaxis_range)),[10,20]);
 context.interactiveViewReady=true;
 // Autoscale still captures the resolved visible extent for consistent static exports.
 plot.layout.xaxis.autorange=true;context.savePlotViewState();
 assert.deepEqual(JSON.parse(JSON.stringify(context.readStoredPlotView(0).xaxis_range)),[100,200]);
 const link={};context.setStaticPlotHref(link);
 const view=JSON.parse(new URL(link.href,'http://localhost').searchParams.get('view'));
 assert.deepEqual(view.xaxis_range,[100,200]);assert.equal(view.visible_signals.Voltage,false);
 context.TAB_VIEW_TOKENS[0]='changed-axis';assert.equal(context.readStoredPlotView(0),null);
 context.TAB_VIEW_TOKENS[0]='v1';context.DATASET_TOKEN='data2';assert.equal(context.readStoredPlotView(0),null);
 console.log('PASS: save/restore, tab and dataset isolation, range changes, hidden traces, loading guard, autoscale and Static PNG URL');
})().catch(e=>{console.error(e);process.exitCode=1;});
