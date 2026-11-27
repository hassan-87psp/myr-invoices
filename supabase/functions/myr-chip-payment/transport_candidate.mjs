// Review-only adapter. Not imported by the deployed function.
// Caller must reserve a durable test intent BEFORE dispatch and quarantine unknown outcomes.
import {makePurchase,checkPurchase} from "./checkout_candidate.mjs";
const base="https://gate.chip-in.asia/api/v1/";
function require(ok,msg){if(!ok)throw new Error(msg)}
function uuid(x){return typeof x==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(x)}
export function buildTestTransport(config,fetcher=fetch){
 require(config.mode==="test"&&config.testCredentialVerified===true,"Test credential approval required");
 require(uuid(config.brand)&&typeof config.key==="string"&&/^[!-~]{1,1024}$/.test(config.key)&&!/^https?:/i.test(config.key),"Invalid configuration");
 async function call(path,method="GET",body){
   const res=await fetcher(base+path,{method,redirect:"error",signal:AbortSignal.timeout(15000),headers:{Authorization:"Bearer "+config.key,Accept:"application/json",...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});
   if(!res.ok){await res.body?.cancel();throw new Error("Provider request failed");}
   return await res.json();
 }
 return Object.freeze({
   async create(intent,email){
     require(intent.state==="dispatching"&&intent.provider_id==null,"Dispatch reservation required");
     const payload=makePurchase(intent,config.brand,email);
     // Never retry a timed-out POST automatically.
     const data=await call("purchases/","POST",payload);
     const result=checkPurchase(intent,config.brand,data);
     require(result.status==="created","Unexpected creation state");
     return result;
   },
   async reconcile(intent){
     require(uuid(intent.provider_id),"Known purchase required");
     return checkPurchase(intent,config.brand,await call("purchases/"+intent.provider_id+"/"));
   },
   async verifySuccessCallback(raw,signature){
     require(raw instanceof Uint8Array&&raw.length>0&&raw.length<=262144,"Invalid callback body");
     require(typeof signature==="string"&&signature.length<=4096&&/^[A-Za-z0-9+/]+={0,2}$/.test(signature),"Invalid signature");
     const pem=await call("public_key/");
     require(typeof pem==="string"&&pem.startsWith("-----BEGIN PUBLIC KEY-----"),"Invalid public key");
     const bytes=Uint8Array.from(atob(pem.replace(/-----BEGIN PUBLIC KEY-----|-----END PUBLIC KEY-----|\s/g,"")),x=>x.charCodeAt(0));
     const key=await crypto.subtle.importKey("spki",bytes,{name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"},false,["verify"]);
     require(await crypto.subtle.verify("RSASSA-PKCS1-v1_5",key,Uint8Array.from(atob(signature),x=>x.charCodeAt(0)),raw),"Signature rejected");
     const payload=JSON.parse(new TextDecoder().decode(raw));
     require(payload.is_test===true&&uuid(payload.id),"Non-test callback rejected");
     // Caller must match known provider ID and independently reconcile. Never trust callback alone.
     return {provider_id:payload.id,requires_reconciliation:true};
   }
 });
}
