'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('index.html','utf8');
function snippet(from,to){
 const a=source.indexOf(from),b=source.indexOf(to,a+from.length);
 assert.ok(a>=0&&b>a,'Missing handler: '+from);
 return source.slice(a,b);
}
const bSaveSource=snippet('async function bSave(status){','function bPreview(){');
const draftFieldsSource=snippet('function myrDraftFields(','function myrDraftRead(');
const paymentSource=snippet('async function savePay(id){','function remind(id){');
const sampleInv={
 id:'i1',number:'INV-1001',_autoNumber:'INV-1001',
 currency:'MYR',appStatus:'Draft',items:[{id:'l1',qty:1,price:1000}],payments:[],
 lhdn:{status:'Not Submitted',attempts:[]}
};
async function testAtomicInvoice(){
 const co={id:'company-test',prefix:'INV-',nextNo:1001,approvalRequired:false,invoices:[]};
 const ed=JSON.parse(JSON.stringify(sampleInv));
 const called=[];let navigation='',saved=false;
 const sandbox=vm.createContext({
  ED:ed,CO:()=>co, MYR_INV_BASE:'',myrDraftClear:()=>{},CLOUD:true,CFG:{atomicRecordWrites:true},
  atomicEnabled:()=>true,atomicReady:async()=>true,
  INVOICE_SAVING:false,UNSYNCED_CLOUD:false,
  can:()=>true,bCheck:()=>({errors:[]}),
  clone:x=>JSON.parse(JSON.stringify(x)),
  locked:()=>false,paidOf:()=>0,calc:()=>({total:1000}),
  tl:()=>{},audit:()=>{},save:()=>{saved=true},
  toast:()=>{},go:x=>{navigation=x},$:()=>null,clearTimeout:()=>{},PUSH_T:null,
  coBody:x=>JSON.parse(JSON.stringify(x)),
  atomicApply:(c,response)=>{c.invoices.push(response.record);return true},
  cloudPush:async()=>true,
  SB:{rpc:async(name,args)=>{
   called.push({name,args});
   if(name==='reserve_invoice_number')return {data:{number:'INV-1007',nextNo:1008},error:null};
   if(name==='atomic_save_record')return {
    data:{record:args.p_record,version:5,company_data:{}},error:null
   };
   throw Error('Unexpected RPC '+name);
  }}
 });
 vm.runInContext(draftFieldsSource+bSaveSource+'\nthis.saveInvoice=bSave;',sandbox);
 await sandbox.saveInvoice();
 assert.equal(called.length,2,'Two-stage atomic numbering and save');
 assert.equal(called[0].name,'reserve_invoice_number');
 assert.equal(called[1].name,'atomic_save_record');
 assert.equal(called[1].args.p_kind,'invoices');
 assert.equal(called[1].args.p_record.number,'INV-1007');
 assert.equal(called[1].args.p_expected,null,'New record should not have edit snapshot');
 assert.equal(called[1].args.p_record._autoNumber,undefined,'Client metadata is stripped');
 assert.equal(co.invoices.length,1,'Server response drives local state');
 assert.equal(saved,false,'No whole company JSON overwrite');
 assert.match(navigation,/\/view\/i1$/);
 assert.equal(JSON.parse(sandbox.MYR_INV_BASE).number,'INV-1007','Draft baseline follows atomic reservation');

 const failed=vm.createContext({
  ED:{...sampleInv},CO:()=>({id:'c1',prefix:'INV-',nextNo:1001,invoices:[],approvalRequired:false}),
  CLOUD:true,UNSYNCED_CLOUD:false,INVOICE_SAVING:false,
  can:()=>true,bCheck:()=>({errors:[]}),clone:x=>JSON.parse(JSON.stringify(x)),
  locked:()=>false,paidOf:()=>0,calc:()=>({total:1000}),tl:()=>{},audit:()=>{},save:()=>{},
  toast:()=>{},atomicEnabled:()=>true,atomicReady:async()=>true,
  clearTimeout:()=>{},PUSH_T:null,$:()=>null,coBody:x=>JSON.parse(JSON.stringify(x)),
  SB:{rpc:async name=>name==='reserve_invoice_number'
    ?{data:{number:'INV-1001',nextNo:1002},error:null}
    :{data:null,error:{message:'Database unavailable'}}},
  go:()=>{throw Error('Unexpected navigation after save failure')},
  atomicApply:()=>{throw Error('atomicApply called after failure')}
 });
 vm.runInContext(bSaveSource+'\nthis.saveInvoice=bSave;',failed);
 await failed.saveInvoice();
}
async function testAtomicPayment(){
 const invoice={id:'invoice-1',currency:'MYR',lhdn:{status:'Not Submitted'},payments:[]};
 const co={id:'company-1',invoices:[invoice]};
 const inputs={'py-a':'12.50','py-d':'2026-11-19','py-m':'Cash','py-r':'REF123'};
 let called=0,closed=false,wholeCompanySave=false;
 const context=vm.createContext({
  CO:()=>co,can:()=>true,
  val:k=>inputs[k]||'',toSen:v=>Math.round(Number(v)*100),
  balance:()=>5000,money:v=>'RM '+(v/100).toFixed(2),
  todayStr:()=> '2026-11-19',
  uuid:()=> 'payment-unique-1',DB:{session:'test@example.invalid'},
  toast:()=>{},CLOUD:true,
  atomicEnabled:()=>true,atomicReady:async()=>true,
  coBody:x=>({invoices:x.invoices}),atomicApply:(c,r)=>{c.invoices[0]=r.invoice;return true},
  SB:{rpc:async(name,args)=>{called++;
   assert.equal(name,'atomic_add_payment');
   assert.equal(args.p_payment.id,'payment-unique-1');
   return {data:{invoice:{...invoice,payments:[args.p_payment]},version:6,company_data:{}},error:null};
  }},
  closeModal:()=>{closed=true},rerender:()=>{},
  save:()=>{wholeCompanySave=true},tl:()=>{},audit:()=>{},clearTimeout:()=>{},PUSH_T:null
 });
 vm.runInContext('let PAYMENT_SAVING=false,PAYMENT_PENDING_ID=null;\n'+paymentSource+
  '\nthis.savePayment=savePay;',context);
 await context.savePayment('invoice-1');
 assert.equal(called,1);
 assert.equal(co.invoices[0].payments.length,1);
 assert.equal(co.invoices[0].payments[0].amount,1250);
 assert.equal(closed,true);
 assert.equal(wholeCompanySave,false,'No legacy blob overwrite');
}
(async()=>{
 await testAtomicInvoice();
 await testAtomicPayment();
 console.log('PASS: atomic invoice and payment Save handlers, server numbering and error rejection');
})().catch(e=>{console.error(e);process.exitCode=1});
