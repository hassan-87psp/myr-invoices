// Offline regression exercises the exact queued frontend patch.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const m=JSON.parse(fs.readFileSync(new URL('./approved-frontend-releases.json',import.meta.url),'utf8'));
const r=m.releases.find(x=>x.id==='invoice-sen-rounding-v1');
assert.ok(r);
let html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
for(const p of r.replacements){
 assert.equal(html.split(p.old).length,2);
 html=html.replace(p.old,()=>p.new);
}
const start=html.indexOf('function myrRoundProduct('),end=html.indexOf('const paidOf=',start);
assert.ok(start>=0&&end>start);
const ctx=vm.createContext({});
vm.runInContext(html.slice(start,end),ctx);
const check=(items)=>vm.runInContext('calc('+JSON.stringify({items})+')',ctx);
assert.equal(check([{qty:1.005,price:100}]).total,101);
assert.equal(check([{qty:2.675,price:100}]).total,268);
assert.equal(check([{qty:2,price:1000,discount:100,taxRate:10}]).total,2090);
assert.equal(check([{qty:1,price:5,taxRate:10}]).tax,1);
assert.equal(check([{qty:1,price:100,discount:150,taxRate:10}]).total,0);
assert.equal(check([{qty:1e-7,price:5000000}]).total,1);
assert.equal(check([{qty:1,price:100,taxType:'__proto__'}]).byTax['__proto__'].taxable,100);
assert.equal(check([{qty:0.01,price:50}]).total,1);
console.log('MYR_INVOICE_ROUNDING_OFFLINE_OK');
