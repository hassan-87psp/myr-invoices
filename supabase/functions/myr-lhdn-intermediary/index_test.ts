import { createHandler } from "./handler.ts";
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
