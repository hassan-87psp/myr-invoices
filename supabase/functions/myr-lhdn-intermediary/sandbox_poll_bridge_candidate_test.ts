import {createPollCandidate} from "./sandbox_poll_bridge_candidate.ts";
const secret="b".repeat(64),now=Date.parse("2026-11-28T07:00:00Z"),sub="S".repeat(26),doc="D".repeat(26);
const grant={tenant_id:"00000000-0000-4000-8000-000000000001",taxpayer:"C1234567890",code_number:"PILOT-1",document_hash:"a".repeat(64),submission_uid:sub,uuid:doc,expires_at:new Date(now+600000).toISOString()};
function assert(x:unknown):asserts x{if(!x)throw Error("assertion failed")}
function fixture(){
 const env:Record<string,string>={MYR_LHDN_SANDBOX_POLL_SECRET:secret,MYR_LHDN_SANDBOX_POLL_ENABLED:"true",MYR_LHDN_SANDBOX_POLL_GRANT:JSON.stringify(grant),MYR_LHDN_SANDBOX_CLIENT_ID:"fake-id",MYR_LHDN_SANDBOX_CLIENT_SECRET:"fake-secret"};
 const row={uuid:doc,submissionUid:sub,internalId:grant.code_number,issuerTin:grant.taxpayer,status:"Valid",longId:"LONG1",dateTimeValidated:new Date(now).toISOString(),issuerName:"PRIVATE"};
 const calls:string[]=[];
 const send=(async(url:RequestInfo|URL,init?:RequestInit)=>{
  calls.push(String(url));
  if(String(url).endsWith("/connect/token")){assert(init?.method==="POST"&&new Headers(init.headers).get("onbehalfof")===grant.taxpayer);return new Response(JSON.stringify({access_token:"fake-token",token_type:"Bearer",expires_in:3600}))}
  assert(init?.method==="GET"&&String(url)==="https://preprod-api.myinvois.hasil.gov.my/api/v1.0/documentsubmissions/"+sub+"?pageNo=1&pageSize=10");
  return new Response(JSON.stringify({submissionUid:sub,documentCount:1,documentSummary:[row]}))
 }) as typeof fetch;
 const handler=createPollCandidate(k=>env[k],send,()=>now);
 const body={environment:"sandbox",tenant_id:grant.tenant_id,submission_uid:sub,uuid:doc};
 const req=(b:object,key=secret)=>new Request("https://example.invalid",{method:"POST",headers:{Authorization:"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify(b)});
 return {env,row,calls,handler,body,req};
}
Deno.test("private receipt-bound Sandbox poll produces only normalized result",async()=>{
 const f=fixture(),r=await f.handler(f.req(f.body)),b=await r.json();
 assert(r.status===200&&b.state==="polled"&&f.calls.length===2&&!JSON.stringify(b).includes("PRIVATE")&&!JSON.stringify(b).includes("fake-token"));
});
Deno.test("poll refuses wrong secret, disabled gate, other tenant, production and expired grant",async()=>{
 const f=fixture();
 assert((await f.handler(f.req(f.body,"wrong"))).status===401);
 assert((await f.handler(f.req({...f.body,environment:"production"}))).status===403);
 assert((await f.handler(f.req({...f.body,uuid:"X".repeat(26)}))).status===403);
 f.env.MYR_LHDN_SANDBOX_POLL_ENABLED="false";assert((await f.handler(f.req(f.body))).status===503);
 f.env.MYR_LHDN_SANDBOX_POLL_ENABLED="true";f.env.MYR_LHDN_SANDBOX_POLL_GRANT=JSON.stringify({...grant,expires_at:new Date(now-1).toISOString()});
 assert((await f.handler(f.req(f.body))).status===503&&f.calls.length===0);
});
Deno.test("wrong issuer cannot return verified status",async()=>{
 const f=fixture();f.row.issuerTin="C9999999999";const r=await f.handler(f.req(f.body));assert(r.status===502&&(await r.json()).state==="poll_unavailable");
});
