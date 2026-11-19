'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');

function codeLine(prefix) {
  const found = html.split('\n').find(line => line.startsWith(prefix));
  assert.ok(found, 'Missing application code: ' + prefix);
  return found;
}

const funcs = new Function([
  codeLine('function calc(inv)'),
  codeLine('const paidOf='),
  codeLine('const balance='),
  codeLine('const myrSen='),
  codeLine('const fxMissing='),
  'return {calc, paidOf, balance, myrSen, fxMissing};'
].join('\n'))();

const sample = {
  currency: 'MYR',
  items: [{ qty: 2, price: 1050, discount: 100, taxRate: 6, taxType: '01' }],
  payments: [{ amount: 1200 }]
};
assert.equal(funcs.calc(sample).total, 2120);
assert.equal(funcs.calc(sample).tax, 120);
assert.equal(funcs.paidOf(sample), 1200);
assert.equal(funcs.balance(sample), 920);
assert.equal(funcs.myrSen(1000, {currency:'USD', fxRate:'4.65'}), 4650);
assert.equal(funcs.myrSen(1000, {currency:'MYR'}), 1000);
assert.equal(funcs.myrSen(1000, {currency:'USD'}), 0);
assert.equal(funcs.fxMissing([{currency:'USD', fxRate:''}]), true);
assert.equal(funcs.fxMissing([{currency:'USD', fxRate:'4.65'}, {currency:'MYR'}]), false);


const permissions = new Function(
  'CO','ROLE_PERMS','role',
  codeLine('const can=') + '\nreturn can;'
);
let suspended = false;
const can = permissions(
  () => ({status:suspended?'suspended':'active'}),
  {'Owner':['View','Create','Edit Draft','Download','Export','Access Billing']},
  () => 'Owner'
);
assert.equal(can('Create'), true);
suspended = true;
assert.equal(can('Create'), false, 'Suspended company must be read-only');
assert.equal(can('View'), true, 'Suspended company remains readable');
assert.equal(can('Download'), true, 'Permitted downloads remain available');

const inputs = {'py-a':'12.50','py-d':'2026-11-19','py-m':'Bank transfer','py-r':'SAMPLE-1'};
const toasts = [];
const inv = {id:'invoice1',currency:'MYR',lhdn:{status:'Not Submitted'},payments:[]};
let saved = 0;
const ctx = vm.createContext({
  CO: () => ({invoices:[inv]}),
  can: () => true,
  val: name => inputs[name] || '',
  toSen: input => Math.round(Number(input) * 100),
  balance: () => 5000,
  money: amount => 'RM '+(amount/100).toFixed(2),
  todayStr: () => '2026-11-19',
  toast: (msg,type) => {toasts.push({msg,type})},
  uuid: () => 'pay-id',
  DB: {session:'test@example.invalid'},
  tl: () => {},
  audit: () => {},
  save: () => {saved++},
  CLOUD: false,
  closeModal: () => {},
  rerender: () => {},
  clearTimeout: () => {},
  cloudPush: async () => true,
  PUSH_T: null
});
vm.runInContext(codeLine('let PAYMENT_SAVING=false;')+'\n'+codeLine('async function savePay(id)')+'\nthis.savePay=savePay;',ctx);
(async () => {
  inputs['py-a'] = 'abc';
  await ctx.savePay('invoice1');
  assert.equal(inv.payments.length, 0, 'Invalid payment rejected');
  inputs['py-a'] = '12.555';
  await ctx.savePay('invoice1');
  assert.equal(inv.payments.length, 0, 'Overprecision payment rejected');
  inputs['py-a'] = '51.00';
  await ctx.savePay('invoice1');
  assert.equal(inv.payments.length, 0, 'Overpayment rejected');
  inputs['py-a'] = '12.50';
  inputs['py-d'] = '2026-11-20';
  await ctx.savePay('invoice1');
  assert.equal(inv.payments.length, 0, 'Future payment date rejected');
  inputs['py-d'] = '2026-11-19';
  await ctx.savePay('invoice1');
  assert.equal(inv.payments.length, 1, 'Valid payment recorded');
  assert.equal(inv.payments[0].amount, 1250);
  assert.equal(saved, 1);
  assert.ok(toasts.some(t => /saved/i.test(t.msg)), 'Save confirmation displayed');
  console.log('PASS: financial conversions, totals and payment safeguards');
})().catch(err => { console.error(err); process.exitCode = 1; });
