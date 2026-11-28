'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('index.html','utf8');
const start=src.indexOf('function myrPdfLines('),end=src.indexOf('function printDoc()',start);
assert.ok(start>=0&&end>start,'PDF document renderer exists');
const calc=src.split('\n').find(x=>x.startsWith('function calc(inv)'));
assert.ok(calc,'Financial calculation used by renderer exists');
const deps=['const UNITS=','const TAX_TYPES=','const portalBase=','const verifyUrl='].map(prefix=>{const line=src.split('\n').find(x=>x.startsWith(prefix));assert.ok(line,'Missing real renderer dependency '+prefix);return line;}).join('\n');
let qrCalls=0;
const ctx=vm.createContext({
 STATES:[],DOC_TYPES:{'01':'Invoice'},
 isSelfBilled:()=>false,isAdj:()=>false,isSale:()=>true,
 esc:x=>String(x??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),
 money:x=>'RM '+(Number(x)/100).toFixed(2),
 fmtDate:x=>x||'—',fmtDT:x=>x||'—',
 qrSvg:()=>{qrCalls++;return '<svg data-qr="yes"></svg>'}
});
vm.runInContext(deps+'\n'+calc+'\n'+src.slice(start,end)+'\nthis.draw=docHTML;',ctx);
const co={
 name:'Fictional Seller',tin:'C1234567890',brn:'202601000001',
 msic:'62010',msicDesc:'Services',phone:'',email:'',
 addr:{line:'1 Example Road',city:'Kuala Lumpur',postcode:'50000',state:'14',country:'MYS'},
 logo:'data:image/png;base64,FAKE" onerror="alert(1)',
 customers:[{id:'c1',name:'Buyer <script>alert(1)</script>',tin:'C1234567800',idType:'BRN',idValue:'202601000002',addr:{line:'2 Example Road',city:'Kuala Lumpur',state:'14',country:'MYS'}}],
 invoices:[],lhdn:{env:'sandbox'}
};
const inv={
 id:'i1',number:'INV-1001',docType:'01',customerId:'c1',
 issueDate:'2026-11-19',dueDate:'2026-12-19',
 currency:'MYR',items:[{id:'l1',desc:'Consulting <b>test</b>',classCode:'022',unitCode:'C62',qty:1,price:2500,discount:0,taxRate:0,taxType:'06'}],
 notes:'',payTerms:'Net 30',lhdn:{status:'Not Submitted',uuid:''}
};
let html=ctx.draw(inv,co);
assert.match(html,/myr-paper-state pending[^>]*>Not yet validated by LHDN/,'Draft must be visibly unvalidated');
assert.match(html,/Official UUID, validation date-time and verification QR are displayed only after LHDN returns a Valid status/);
assert.match(html,/RM 25\.00/,'Correct total on print document');
assert.ok(html.includes('&lt;b&gt;test&lt;/b&gt;'),'Line descriptions are escaped');
assert.ok(html.includes('&lt;script&gt;'),'Buyer name is escaped');
assert.ok(!html.includes('onerror="alert(1)"'),'Logo attribute cannot inject HTML');
assert.equal(qrCalls,0,'Draft invoice must not show verification QR');
html=ctx.draw(inv,co,{sample:true});
assert.match(html,/Sample · Not validated/,'Sample must be prominently marked');
assert.equal(qrCalls,0);
inv.lhdn.status='Valid';
inv.lhdn.uuid='official-demo-uuid';
html=ctx.draw(inv,co);
assert.equal(qrCalls,0,'Valid status without longId must not show verification QR');
inv.lhdn.longId='verified-long-id';
html=ctx.draw(inv,co);
assert.match(html,/Validated by LHDN MyInvois/);
assert.equal(qrCalls,1,'Verification QR displayed only when Valid status has URL');
assert.ok(html.includes('https://preprod.myinvois.hasil.gov.my/official-demo-uuid/share/verified-long-id'));
ctx.draw(inv,co,{sample:true});
assert.equal(qrCalls,1,'Sample never shows a verification QR');
inv.lhdn.status='Cancelled';
html=ctx.draw(inv,co);
assert.match(html,/Cancelled document/);
assert.equal(qrCalls,1,'Cancelled invoice must not show QR');
console.log('PASS: invoice printable HTML, unvalidated watermark, safe text/logo rendering, QR gating');
