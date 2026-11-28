import { createHandler, retryDeadline } from "./handler.ts";
const secret="a".repeat(64);
const values:Record<string,string>={MYR_LHDN_BRIDGE_SECRET:secret,MYR_LHDN_SANDBOX_CLIENT_ID:"mock",MYR_LHDN_SANDBOX_CLIENT_SECRET:"mock-secret"};
let calls=0;
const provider=(async (url: string, init:RequestInit)=>{
  calls++;
  if(url!=="https://preprod-api.myinvois.hasil.gov.my/connect/token")throw Error("wrong origin");
  if(!new Headers(init.headers).get("onbehalfof"))throw Error("missing taxpayer header");
  return new Response(JSON.stringify({access_token:"mock-private-token",token_type:"Bearer",expires_in:3600}),{status:200});
}) as typeof fetch;
const handler=createHandler(k=>values[k],provider);
const body={action:"check_connection",environment:"sandbox",tenant_id:"00000000-0000-4000-8000-000000000001",taxpayer:"C1234567890"};
const req=(payload:object,key=secret)=>new Request("https://example.invalid",{method:"POST",headers:{Authorization:"Bearer "+key,"Content-Type":"application/json"},body:JSON.stringify(payload)});
function assert(value:boolean){if(!value)throw Error("assertion failed");}
Deno.test("fails closed, isolates customers, caches tokens without exposing them",async()=>{
  assert((await handler(req(body,"b".repeat(64)))).status===401);
  assert((await handler(req(body))).status===503);
  assert(calls===0);
  values.MYR_LHDN_SANDBOX_CONNECTION_CHECK_ENABLED="true";
  const first=await handler(req(body)); const result=await first.text();
  assert(first.status===200 && result.includes("provider_login") && !result.includes("mock-private-token"));
  const again=await handler(req(body));assert((await again.json()).verification==="cached" && calls===1);
  assert((await handler(req({...body,tenant_id:"00000000-0000-4000-8000-000000000002"}))).status===200 && calls===2);
  assert((await handler(req({...body,taxpayer:"C9876543210"}))).status===200 && calls===3);
  assert((await handler(req({...body,environment:"production"}))).status===503 && calls===3);
  assert((await handler(req({...body,action:"submit"}))).status===400 && calls===3);
});

Deno.test("TIN pilot remains sandbox-only, verifies BRN and never leaks token",async()=>{
  const settings={...values,MYR_LHDN_SANDBOX_CONNECTION_CHECK_ENABLED:"true"} as Record<string,string>;
  delete settings.MYR_LHDN_SANDBOX_TIN_VALIDATION_ENABLED;
  let authCalls=0,validationCalls=0;
  const mock=(async (url:string,init:RequestInit)=>{
    const headers=new Headers(init.headers);
    if(url.endsWith("/connect/token")){
      authCalls++;
      assert(headers.get("onbehalfof")==="C1234567890:123456789012");
      return new Response(JSON.stringify({access_token:"private-test-token",token_type:"Bearer",expires_in:3600}));
    }
    validationCalls++;
    assert(url==="https://preprod-api.myinvois.hasil.gov.my/api/v1.0/taxpayer/validate/C1234567890?idType=BRN&idValue=123456789012");
    assert(init.method==="GET" && headers.get("Authorization")==="Bearer private-test-token");
    return new Response(null,{status:200});
  }) as typeof fetch;
  const h=createHandler(k=>settings[k],mock);
  const payload={...body,action:"validate_self_tin",taxpayer:"C1234567890:123456789012",brn:"123456789012"};
  assert((await h(req(payload))).status===503 && authCalls===0);
  settings.MYR_LHDN_SANDBOX_TIN_VALIDATION_ENABLED="true";
  assert((await h(req({...payload,environment:"production"}))).status===503 && authCalls===0);
  assert((await h(req({...payload,brn:"OTHER"}))).status===400 && authCalls===0);
  const res=await h(req(payload));const raw=await res.text();
  assert(res.status===200 && raw.includes("provider_tin") && !raw.includes("private-test-token"));
  assert((await (await h(req(payload))).json()).verification==="cached_tin");
  assert(authCalls===1 && validationCalls===1);
  assert((await h(req({...payload,tenant_id:"00000000-0000-4000-8000-000000000002"}))).status===200);
  assert(authCalls===2 && validationCalls===2);
  assert((await h(req({...payload,action:"submit"}))).status===400);
});

Deno.test("provider retry deadline preserves long and date-based waits",()=>{
 const now=Date.parse("2026-11-28T03:00:00Z");
 assert(retryDeadline("7200",now)===now+7200000);
 assert(retryDeadline("Sat, 28 Nov 2026 05:00:00 GMT",now)===now+7200000);
 assert(retryDeadline(null,now)===now+60000);
 assert(retryDeadline("0",now)===now+60000);
 assert(retryDeadline("bad",now)===now+60000);
});
Deno.test("denied taxpayer validation invalidates cached access",async()=>{
 const settings={...values,MYR_LHDN_SANDBOX_CONNECTION_CHECK_ENABLED:"true",MYR_LHDN_SANDBOX_TIN_VALIDATION_ENABLED:"true"} as Record<string,string>;
 let logins=0;
 const mock=(async (url:string)=>{
   if(url.endsWith("/connect/token")){logins++;return new Response(JSON.stringify({access_token:"token-"+logins,token_type:"Bearer",expires_in:3600}));}
   return new Response(null,{status:403});
 }) as typeof fetch;
 const h=createHandler(k=>settings[k],mock);
 const p={...body,action:"validate_self_tin",brn:"123456789012"};
 assert((await h(req(p))).status===403);
 assert((await h(req(body))).status===200);
 assert(logins===2);
});
