// Offline regression for the actual queued mobile viewport geometry.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const manifest=JSON.parse(fs.readFileSync(new URL('./approved-frontend-releases.json',import.meta.url),'utf8'));
const release=manifest.releases.find(r=>r.id==='mobile-keyboard-suggestions-v1');
assert.ok(release);
const patch=release.replacements.find(p=>p.new.includes('function myrMobileSuggestionGeometry('));
assert.ok(patch);
const start=patch.new.indexOf('function myrMobileSuggestionGeometry(');
const end=patch.new.indexOf('function myrPositionMobileSuggestions(',start);
assert.ok(end>start);
const context=vm.createContext({});
vm.runInContext(patch.new.slice(start,end),context);
const geometry=(rect,viewport)=>context.myrMobileSuggestionGeometry(rect,viewport);
const viewport={left:0,top:0,width:390,height:500};
const rect=(left,top,width,height)=>({left,top,width,height,bottom:top+height});
let g=geometry(rect(16,50,180,40),viewport);
assert.equal(g.top,94);assert.equal(g.height,240);assert.equal(g.width,250);
g=geometry(rect(310,420,60,40),viewport);
assert.equal(g.top,176);assert.equal(g.height,240);assert.equal(g.left,132);
g=geometry(rect(20,90,320,40),{left:10,top:25,width:280,height:230});
assert.equal(g.width,264);assert.equal(g.left,18);assert.equal(g.top,134);
g=geometry(rect(10,15,100,20),{left:0,top:0,width:35,height:40});
assert.ok(g.width<44&&g.height<44); // caller hides unusably small suggestions
for(const v of [viewport,{left:12,top:40,width:320,height:240},{left:0,top:0,width:280,height:160}]){
 for(let x=0;x<v.width;x+=37){for(let y=0;y<v.height;y+=29){
  g=geometry(rect(v.left+x,v.top+y,100,32),v);
  if(g.height<44||g.width<44)continue;
  assert.ok(g.left>=v.left+8&&g.left+g.width<=v.left+v.width-8);
  assert.ok(g.top>=v.top+8&&g.top+g.height<=v.top+v.height-8);
  assert.ok(g.height<=240);
 } }
}
console.log('MYR_MOBILE_SUGGESTIONS_OFFLINE_OK');
