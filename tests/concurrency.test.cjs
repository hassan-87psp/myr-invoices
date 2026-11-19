'use strict';
const assert=require('node:assert/strict');
const {mergeCompany,eq}=require('../concurrency.js');
const make = () => ({
  name:'Fictional Demo Co',
  nextNo:1001,
  invoices:[{id:'a',number:'INV-1000',notes:'baseline',payments:[],items:[]}],
  customers:[{id:'c',name:'Buyer'}],
  products:[]
});
const base=make();
const local=make(),remote=make();
local.invoices.push({id:'b',number:'INV-1001',items:[],payments:[]});
remote.customers[0].name='Updated buyer';
const result=mergeCompany(base,local,remote);
assert.equal(result.ok,true,'Independent invoice and customer changes should merge');
assert.equal(result.data.invoices.length,2);
assert.equal(result.data.customers[0].name,'Updated buyer');
assert.equal(result.data.nextNo,1001);

const concurrentA=make(),concurrentB=make();
concurrentA.invoices[0].notes='from device A';
concurrentB.invoices[0].notes='from device B';
const conflict=mergeCompany(base,concurrentA,concurrentB);
assert.equal(conflict.ok,false,'Simultaneous edits of the same invoice must be rejected');
assert.ok(conflict.conflicts.some(x=>x.includes('invoices / a')));

const dupA=make(),dupB=make();
dupA.invoices.push({id:'c1',number:'INV-1001'});
dupB.invoices.push({id:'c2',number:'inv-1001'});
assert.equal(mergeCompany(base,dupA,dupB).ok,false,'Simultaneous number collision must be rejected');

const settingA=make(),settingB=make();
settingA.name='Owner changed name';settingB.name='Other editor changed name';
assert.equal(mergeCompany(base,settingA,settingB).ok,false,'Settings collisions must be rejected');

const paymentA=make(),paymentB=make();
paymentA.invoices[0].payments.push({id:'p1',amount:1250});
paymentB.invoices.push({id:'new',number:'INV-1002'});
const paymentMerge=mergeCompany(base,paymentA,paymentB);
assert.equal(paymentMerge.ok,true,'Different invoice IDs can merge without dropping payments');
assert.equal(paymentMerge.data.invoices[0].payments[0].amount,1250);
assert.equal(paymentMerge.data.invoices.length,2);

assert.ok(eq({x:1,y:2},{y:2,x:1}),'Key ordering must not cause false conflicts');
console.log('PASS: concurrent record merges, same-record conflicts, duplicate numbers and payment preservation');
