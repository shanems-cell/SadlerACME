/* Execute the real launcher against an AppWindow-constructor fixture.
 * Tests what is passed to DSM, not an assertion about native DSM rendering.
 * Optional baseline path: SADLER_LAUNCHER_SOURCE=/path/to/old/SadlerACME.js.
 */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.env.SADLER_LAUNCHER_SOURCE || path.join(__dirname, '../src/ui/SadlerACME.js'), 'utf8');
function launch(config, viewport = {}, doc = {}) {
  let definitions = {}, captured, listener, removed;
  const desktop = {location:{origin:'https://fixture.invalid'}, ...viewport,
    addEventListener:(kind,fn)=>{listener=fn;},removeEventListener:(kind,fn)=>{removed=fn;}};
  const context = {window:desktop,document:{documentElement:doc,getElementById:()=>null},
    SYNO:{SDS:{Session:{SynoToken:'FIXTURE-TOKEN'}}},
    Ext:{ns:()=>{},define:(name,value)=>definitions[name]=value,id:()=> 'test-frame',
      apply:(a,b)=>Object.assign(a,b),urlAppend:x=>x}};
  vm.createContext(context);vm.runInContext(source,context);
  const spec=definitions['SYNO.SDS.SadlerACME.MainWindow'];
  const self={callParent:(args)=>{captured=args[0];},sendWebAPI:()=>{throw Error('Constructor sent an API request');}};
  spec.constructor.call(self,config);
  return {config:captured,spec,self,listener,get removed(){return removed;}};
}
const tests=[];function test(name,fn){tests.push([name,fn]);}
test('Fresh full-size desktop passes explicit preferred dimensions',()=>{
 const f=launch({}, {innerWidth:1920,innerHeight:1080});
 assert.equal(f.config.width,1320);assert.equal(f.config.height,820);
 assert.equal(f.config.minWidth,900);assert.equal(f.config.minHeight,620);
});
test('Missing incoming config and missing viewport have usable defaults',()=>{
 const f=launch();assert.equal(f.config.width,1320);assert.equal(f.config.height,820);
});
test('Constructor does not rely on prototype geometry',()=>{
 const f=launch({});assert.equal(Object.hasOwn(f.config,'width'),true);assert.equal(Object.hasOwn(f.config,'height'),true);
});
test('Laptop viewport caps the default size',()=>{
 const c=launch({}, {innerWidth:1366,innerHeight:768}).config;
 assert.equal(c.width,1320);assert.equal(c.height,704);
});
test('Small screen caps minimum dimensions as well',()=>{
 const c=launch({}, {innerWidth:800,innerHeight:600}).config;
 assert.equal(c.width,768);assert.equal(c.height,536);assert.equal(c.minWidth,768);assert.equal(c.minHeight,536);
});
test('Narrow viewport never acquires an off-screen desktop minimum',()=>{
 const c=launch({}, {innerWidth:390,innerHeight:844}).config;
 assert.equal(c.width,358);assert.equal(c.minWidth,358);assert(c.height<=780);
});
test('Document client dimensions are the viewport fallback',()=>{
 const c=launch({}, {}, {clientWidth:1024,clientHeight:768}).config;
 assert.equal(c.width,992);assert.equal(c.height,704);
});
test('Invalid viewport values fall back without NaN geometry',()=>{
 const c=launch({}, {innerWidth:NaN,innerHeight:Infinity}).config;
 assert.equal(c.width,1320);assert.equal(c.height,820);
});
test('Usable incoming dimensions and DSM app metadata survive',()=>{
 const instance={fixture:true};const c=launch({width:1100,height:700,appInstance:instance,x:55,y:60,maximized:true}, {innerWidth:1920,innerHeight:1080}).config;
 assert.equal(c.width,1100);assert.equal(c.height,700);assert.equal(c.appInstance,instance);assert.equal(c.x,55);assert.equal(c.y,60);assert.equal(c.maximized,true);
});
test('Tiny incoming dimensions cannot reproduce 250px initial window',()=>{
 const c=launch({width:270,height:250}, {innerWidth:1920,innerHeight:1080}).config;
 assert.equal(c.width,900);assert.equal(c.height,620);
});
test('Oversized supplied geometry fits the current viewport',()=>{
 const c=launch({width:3000,height:2000}, {innerWidth:1366,innerHeight:768}).config;
 assert.equal(c.width,1334);assert.equal(c.height,704);
});
test('Invalid incoming dimensions use preferred defaults',()=>{
 for(const value of [null,undefined,0,-1,NaN,Infinity,'auto','1320']) {
  const c=launch({width:value,height:value}).config;
  assert.equal(c.width,1320);assert.equal(c.height,820);
 }
});
test('Incoming configuration is not mutated',()=>{
 const input={width:270,height:250,appInstance:{fixture:true}};const copy=JSON.stringify(input);
 launch(input);assert.equal(JSON.stringify(input),copy);
});
test('Window chrome capabilities are passed to parent explicitly',()=>{
 const c=launch({}).config;
 assert.equal(c.resizable,true);assert.equal(c.maximizable,true);assert.equal(c.minimizable,true);assert.equal(c.layout,'fit');
});
test('Session token stays on the existing same-origin iframe',()=>{
 const c=launch({}).config;
 assert.equal(c.items[0].autoEl.src,'/webman/3rdparty/sadleracme/index.cgi?SynoToken=FIXTURE-TOKEN');
});
test('Request/open handlers do not force user geometry back',()=>{
 const f=launch({});assert(!/setSize|setWidth|setHeight/.test(f.spec.onOpen.toString()+f.spec.onRequest.toString()));
});
test('Destroy still removes the scheduler message listener',()=>{
 const f=launch({});f.spec.onDestroy.call(f.self);
 assert.equal(f.removed,f.listener);assert.equal(f.self._schedulerBridgeHandler,null);
});
let failed=0;for(const [name,fn] of tests){try{fn();console.log('PASS '+name);}catch(e){failed++;console.error('FAIL '+name+'\n'+e.message);}}
console.log(`${tests.length-failed}/${tests.length} launcher tests passed (fixture, not DSM).`);process.exitCode=failed?1:0;
