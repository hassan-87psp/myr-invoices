'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('index.html', 'utf8');

const begin = code.indexOf('async function bSave(status)');
const end = code.indexOf('function bPreview()', begin);
assert.ok(begin > -1 && end > begin, 'Invoice save handler found');
const saveSource = code.slice(begin,end).trim();

const savedInvoice = {
  id: 'safe-test',
  number: 'INV-1001',
  currency: 'MYR',
  items: [{qty: 1,price: 2000}],
  payments: [{amount: 1500}],
  lhdn: {status: 'Not Submitted',attempts: []},
  appStatus:'Draft'
};
const co = {id:'test-company', prefix:'INV-',nextNo:1002,
  invoices:[savedInvoice], approvalRequired:false};
let ED = JSON.parse(JSON.stringify(savedInvoice));
const messages = [];
let saves=0;
const sandbox = vm.createContext({
  CO: () => co, can: () => true, clone: v=>JSON.parse(JSON.stringify(v)),
  locked: i => ['Submitted','Valid','Cancelled'].includes(i.lhdn.status),
  paidOf: i => i.payments.reduce((a,p)=>a+p.amount,0),
  calc: i => ({total:i.items.reduce((a,v)=>a+v.qty*v.price,0)}),
  toast: (m) => {messages.push(m)}, audit: ()=>{}, tl: ()=>{},
  save:()=>{saves++}, go:()=>{}, clearTimeout:()=>{},
  cloudPush: async()=>true, CLOUD:false, PUSH_T:null, atomicEnabled:()=>false,
  bCheck:()=>({errors:[]}), $:()=>null, ED, DB:{session:'test@example.invalid'},
  uuid:()=> 'uuid-test', confirmBox:()=>{}, INVOICE_SAVING:false
});
vm.runInContext(saveSource+'\nthis.handleSave=bSave;',sandbox);
vm.runInContext('this.handleDelete='+code.split('\n').find(l=>l.startsWith('function delInvoice(id)')).replace(/^function delInvoice/, 'function'),sandbox);

(async()=>{
  savedInvoice.lhdn.status='Submitted';
  await sandbox.handleSave();
  assert.equal(saves,0,'LHDN-submitted invoice may not be edited');
  savedInvoice.lhdn.status='Not Submitted';

  sandbox.ED.items=[{qty:1,price:1000}];
  await sandbox.handleSave();
  assert.equal(saves,0,'Cannot reduce invoice below recorded payments');

  sandbox.ED.items=[{qty:1,price:2200}];
  await sandbox.handleSave();
  assert.equal(saves,1,'Valid invoice edit saved');
  assert.equal(co.invoices[0].items[0].price,2200);

  // Direct deletion calls must not bypass UI guards.
  let confirmed=false;
  sandbox.confirmBox=()=>{confirmed=true};
  await sandbox.handleDelete('safe-test');
  assert.equal(confirmed,false,'Paid invoice cannot be deleted');
  co.invoices[0].payments=[];
  co.invoices[0].lhdn.attempts=[{at:'2026-11-19'}];
  await sandbox.handleDelete('safe-test');
  assert.equal(confirmed,false,'LHDN-attempted invoice cannot be deleted');

  assert.ok(messages.some(m=>m.includes('recorded payments')));
  console.log('PASS: invoice editing, payment preservation, deletion safeguards');
})().catch(e=>{console.error(e);process.exitCode=1});
