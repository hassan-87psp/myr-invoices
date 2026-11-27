import {submitSandbox,pollSandbox} from "./sandbox_transport_candidate.ts";
const SUB="S".repeat(26),DOC="D".repeat(26);
function assert(ok:unknown):asserts ok{if(!ok)throw Error("assertion failed");}
async function reject(f:()=>Promise<unknown>){try{await f();}catch{return;}throw Error("expected rejection");}
async function fixture(){
 const taxpayer="C1234567890",tenant_id="00000000-0000-4000-8000-000000000001",code_number="TEST-1";
 const raw=new TextEncoder().encode(JSON.stringify({Invoice:[{ID:[{_:code_number}],InvoiceTypeCode:[{_:"01",listVersionID:"1.0"}],
   AccountingSupplierParty:[{Party:[{PartyIdentification:[{ID:[{_:taxpayer,schemeID:"TIN"}]}]}]}]}]}));
 const document_hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",raw)),x=>x.toString(16).padStart(2,"0")).join("");
 const c={enabled:true,environment:"sandbox",tenant_id,taxpayer,token:"synthetic-token",grant:{tenant_id,taxpayer,code_number,document_hash}};
 const payload={documents:[{format:"JSON",document:btoa(String.fromCharCode(...raw)),documentHash:document_hash,codeNumber:code_number}]};
 return {c,payload};
}
const receipt={submissionUID:SUB,acceptedDocuments:[{uuid:DOC,invoiceCodeNumber:"TEST-1",private:"do-not-return"}],rejectedDocuments:[]};
function mock(data:unknown,status=200,headers:Record<string,string>={}){
 const calls:{url:string;init?:RequestInit}[]=[];
 const send=(async(input:RequestInfo|URL,init?:RequestInit)=>{calls.push({url:String(input),init});return new Response(JSON.stringify(data),{status,headers});}) as typeof fetch;
 return {calls,send};
}
Deno.test("sandbox grant, fixed URL and minimal receipt",async()=>{
 const {c,payload}=await fixture();const m=mock(receipt,202);
 const r=await submitSandbox(c,payload,m.send);
 assert(r.state==="accepted"&&m.calls.length===1&&m.calls[0].url==="https://preprod-api.myinvois.hasil.gov.my/api/v1.0/documentsubmissions/");
 assert(m.calls[0].init?.redirect==="error"&&!JSON.stringify(r).includes("do-not-return")&&!JSON.stringify(r).includes(c.token));
});
Deno.test("disabled, production, mismatched grant and tampering stop before transport",async()=>{
 const {c,payload}=await fixture();const m=mock(receipt,202);
 for(const ctx of [{...c,enabled:false},{...c,environment:"production"},{...c,taxpayer:"C9876543210"}]){
   await reject(()=>submitSandbox(ctx,payload,m.send));
 }
 await reject(()=>submitSandbox(c,{documents:[{...payload.documents[0],document:btoa("tampered")}]},m.send));
 assert(m.calls.length===0);
});
Deno.test("duplicate or ambiguous response cannot enable retry",async()=>{
 const {c,payload}=await fixture();
 const m=mock({private:"do-not-return"},422,{"Retry-After":"120"});
 const r=await submitSandbox(c,payload,m.send);
 assert(r.state==="outcome_unknown"&&r.retry_enabled===false&&r.retry_after===120&&m.calls.length===1);
 assert(!JSON.stringify(r).includes("do-not-return"));
 const wrong=mock({...receipt,acceptedDocuments:[{uuid:DOC,invoiceCodeNumber:"OTHER"}]},202);
 assert((await submitSandbox(c,payload,wrong.send)).state==="outcome_unknown");
});
Deno.test("poll binds issuer, receipt and code and projects only safe fields",async()=>{
 const {c}=await fixture();
 const row={uuid:DOC,submissionUid:SUB,internalId:"TEST-1",issuerTin:c.taxpayer,status:"Valid",longId:"LONG123",dateTimeValidated:"2026-11-27T03:00:00Z",issuerName:"PRIVATE"};
 const m=mock({submissionUid:SUB,documentCount:1,documentSummary:[row]});
 const r=await pollSandbox(c,SUB,DOC,m.send);
 assert(r.state==="polled"&&!JSON.stringify(r).includes("PRIVATE")&&m.calls.length===1);
 const bad=mock({submissionUid:SUB,documentCount:1,documentSummary:[{...row,issuerTin:"C9999999999"}]});
 assert((await pollSandbox(c,SUB,DOC,bad.send)).state==="poll_unavailable");
 await reject(()=>pollSandbox(c,"../../secret",DOC,m.send));
});
Deno.test("network failure makes exactly one write attempt",async()=>{
 const {c,payload}=await fixture();let calls=0;
 const send=(async()=>{calls++;throw Error("synthetic timeout");}) as typeof fetch;
 const r=await submitSandbox(c,payload,send);
 assert(r.state==="outcome_unknown"&&r.retry_enabled===false&&calls===1);
});
