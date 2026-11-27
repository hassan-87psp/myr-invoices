import {createDispatchCandidate} from "./sandbox_dispatch_bridge_candidate.ts";
const secret="a".repeat(64),tenant_id="00000000-0000-4000-8000-000000000001",taxpayer="C1234567890",code_number="INV-1";
const now=Date.parse("2026-11-27T04:00:00Z");
function assert(v:unknown):asserts v{if(!v)throw Error("assertion failed");}
async function fixture(){
 const raw=new TextEncoder().encode(JSON.stringify({Invoice:[{ID:[{_:code_number}],InvoiceTypeCode:[{_:"01",listVersionID:"1.0"}],AccountingSupplierParty:[{Party:[{PartyIdentification:[{ID:[{_:taxpayer,schemeID:"TIN"}]}]}]}]}]}));
 const document_hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",raw)),x=>x.toString(16).padStart(2,"0")).join("");
 const grant={tenant_id,taxpayer,code_number,document_hash,expires_at:new Date(now+600000).toISOString()};
 const env:Record<string,string>={MYR_LHDN_SANDBOX_DISPATCH_SECRET:secret,MYR_LHDN_SANDBOX_DISPATCH_ENABLED:"true",MYR_LHDN_SANDBOX_EXACT_GRANT:JSON.stringify(grant),MYR_LHDN_SANDBOX_CLIENT_ID:"test-id",MYR_LHDN_SANDBOX_CLIENT_SECRET:"test-secret"};
 const body={environment:"sandbox",tenant_id,taxpayer,payload:{documents:[{format:"JSON",document:btoa(String.fromCharCode(...raw)),documentHash:document_hash,codeNumber:code_number}]}};
 let claims=0;const calls:string[]=[];
 const claim=async()=>++claims===1;
 const send=(async(input:RequestInfo|URL)=>{
   const url=String(input);calls.push(url);
   if(url.endsWith("/connect/token"))return new Response(JSON.stringify({access_token:"test-token",token_type:"Bearer",expires_in:3600}),{status:200});
   return new Response(JSON.stringify({submissionUID:"S".repeat(26),acceptedDocuments:[{uuid:"D".repeat(26),invoiceCodeNumber:code_number}],rejectedDocuments:[]}),{status:202});
 }) as typeof fetch;
 const handler=createDispatchCandidate(k=>env[k],claim,send,()=>now);
 const req=(b=body,auth="Bearer "+secret)=>new Request("https://example.invalid",{method:"POST",headers:{Authorization:auth,"Content-Type":"application/json"},body:JSON.stringify(b)});
 return {grant,env,body,handler,req,calls,claims:()=>claims,send};
}
Deno.test("exact one-shot grant, no replay and no credential response",async()=>{
 const f=await fixture();
 const r=await f.handler(f.req());assert(r.status===200);
 const d=await r.text();assert(d.includes('"state":"accepted"')&&!d.includes("test-token")&&!d.includes("test-secret"));
 assert(f.calls.length===2);
 const replay=await f.handler(f.req());assert(replay.status===409);assert(f.calls.length===2);
});
Deno.test("gate, tenant and production mismatch stop before claim",async()=>{
 const f=await fixture();
 assert((await f.handler(f.req(f.body,"Bearer "+"b".repeat(64)))).status===401);
 f.env.MYR_LHDN_SANDBOX_DISPATCH_ENABLED="false";
 assert((await f.handler(f.req())).status===503);
 f.env.MYR_LHDN_SANDBOX_DISPATCH_ENABLED="true";
 assert((await f.handler(f.req({...f.body,environment:"production"}))).status===403);
 assert((await f.handler(f.req({...f.body,taxpayer:"C9999999999"}))).status===403);
 assert(f.claims()===0&&f.calls.length===0);
});
Deno.test("expired grant and unavailable durable fence prevent provider calls",async()=>{
 const f=await fixture();f.env.MYR_LHDN_SANDBOX_EXACT_GRANT=JSON.stringify({...f.grant,expires_at:new Date(now-1).toISOString()});
 assert((await f.handler(f.req())).status===503&&f.calls.length===0);
 f.env.MYR_LHDN_SANDBOX_EXACT_GRANT=JSON.stringify(f.grant);
 const handler=createDispatchCandidate(k=>f.env[k],async()=>{throw Error("uncertain claim");},f.send,()=>now);
 assert((await handler(f.req())).status===502&&f.calls.length===0);
});
Deno.test("grant revocation during login blocks submission",async()=>{
 const f=await fixture();let writes=0;
 const handler=createDispatchCandidate(k=>f.env[k],async()=>true,(async(input:RequestInfo|URL)=>{
   if(String(input).endsWith("/connect/token")){
     f.env.MYR_LHDN_SANDBOX_DISPATCH_ENABLED="false";
     return new Response(JSON.stringify({access_token:"test-token",token_type:"Bearer",expires_in:3600}));
   }
   writes++;throw Error("unexpected dispatch");
 }) as typeof fetch,()=>now);
 assert((await handler(f.req())).status===503&&writes===0);
});
