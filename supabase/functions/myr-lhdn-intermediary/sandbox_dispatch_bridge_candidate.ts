// Candidate only. Never deploy until fence schema, grants, VPS and sandbox tests pass.
// A single exact, expiring operator grant plus a durable unique dispatch fence.
// No browser credentials accepted, no production route, no automatic write retry.
import {submitSandbox} from "./sandbox_transport_candidate.ts";
const enc=new TextEncoder();
const BASE="https://preprod-api.myinvois.hasil.gov.my";
type Env=(name:string)=>string|undefined;
type Grant={tenant_id:string;taxpayer:string;document_hash:string;code_number:string;expires_at:string};
type Claim=(grant:Grant)=>Promise<boolean>;
const isObject=(x:unknown):x is Record<string,unknown>=>!!x&&typeof x==="object"&&!Array.isArray(x);
const out=(status:number,data:object)=>new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
async function authorized(secret:string,header:string){
 if(!/^[a-f0-9]{64}$/.test(secret)||!/^Bearer [a-f0-9]{64}$/.test(header))return false;
 const alg={name:"HMAC",hash:"SHA-256"};
 const a=await crypto.subtle.importKey("raw",enc.encode(secret),alg,false,["sign"]);
 const b=await crypto.subtle.importKey("raw",enc.encode(header.slice(7)),alg,false,["verify"]);
 const data=enc.encode("myr-sandbox-dispatch-v1");
 return crypto.subtle.verify("HMAC",b,await crypto.subtle.sign("HMAC",a,data),data);
}
async function readBounded(body:ReadableStream<Uint8Array>|null,max:number){
 const reader=body?.getReader();if(!reader)throw Error("body_required");
 const bytes=new Uint8Array(max);let size=0;
 for(;;){const part=await reader.read();if(part.done)break;
  if(part.value.byteLength>bytes.length-size){await reader.cancel();throw Error("body_too_large");}
  bytes.set(part.value,size);size+=part.value.byteLength;
 }
 return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes.subarray(0,size)));
}
function grant(env:Env,now:number):Grant|null{
 try{
  const g=JSON.parse(env("MYR_LHDN_SANDBOX_EXACT_GRANT")||"null");
  if(!isObject(g)||Object.keys(g).sort().join(",")!=="code_number,document_hash,expires_at,taxpayer,tenant_id")return null;
  if(typeof g.tenant_id!=="string"||!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(g.tenant_id)||
     typeof g.taxpayer!=="string"||!/^[A-Z]{1,3}[0-9]{1,13}$/.test(g.taxpayer)||
     typeof g.document_hash!=="string"||!/^[a-f0-9]{64}$/.test(g.document_hash)||
     typeof g.code_number!=="string"||g.code_number.length<1||g.code_number.length>50||
     typeof g.expires_at!=="string")return null;
  const expiry=Date.parse(g.expires_at);
  if(!Number.isFinite(expiry)||expiry<=now||expiry>now+15*60000)return null;
  return g as Grant;
 }catch{return null;}
}
export function createDispatchCandidate(env:Env,claim:Claim,send:typeof fetch=fetch,clock=Date.now){
 return async(req:Request)=>{
  try{
   if(req.method!=="POST")return out(405,{code:"method_not_allowed"});
   if(!await authorized(env("MYR_LHDN_SANDBOX_DISPATCH_SECRET")||"",req.headers.get("Authorization")||""))return out(401,{code:"unauthorized"});
   if(env("MYR_LHDN_SANDBOX_DISPATCH_ENABLED")!=="true")return out(503,{code:"dispatch_disabled"});
   const g=grant(env,clock());
   if(!g)return out(503,{code:"grant_required"});
   const body=await readBounded(req.body,350000);
   if(!isObject(body)||Object.keys(body).sort().join(",")!=="environment,payload,taxpayer,tenant_id"||
       body.environment!=="sandbox"||body.tenant_id!==g.tenant_id||body.taxpayer!==g.taxpayer)return out(403,{code:"grant_mismatch"});
   const id=env("MYR_LHDN_SANDBOX_CLIENT_ID"),secret=env("MYR_LHDN_SANDBOX_CLIENT_SECRET");
   if(!id||!secret)return out(503,{code:"credentials_required"});
   // Claim callback MUST atomically insert the unique grant hash before returning true.
   // A failed or uncertain claim must not allow a provider call.
   if(!await claim(g))return out(409,{code:"grant_already_claimed",retry_enabled:false});
   // Login fresh to avoid cached authorization after revocation.
   const tokenResponse=await send(BASE+"/connect/token",{method:"POST",redirect:"error",signal:AbortSignal.timeout(20000),
    headers:{"Content-Type":"application/x-www-form-urlencoded",Accept:"application/json",onbehalfof:g.taxpayer},
    body:new URLSearchParams({client_id:id,client_secret:secret,grant_type:"client_credentials",scope:"InvoicingAPI"})});
   if(tokenResponse.status!==200){await tokenResponse.body?.cancel();return out(502,{code:"login_failed",retry_enabled:false});}
   const token=await readBounded(tokenResponse.body,65536);
   if(!isObject(token)||typeof token.access_token!=="string"||String(token.token_type).toLowerCase()!=="bearer"||
     typeof token.expires_in!=="number"||token.expires_in<=60)return out(502,{code:"invalid_login",retry_enabled:false});
   // Re-read operator grant immediately before write. A removed/changed grant fails closed.
   const current=grant(env,clock());
   if(env("MYR_LHDN_SANDBOX_DISPATCH_ENABLED")!=="true"||!current||JSON.stringify(current)!==JSON.stringify(g))return out(503,{code:"grant_revoked",retry_enabled:false});
   const result=await submitSandbox({enabled:true,environment:"sandbox",tenant_id:g.tenant_id,taxpayer:g.taxpayer,grant:g,token:token.access_token},body.payload,send);
   return out(result.state==="accepted"?200:502,result);
  }catch{return out(502,{code:"dispatch_requires_review",retry_enabled:false});}
 };
}
