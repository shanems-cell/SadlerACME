/* Native geometry contract tests. These are fixtures, NOT a live DSM run.
 * Default: original, handwritten contract model.
 * --dsm-reports V1.json V2.json: execute selected supplied DSM definitions
 * unchanged, with fixture implementations only for unreported DOM/base classes.
 * Reports are intentionally NOT distributed in the GPL source/runtime package.
 */
'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(process.env.SADLER_LAUNCHER_SOURCE || path.join(__dirname,'../src/ui/SadlerACME.js'),'utf8');
let native=null;
if(process.argv[2]==='--dsm-reports'){
 const a=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
 const b=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
 native={...a.AppWindow.functions,...b.AppWindow};
 for(const name of ['constructor','getRestoreSizePos','overwriteAppWinConfig','saveRestoreData','onWindowMove','onHandlerResize','beforeShow','setPosition','setPagePosition'])
  assert.equal(typeof native[name],'string','missing native '+name);
}
const clone=x=>x==null?x:JSON.parse(JSON.stringify(x));
function launch(input={},options={}){
 const viewport={width:1920,height:1080,...options.viewport};
 let stored=options.store || {value:clone(options.saved)},writes=[],defs={},handlers={},current=[0,0],shown=false;
 let captured,passedConfig,baseConfig,rawSets=[],firstShowSets=[],phase='construct',size,extReads=0;
 const off=[options.offsetX||0,options.offsetY||0];
 const document={body:{},documentElement:{},getElementById:()=>null};
 const desktop={innerWidth:viewport.width,innerHeight:viewport.height,location:{origin:'https://fixture.invalid'},addEventListener(){},removeEventListener(){}};
 const settings={getProperty(){return stored.value;},setProperty(app,key,value){assert.equal(key,'restoreSizePos');stored.value=value;writes.push(clone(value));}};
 const Ext={ns(){},define(name,spec){defs[name]=spec;},id:()=> 'frame',urlAppend:x=>x,
  apply(target,src,defaults){if(defaults)Object.assign(target,defaults);return Object.assign(target,src);},
  isDefined:x=>typeof x!=='undefined',isArray:Array.isArray,isObject:x=>x&&typeof x==='object',isNumber:x=>typeof x==='number',
  state:{Manager:{get(){extReads++;return options.extState;}}},
  lib:{Dom:{getViewWidth:()=>viewport.width,getViewHeight:()=>viewport.height}},
  EventManager:{onWindowResize(){},removeResizeListener(){}},getBody:()=>document.body};
 const SYNO={SDS:{Session:{SynoToken:'fixture'},UserSettings:settings,
  TaskBar:{height:()=>40},StatusNotifier:{fireEvent(){}},UIFeatures:{test:()=>false},AppWindow:{superclass:{}}}};
 const context={window:desktop,document,Ext,SYNO,_S:key=>key==='majorversion'?'7':key==='minorversion'?'4':false,_T:()=> 'fixture',console};
 vm.createContext(context);vm.runInContext(source,context);
 const spec=defs['SYNO.SDS.SadlerACME.MainWindow'];
 function baseConstructor(c){
  baseConfig=c;Object.assign(this,c);this.rendered=false;this.boxReady=false;size={width:this.width,height:this.height};
 }
 SYNO.SDS.AppWindow.superclass.constructor=baseConstructor;
 SYNO.SDS.AppWindow.superclass.afterRender=function(){};
 SYNO.SDS.WindowMgr={centerWindow(win){win.setPagePosition((viewport.width-size.width)/2,40+(viewport.height-40-size.height)/2);}};
 const model={
  constructor:function(c){
   c=Ext.apply({},c,{autoCenter:true});
   if(c.appInstance&&(c.autoStart===true||(c.fromRestore!==true&&c.autoRestoreSizePos!==false))) Ext.apply(c,this.getRestoreSizePos(c));
   c=this.overwriteAppWinConfig(c);baseConstructor.call(this,c);
   this.mon(this,'move',this.onWindowMove,this);
  },
  getRestoreSizePos:function(c){
   const s=c.appInstance.getUserSettings('restoreSizePos')||{};
   if(s.width!==undefined&&s.width<c.minWidth)s.width=c.width||c.minWidth;
   if(s.height!==undefined&&s.height<c.minHeight)s.height=c.height||c.minHeight;
   if(s.maximized===undefined)s.maximized=c.defaultMaximized;
   if(c.maximized)s.maximized=c.maximized;
   return s;
  },
  overwriteAppWinConfig:c=>c,
  saveRestoreData:function(){
   const old=this.appInstance.getUserSettings('restoreSizePos');
   const result=Object.assign(this.getSizeAndPosition(),{fromRestore:true,maximized:this.maximized});
   if(old){
    if(this.moveDirty)this.moveDirty=false;else{if(old.pageX)result.pageX=old.pageX;if(old.pageY)result.pageY=old.pageY;}
    if(this.resizeDirty)this.resizeDirty=false;else{if(old.width)result.width=old.width;if(old.height)result.height=old.height;}
   }
   this.appInstance.setUserSettings('restoreSizePos',result);
  },
  onWindowMove:function(){this.moveDirty=true;this.saveRestoreData();},
  onHandlerResize:function(){this.resizeDirty=true;this.saveRestoreData();},
  setPosition:function(x,y){
   this.x=x;this.y=y;if(!this.boxReady)return this;
   this.getPositionEl().setLeftTop(x,y);this.fireEvent('move',this,x,y);return this;
  },
  setPagePosition:function(x,y){
   this.pageX=x;this.pageY=y;if(!this.boxReady)return;
   const p=this.getPositionEl().translatePoints(x,y);this.setPosition(p.left,p.top);return this;
  },
  beforeShow:function(){
   if(this.x===undefined||this.y===undefined){const a=this.el.getAlignToXY(this.container,'c-c'),p=this.el.translatePoints(a[0],a[1]);if(this.x===undefined)this.x=p.left;if(this.y===undefined)this.y=p.top;}
   this.el.setLeftTop(this.x,this.y);
  }
 };
 const self={
  mon(object,event,fn,scope){if(object===this)(handlers[event]||(handlers[event]=[])).push(()=>fn.call(scope));},
  on(event,fn,scope,opts){assert.equal(event,'show');captured=()=>fn.call(scope);this.showOptions=opts;},
  fireEvent(event){(handlers[event]||[]).forEach(f=>f());return true;},
  getSize:()=>({...size}),getSizeAndPosition:()=>({width:size.width,height:size.height,pageX:current[0],pageY:current[1]}),
  getPosition(local){if(options.throwPosition)throw Error('unavailable');return local?[current[0]-off[0],current[1]-off[1]]:(options.cachedPage||current).slice();},
  getPositionEl(){return this.el;},adjustPosition:(x,y)=>({x,y}),onPosition(){},syncShadow(){},getStateId:()=> 'not-native',
  getTitle:()=> 'SadlerACME',isStandaloneMainWindow:()=>!!options.standalone,
  sendWebAPI(){throw Error('Unexpected DSM API request');},
  setSize(w,h){size={width:w,height:h};this.width=w;this.height=h;if(options.moveOnResize)current=options.moveOnResize.slice();},
  callParent(args){passedConfig=args[0];return contract.constructor.call(this,args[0]);}
 };
 const element={
  setLeftTop(x,y){current=[x+off[0],y+off[1]];rawSets.push([phase,...current]);if(phase==='show-handler')firstShowSets.push(current.slice());},
  setLeft(x){current[0]=x+off[0];},setTop(y){current[1]=y+off[1];},
  translatePoints:(x,y)=>({left:x-off[0],top:y-off[1]}),
  getAlignToXY:()=>[(viewport.width-size.width)/2,(viewport.height-size.height)/2],
  getLeft:()=>current[0]-off[0],getTop:()=>current[1]-off[1],getXY:()=>current.slice()
 };
 self.el=element;
 let contract={...model};
 if(native){
  // Evaluate only preselected inspected methods; no network or API primitives.
  for(const name of Object.keys(model))contract[name]=vm.runInContext('('+native[name]+')',context);
 }
 Object.entries(contract).forEach(([name,fn])=>{if(name!=='constructor')self[name]=fn;});
 if(spec.overwriteAppWinConfig){
  const fn=spec.overwriteAppWinConfig;
  self.overwriteAppWinConfig=function(c){const save=this.callParent;this.callParent=args=>contract.overwriteAppWinConfig.call(this,args[0]);try{return fn.call(this,c);}finally{this.callParent=save;}};
 }
 const instance={jsConfig:{jsID:'SYNO.SDS.SadlerACME.Application'},getUserSettings:key=>settings.getProperty(null,key),setUserSettings:(key,v)=>settings.setProperty(null,key,v)};
 spec.constructor.call(self,{appInstance:instance,...input});
 if(options.rect)self.container={dom:{getBoundingClientRect:()=>options.rect}};
 if(options.throwContainer)self.container={dom:{getBoundingClientRect(){throw Error('unavailable');}}};
 if(options.bodyContainer)self.container={dom:document.body};
 function render(){
  phase='render';self.boxReady=true;self.rendered=true;
  if(typeof self.pageX==='number'&&typeof self.pageY==='number')self.setPagePosition(self.pageX,self.pageY);
  else if(typeof self.x==='number'&&typeof self.y==='number')self.setPosition(self.x,self.y);
  else{
   const p=options.renderDefault || [220,10];
   // Unreported base-render behaviour is an explicit fixture. Deliberately
   // persist native initial placement before show, to catch live-store guessing.
   self.setPagePosition(p[0],p[1]);
  }
  if(options.forceNativeInitial)self.setPagePosition(options.forceNativeInitial[0],options.forceNativeInitial[1]);
  if(options.hideNativeCoordinates){delete self.x;delete self.y;}
  contract.beforeShow.call(self);
 }
 function show(){if(!shown){render();shown=true;}phase='show-handler';captured();phase='idle';}
 return{self,show,store:stored,writes,passedConfig,get baseConfig(){return baseConfig;},get position(){return current.slice();},get size(){return {...size};},firstShowSets,rawSets,get extReads(){return extReads;},
  drag(x,y){phase='user-move';self.setPagePosition(x,y);phase='idle';},
  resize(w,h){self.setSize(w,h);contract.onHandlerResize.call(self);},
  close(){contract.saveRestoreData.call(self);},
  showAgain(){phase='show-handler';captured();phase='idle';}
 };
}
const tests=[];const test=(name,fn)=>tests.push([name,fn]);
const restored=(extra={})=>({pageX:75,pageY:95,width:1050,height:700,fromRestore:true,maximized:false,...extra});
test('Fresh opening has no competing seeded local or page coordinates',()=>{const f=launch();for(const k of ['x','y','pageX','pageY'])assert.equal(f.passedConfig[k],undefined,k);});
test('Fresh native render movement is not mistaken for restored geometry',()=>{const f=launch();f.show();assert.deepEqual(f.position,[300,138]);});
test('Native render preference writes do not suppress fresh centring',()=>{const f=launch({}, {renderDefault:[70,80]});f.show();assert.deepEqual(f.position,[300,138]);assert.equal(f.store.value.pageX,300);assert.equal(f.store.value.pageY,138);});
test('Native page-coordinate record is restored without recentering',()=>{const f=launch({}, {saved:restored()});f.show();assert.deepEqual(f.position,[75,95]);assert.deepEqual(f.size,{width:1050,height:700});assert.equal(f.firstShowSets.length,0);});
test('Move resize close reopen preserves native store geometry',()=>{const first=launch();first.show();first.drag(65,85);first.resize(1000,700);first.close();const next=launch({}, {store:first.store});next.show();assert.deepEqual(next.position,[65,85]);assert.deepEqual(next.size,{width:1000,height:700});assert.equal(next.firstShowSets.length,0);});
test('Existing remembered centre is not treated as forced new centring',()=>{const f=launch({}, {saved:restored({pageX:435,pageY:198})});f.show();assert.deepEqual(f.position,[435,198]);assert.equal(f.firstShowSets.length,0);});
test('Window-manager page position in fromRestore config is honoured',()=>{const f=launch({...restored(),pageX:100,pageY:120}, {saved:restored({pageX:400,pageY:200})});f.show();assert.deepEqual(f.position,[100,120]);});
test('autoRestoreSizePos false does not consult stored position',()=>{const f=launch({autoRestoreSizePos:false}, {saved:restored()});f.show();assert.deepEqual(f.position,[300,138]);});
test('autoStart restores native record despite fromRestore',()=>{const f=launch({autoStart:true,fromRestore:true,pageX:200,pageY:220}, {saved:restored()});f.show();assert.deepEqual(f.position,[75,95]);});
test('Native page pair wins over stale caller-local coordinates',()=>{const f=launch({x:300,y:138}, {saved:restored()});f.show();assert.deepEqual(f.position,[75,95]);assert.equal(f.baseConfig.x,undefined);assert.equal(f.baseConfig.y,undefined);});
test('Explicit page pair without stored record is retained',()=>{const f=launch({pageX:60,pageY:80});f.show();assert.deepEqual(f.position,[60,80]);assert.equal(f.firstShowSets.length,0);});
test('Explicit local coordinates without page pair are retained',()=>{const f=launch({x:60,y:80});f.show();assert.deepEqual(f.position,[60,80]);assert.equal(f.firstShowSets.length,0);});
test('Local coordinates translate correctly in an offset desktop',()=>{const f=launch({x:60,y:80},{offsetX:10,offsetY:50});f.show();assert.deepEqual(f.position,[70,130]);assert.equal(f.firstShowSets.length,0);});
test('Native page coordinates do not acquire a container offset',()=>{const f=launch({}, {saved:restored(),offsetX:10,offsetY:50});f.show();assert.deepEqual(f.position,[75,95]);});
test('Missing and size-only preferences still centre',()=>{for(const saved of [undefined,{}, {width:1050,height:700,fromRestore:true}]){const f=launch({}, {saved});f.show();const s=f.size;assert.deepEqual(f.position,[(1920-s.width)/2,40+(1016-s.height)/2]);}});
test('Partial or invalid saved page pairs cannot suppress centring',()=>{for(const saved of [{pageX:75},{pageX:'75',pageY:95},{pageX:75,pageY:null}]){const f=launch({}, {saved});f.show();assert.deepEqual(f.position,[300,138]);}});
test('Invalid caller coordinates are removed without NaN placement',()=>{for(const c of [{x:'20',y:60},{x:NaN,y:60},{x:Infinity,y:60},{pageX:40},{pageX:NaN,pageY:40}]){const f=launch(c);f.show();assert.deepEqual(f.position,[300,138]);}});
test('Zero-valued native page coordinates are recognised then bounded',()=>{const f=launch({}, {saved:restored({pageX:0,pageY:0})});f.show();assert.deepEqual(f.position,[16,40]);});
test('Negative saved page coordinates are bounded not centred',()=>{const f=launch({}, {saved:restored({pageX:-100,pageY:-50})});f.show();assert.deepEqual(f.position,[16,40]);});
test('Offscreen native position is clamped without resetting to centre',()=>{const f=launch({}, {saved:restored({pageX:9000,pageY:9000})});f.show();assert.deepEqual(f.position,[854,356]);});
test('Fresh measured desktop rectangle drives centring',()=>{const f=launch({}, {rect:{left:0,top:60,right:1700,bottom:1000}});f.show();assert.deepEqual(f.position,[190,120]);});
test('Measured small desktop shrinks an oversized restored window',()=>{const f=launch({}, {saved:restored({width:1800,height:1000}),rect:{left:0,top:50,right:1000,bottom:700}});f.show();assert.deepEqual(f.size,{width:984,height:634});assert.deepEqual(f.position,[8,58]);});
test('Resizing callbacks cannot overwrite snapshotted restored target',()=>{const f=launch({}, {saved:restored({pageX:100,pageY:100,width:1800}),rect:{left:0,top:50,right:1700,bottom:1000},moveOnResize:[0,0]});f.show();assert.deepEqual(f.position,[8,100]);});
test('Body and invalid container rectangles use conservative fallback',()=>{for(const o of [{bodyContainer:true},{throwContainer:true},{rect:{left:0,top:0,right:100,bottom:100}}]){const f=launch({},o);f.show();assert.deepEqual(f.position,[300,138]);}});
test('Tiny desktop bounds remain finite and contained',()=>{const f=launch({}, {viewport:{width:390,height:700}});f.show();assert.deepEqual(f.size,{width:358,height:636});assert.deepEqual(f.position,[16,40]);});
test('No second placement after show or subsequent drag',()=>{const f=launch();f.show();f.drag(50,70);f.showAgain();assert.deepEqual(f.position,[50,70]);assert.equal(f.firstShowSets.length,1);});
test('Maximised and minimised windows get no custom placement',()=>{for(const flag of ['maximized','minimized']){const f=launch({[flag]:true});f.show();assert.equal(f.firstShowSets.length,0);}});
test('Saved maximised state is left to native window handling',()=>{const f=launch({}, {saved:restored({maximized:true})});f.show();assert.equal(f.self.maximized,true);assert.equal(f.firstShowSets.length,0);});
test('Standalone main window gets no custom placement',()=>{const f=launch({}, {standalone:true});f.show();assert.equal(f.firstShowSets.length,0);});
test('Unrelated Ext state cannot suppress native fresh centring',()=>{const f=launch({}, {extState:{x:60,y:80}});f.show();assert.deepEqual(f.position,[300,138]);assert.equal(f.extReads,0);});
test('Position getter failure cannot crash a fresh opening',()=>{const f=launch({}, {throwPosition:true});f.show();assert.deepEqual(f.position,[300,138]);});
test('Local-setter fallback translates the desired page point',()=>{const f=launch({}, {offsetX:10,offsetY:50,rect:{left:10,top:50,right:1710,bottom:990}});const nativePage=f.self.setPagePosition;f.self.setPagePosition=undefined;f.self.x=210;f.self.y=-40;f.show();assert.deepEqual(f.position,[200,110]);f.self.setPagePosition=nativePage;});
test('Native snapshot is immutable when live settings are replaced',()=>{const f=launch({}, {saved:restored()});f.store.value={pageX:400,pageY:250,width:1050,height:700};f.show();assert.deepEqual(f.position,[75,95]);assert.deepEqual(Array.from(f.self._sadlerInitialGeometry.page),[75,95]);});
test('Window hook does not mutate caller local/page input object',()=>{const c={x:300,y:138,pageX:75,pageY:95,width:1050,height:700};const before=JSON.stringify(c);const f=launch(c);f.show();assert.equal(JSON.stringify(c),before);assert.deepEqual(f.position,[75,95]);});
test('Native initial repositioning cannot be mistaken for a restored user preference',()=>{const f=launch({}, {forceNativeInitial:[220,80]});f.show();assert.deepEqual(f.position,[300,138]);});
test('A stale page-position getter cannot replace native restored geometry',()=>{const f=launch({}, {saved:restored(),cachedPage:[435,198]});f.show();assert.deepEqual(f.position,[75,95]);assert.equal(f.firstShowSets.length,0);});
test('Saved page point is preserved even if getters throw',()=>{const f=launch({}, {saved:restored(),throwPosition:true});f.show();assert.deepEqual(f.position,[75,95]);assert.equal(f.firstShowSets.length,0);});
test('Saved local-coordinate variant is retained when no page pair exists',()=>{const f=launch({}, {saved:{x:75,y:95,width:1050,height:700,fromRestore:true}});f.show();assert.deepEqual(f.position,[75,95]);assert.equal(f.firstShowSets.length,0);});
let failed=0;for(const [name,fn]of tests){try{fn();console.log('PASS '+name);}catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}
console.log(`${tests.length-failed}/${tests.length} placement cases passed (${native?'selected supplied DSM definitions + simulated DOM/base render':'handwritten native contract model'}; NOT a live DSM run).`);
process.exitCode=failed?1:0;
