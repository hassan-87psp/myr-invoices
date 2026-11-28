// Offline browser-account route regression; no network or account credentials.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const build=fs.readFileSync(new URL('./backend/build_native_auth_candidate.py',import.meta.url),'utf8');
let adapter=build.match(/ADAPTER=r"""([\s\S]*?)"""/)[1];
const manifest=JSON.parse(fs.readFileSync(new URL('./approved-frontend-releases.json',import.meta.url),'utf8'));
const release=manifest.releases.find(r=>r.id==='account-link-scope-v1');
assert.ok(release);
for(const pair of release.replacements){
 assert.equal(adapter.split(pair.old).length,2);
 adapter=adapter.replace(pair.old,()=>pair.new);
}
const events={};
const location={hash:''};
const context=vm.createContext({
 location,URLSearchParams,window:{addEventListener:(name,fn)=>{events[name]=fn}},
 history:{replaceState:(_a,_b,hash)=>{location.hash=hash}},
 document:{title:''},LOGO:()=>'',field:()=>'',vAuth:()=>'',fetch:()=>{throw new Error('Network forbidden')}
});
vm.runInContext(adapter,context);
const token='a'.repeat(43), reset='b'.repeat(43);
const view=(action,hash)=>{location.hash=hash;vm.runInContext('myrFinishView('+JSON.stringify(action)+')',context)};
const state=()=>JSON.parse(vm.runInContext('JSON.stringify([MYR_FINISH_TOKEN,MYR_FINISH_ACTION])',context));
view('verify-email','#/auth/verify-email?token='+token);
assert.deepEqual(state(),[token,'verify-email']);
assert.equal(location.hash,'#/auth/verify-email');
view('verify-email',location.hash);
assert.deepEqual(state(),[token,'verify-email']);
view('reset-password','#/auth/reset-password');
assert.deepEqual(state(),['','']);
view('reset-password','#/auth/reset-password?token='+reset);
assert.deepEqual(state(),[reset,'reset-password']);
view('reset-password','#/auth/reset-password?token=invalid');
assert.deepEqual(state(),['','']);
view('verify-email','#/auth/verify-email?token='+token);
location.hash='#/login';events.hashchange();
assert.deepEqual(state(),['','']);
console.log('MYR_ACCOUNT_LINK_SCOPE_OFFLINE_OK');
