/* Appearance-only test of the shipped script with explicit storage/DOM contracts. */
'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../src/ui/theme.js'),'utf8');
function app(opts={}) {
 const values={};if(opts.saved!==undefined)values['sadleracme.theme']=opts.saved;
 const events={},attrs={},meta={},buttonAttrs={},listeners={},label={textContent:''};let writes=0,requests=0,domReady;
 const root={setAttribute:(k,v)=>{attrs[k]=v;},getAttribute:k=>attrs[k]};
 const button={setAttribute:(k,v)=>{buttonAttrs[k]=v;},querySelector:()=>label,addEventListener:(k,fn)=>{listeners[k]=fn;}};
 const window={addEventListener:(k,fn)=>{events[k]=fn;},fetch:()=>{requests++;throw Error('theme performed network request');}};
 Object.defineProperty(window,'localStorage',{get(){if(opts.blockAll)throw Error('storage denied');return {getItem(k){if(opts.blockRead)throw Error('read denied');return values[k]??null;},setItem(k,v){if(opts.blockWrite)throw Error('write denied');writes++;values[k]=v;}};}});
 const doc={documentElement:root,readyState:opts.loading?'loading':'complete',querySelector:()=>({setAttribute:(k,v)=>{meta[k]=v;}}),getElementById:()=>opts.noButton?null:button,addEventListener:(k,fn)=>{if(k==='DOMContentLoaded')domReady=fn;}};
 vm.runInNewContext(source,{window,document:doc});
 return {values,attrs,meta,buttonAttrs,label,events,click:()=>listeners.click(),ready:()=>domReady(),get writes(){return writes;},get requests(){return requests;}};
}
const tests=[];const test=(n,f)=>tests.push([n,f]);
test('Dark is default without saved preference',()=>{const a=app();assert.equal(a.attrs['data-theme'],'dark');assert.equal(a.writes,0);});
test('Saved light applied immediately',()=>{const a=app({saved:'light',loading:true});assert.equal(a.attrs['data-theme'],'light');assert.equal(a.meta.content,'light');assert.equal(a.writes,0);a.ready();assert.equal(a.label.textContent,'Dark mode');});
test('Invalid saved values select dark',()=>{for(const v of ['LIGHT','system','<script>',null,{},0])assert.equal(app({saved:v}).attrs['data-theme'],'dark');});
test('Click updates palette, accessible target label and storage',()=>{const a=app();a.click();assert.equal(a.attrs['data-theme'],'light');assert.equal(a.values['sadleracme.theme'],'light');assert.equal(a.buttonAttrs['aria-label'],'Switch to dark mode');assert.equal(a.meta.content,'light');assert.equal(a.writes,1);});
test('Second click restores dark',()=>{const a=app();a.click();a.click();assert.equal(a.attrs['data-theme'],'dark');assert.equal(a.label.textContent,'Light mode');assert.equal(a.writes,2);});
test('Blocked storage still allows in-page switching',()=>{const a=app({blockAll:true});a.click();assert.equal(a.attrs['data-theme'],'light');assert.equal(a.writes,0);});
test('Blocked preference read falls back safely',()=>{const a=app({blockRead:true,saved:'light'});assert.equal(a.attrs['data-theme'],'dark');a.click();assert.equal(a.attrs['data-theme'],'light');});
test('Failed preference write does not undo visual change',()=>{const a=app({blockWrite:true});a.click();assert.equal(a.attrs['data-theme'],'light');assert.equal(a.writes,0);});
test('Other page preference event applies without echo write',()=>{const a=app();a.events.storage({key:'sadleracme.theme',newValue:'light'});assert.equal(a.attrs['data-theme'],'light');assert.equal(a.writes,0);});
test('Unrelated storage event ignored',()=>{const a=app();a.events.storage({key:'unrelated',newValue:'light'});assert.equal(a.attrs['data-theme'],'dark');});
test('Cleared storage restores default dark',()=>{const a=app({saved:'light'});a.events.storage({key:null,newValue:null});assert.equal(a.attrs['data-theme'],'dark');});
test('Missing button does not prevent palette initialization',()=>{assert.equal(app({noButton:true,saved:'light'}).attrs['data-theme'],'light');});
test('Theme does not request network or use certificate settings',()=>{const a=app();a.click();a.events.storage({key:'sadleracme.theme',newValue:'dark'});assert.equal(a.requests,0);assert.deepEqual(Object.keys(a.values),['sadleracme.theme']);assert(!source.includes('csrf')&&!source.includes('cf_token'));});
let failures=0;for(const [n,f] of tests){try{f();console.log('PASS '+n);}catch(e){failures++;console.error('FAIL '+n+'\n'+e.stack);}}
console.log(`${tests.length-failures}/${tests.length} theme tests passed.`);process.exitCode=failures?1:0;
