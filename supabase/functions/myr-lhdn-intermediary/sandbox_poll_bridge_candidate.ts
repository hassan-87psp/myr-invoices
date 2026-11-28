// Staged, private, connection-only read/poll bridge. No document submission.
// The exact receipt grant must be operator-installed; never issue it to a browser.
// No deployment entrypoint is provided until isolated DB, grants and release review pass.
import {pollSandbox,pollRetrySeconds} from "./sandbox_transport_candidate.ts";
const BASE="https://preprod-api.myinvois.hasil.gov.my";
const enc=new TextEncoder();
type Env=(name:string)=>string|undefined;
type Grant={tenant_id:string;taxpayer:string;code_number:string;document_hash:string;submission_uid:string;uuid:string;expires_at:string};
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==="object"&&!Array.isArray(v);
const reply=(status:number,data:object)=>new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
async function auth(secret:string,header:string){
 if(!/^[a-f0-9]{64}$/.test(secret)||!/^Bearer [a-f0-9]{64}$/.test(header))return false;
 const alg={name:"HMAC",hash:"SHA-256"};
 const a=await crypto.subtle.importKey("raw",enc.encode(secret),alg,false,["sign"]);
 const b=await crypto.subtle.importKey("raw",enc.encode(header.slice(7)),alg,false,["verify"]);
 const data=enc.encode("myr-sandbox-poll-v1");
 return crypto.subtle.verify("HMAC",b,await crypto.subtle.sign("HMAC",a,data),data);
}
async function bounded(body:ReadableStream<Uint8Array>|null,max:number){
 const reader=body?.getReader();if(!reader)throw Error("body required");
 const bytes=new Uint8Array(max);let size=0;
 for(;;){const p=await reader.read();if(p.done)break;if(p.value.byteLength>max-size){await reader.cancel();throw Error("oversize")}bytes.set(p.value,size);size+=p.value.byteLength}
 return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes.subarray(0,size)));
}
function grant(env:Env,now:number):Grant|null{
 try{
 const g=JSON.parse(env("MYR_LHDN_SANDBOX_POLL_GRANT")||"null");
 if(!object(g)||Object.keys(g).sort().join(",")!=="code_number,document_hash,expires_at,submission_uid,taxpayer,tenant_id,uuid")return null;
 if(typeof g.tenant_id!=="string"||!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(g.tenant_id)||
    typeof g.taxpayer!=="string"||!/^[A-Z]{1,3}[0-9]{1,13}$/.test(g.taxpayer)||
    typeof g.document_hash!=="string"||!/^[a-f0-9]{64}$/.test(g.document_hash)||
    typeof g.code_number!=="string"||g.code_number.length<1||g.code_number.length>50||
    typeof g.submission_uid!=="string"||!/^[A-Za-z0-9]{26}$/.test(g.submission_uid)||
    typeof g.uuid!=="string"||!/^[A-Za-z0-9]{26}$/.test(g.uuid)||
    typeof g.expires_at!=="string"||!/Z$/.test(g.expires_at))return null;
 const expires=Date.parse(g.expires_at);
 if(!Number.isFinite(expires)||expires<=now||expires>now+15*60000)return null;
 return g as Grant;
 }catch{return null}
}
export function createPollCandidate(env:Env,send:typeof fetch=fetch,clock=Date.now){
 // Local in-flight guard supplements the mandatory durable VPS reservation.
 // Cross-instance rate limiting must be rehearsed before deployment.
 let busy=false;
 return async(req:Request)=>{
  if(req.method!=="POST")return reply(405,{code:"method_not_allowed"});
  try{
   if(!await auth(env("MYR_LHDN_SANDBOX_POLL_SECRET")||"",req.headers.get("Authorization")||""))return reply(401,{code:"unauthorized"});
   if(env("MYR_LHDN_SANDBOX_POLL_ENABLED")!=="true")return reply(503,{code:"poll_disabled"});
   const g=grant(env,clock());if(!g)return reply(503,{code:"grant_required"});
   const b=await bounded(req.body,4096);
   if(!object(b)||Object.keys(b).sort().join(",")!=="environment,submission_uid,tenant_id,uuid"||b.environment!=="sandbox"||b.tenant_id!==g.tenant_id||b.submission_uid!==g.submission_uid||b.uuid!==g.uuid)return reply(403,{code:"grant_mismatch"});
   if(busy)return reply(429,{state:"poll_unavailable",retry_after:60});
   const id=env("MYR_LHDN_SANDBOX_CLIENT_ID"),secret=env("MYR_LHDN_SANDBOX_CLIENT_SECRET");
   if(!id||!secret)return reply(503,{code:"credentials_required"});
   busy=true;
   try{
    // Fresh login for this short-lived, operator-only pilot; no cached authorization after revocation.
    const tokenResponse=await send(BASE+"/connect/token",{method:"POST",redirect:"error",signal:AbortSignal.timeout(20000),headers:{"Content-Type":"application/x-www-form-urlencoded",Accept:"application/json",onbehalfof:g.taxpayer},body:new URLSearchParams({client_id:id,client_secret:secret,grant_type:"client_credentials",scope:"InvoicingAPI"})});
    if(tokenResponse.status!==200){const delay=pollRetrySeconds(tokenResponse.headers.get("Retry-After"),clock());await tokenResponse.body?.cancel();return reply(502,{state:"poll_unavailable",retry_after:delay})}
    const token=await bounded(tokenResponse.body,65536);
    if(!object(token)||typeof token.access_token!=="string"||String(token.token_type).toLowerCase()!=="bearer"||typeof token.expires_in!=="number"||token.expires_in<=60)return reply(502,{state:"poll_unavailable",retry_after:60});
    const current=grant(env,clock());
    if(env("MYR_LHDN_SANDBOX_POLL_ENABLED")!=="true"||!current||JSON.stringify(current)!==JSON.stringify(g))return reply(503,{code:"grant_revoked"});
    const result=await pollSandbox({enabled:true,environment:"sandbox",tenant_id:g.tenant_id,taxpayer:g.taxpayer,grant:g,token:token.access_token},g.submission_uid,g.uuid,send);
    return reply(result.state==="polled"?200:502,result);
   }finally{busy=false}
  }catch{return reply(502,{state:"poll_unavailable",retry_after:60})}
 };
}
