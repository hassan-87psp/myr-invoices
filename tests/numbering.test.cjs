'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('index.html','utf8');
const start=src.indexOf('async function bSave(status)');
const stop=src.indexOf('function bPreview()',start);
assert.ok(start>0&&stop>start,'Invoice save source exists');
const handler=src.slice(start,stop);
const draftStart=src.indexOf('function myrDraftFields('),draftEnd=src.indexOf('function myrDraftRead(',draftStart);
assert.ok(draftStart>=0&&draftEnd>draftStart,'Draft fields helper exists');
const draftFields=src.slice(draftStart,draftEnd);
function setup(rpcResult){
 const co={id:'company-1',prefix:'INV-',nextNo:1001,approvalRequired:false,invoices:[]};
 const invoice={id:'new-1',number:'INV-1001',_autoNumber:'INV-1001',currency:'MYR',appStatus:'Draft',items:[{id:'line',qty:1,price:1000}],payments:[],lhdn:{status:'Not Submitted',attempts:[]}};
 let saves=0,remote=0,goTo='',calls=0;
 const toasts=[];
 const context=vm.createContext({
  ED:invoice,CO:()=>co, MYR_INV_BASE:'',myrDraftClear:()=>{},CLOUD:true,UNSYNCED_CLOUD:false,INVOICE_SAVING:false, atomicEnabled:()=>false,
  can:()=>true,
  bCheck:()=>({errors:[]}),
  clone:x=>JSON.parse(JSON.stringify(x)),
  locked:()=>false,
  calc:i=>({total:i.items.reduce((n,v)=>n+v.price*v.qty,0)}),
  paidOf:i=>(i.payments||[]).reduce((n,v)=>n+v.amount,0),
  tl:()=>{},audit:()=>{},save:()=>{saves++},clearTimeout:()=>{},PUSH_T:null,
  toast:(msg)=>{toasts.push(msg)},go:url=>{goTo=url},$:(()=>null),
  cloudPush:async()=>{remote++;return true},
  SB:{rpc:async(name,args)=>{calls++;assert.equal(name,'reserve_invoice_number');assert.equal(args.p_invoice_id,'new-1');return rpcResult;}}
 });
 vm.runInContext(draftFields+handler+'\nthis.runSave=bSave;',context);
 return {co,invoice,context,toasts,stats:()=>({saves,remote,goTo,calls})};
}
(async()=>{
 const a=setup({data:{number:'INV-1002',nextNo:1003},error:null});
 await a.context.runSave();
 assert.equal(a.stats().calls,1,'Server RPC called once');
 assert.equal(a.co.invoices.length,1,'New invoice persisted in local state');
 assert.equal(a.co.invoices[0].number,'INV-1002','Server number takes precedence');
 assert.equal(a.co.nextNo,1003,'Server sequence updates counter');
 assert.equal(a.co.invoices[0]._autoNumber,undefined,'Transient auto marker never stored');
 assert.equal(a.stats().remote,1,'Cloud persistence confirmed');
 assert.ok(a.stats().goTo.endsWith('/view/new-1'));
 assert.equal(JSON.parse(a.context.MYR_INV_BASE).number,'INV-1002','Draft baseline reflects reserved number');

 const b=setup({data:null,error:{message:'Not authorized'}});
 await b.context.runSave();
 assert.equal(b.co.invoices.length,0,'Failed reservation must not save an invoice');
 assert.equal(b.stats().remote,0,'Failed reservation must not push to cloud');
 assert.ok(b.toasts.some(t=>t.includes('Unable to reserve')),'User is notified of reservation error');

 const c=setup({data:{number:'INV-1001',nextNo:1002},error:null});
 c.invoice.number='CUSTOM-7';
 await c.context.runSave();
 assert.equal(c.stats().calls,0,'Manually entered number bypasses auto reservation');
 assert.equal(c.co.invoices[0].number,'CUSTOM-7');
 console.log('PASS: server-allocated invoice number, failure safety, manual numbering');
})().catch(e=>{console.error(e);process.exitCode=1;});
