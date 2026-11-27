// Private VPS-to-edge connection foundation. No document submission or database access.
const bases = { sandbox: "https://preprod-api.myinvois.hasil.gov.my", production: "https://api.myinvois.hasil.gov.my" } as const;
type Env = keyof typeof bases;
type Entry = { token: string; expires: number };
const enc = new TextEncoder();
function json(status: number, data: object) {
  return new Response(JSON.stringify(data), { status, headers: {"Content-Type":"application/json", "Cache-Control":"no-store"} });
}
async function authorized(expected: string, provided: string) {
  if (!/^[a-f0-9]{64}$/.test(expected) || !/^[a-f0-9]{64}$/.test(provided)) return false;
  const alg = {name:"HMAC", hash:"SHA-256"};
  const key = await crypto.subtle.importKey("raw", enc.encode(expected), alg, false, ["sign"]);
  const other = await crypto.subtle.importKey("raw", enc.encode(provided), alg, false, ["verify"]);
  const message = enc.encode("myr-lhdn-connector-v1");
  const signature = await crypto.subtle.sign("HMAC", key, message);
  return crypto.subtle.verify("HMAC", other, signature, message);
}
export function createHandler(env: (name:string)=>string|undefined, send: typeof fetch = fetch) {
  // Isolate-local only. A distributed limiter/cache is required before public rollout.
  const cache = new Map<string,Entry>();
  const inflight = new Map<string,Promise<Entry>>();
  const calls = new Map<Env,number[]>();
  const backoff = new Map<Env,number>();
  // Sandbox only. Cache identity confirmation per tenant and credential context.
  const validated = new Map<string,number>();
  const validating = new Set<string>();
  let validationCalls:number[]=[];
  let validationBackoff=0;
  async function validateSelf(key:string, entry:Entry, tin:string, brn:string):Promise<Response> {
    const now=Date.now();
    for(const [k,v] of validated) if(v<=now) validated.delete(k);
    if((validated.get(key)||0)>now) return json(200,{ok:true,verification:"cached_tin",submission_enabled:false});
    if(validationBackoff>now || validating.has(key)) return json(429,{ok:false,code:"rate_limited"});
    validationCalls=validationCalls.filter(t=>now-t<60000);
    if(validationCalls.length>=4) return json(429,{ok:false,code:"rate_limited"});
    validationCalls.push(now);
    validating.add(key);
    try {
      const url=bases.sandbox+"/api/v1.0/taxpayer/validate/"+encodeURIComponent(tin)+"?"+new URLSearchParams({idType:"BRN",idValue:brn});
      const response=await send(url,{method:"GET",redirect:"error",signal:AbortSignal.timeout(15000),headers:{Authorization:"Bearer "+entry.token,Accept:"application/json"}});
      await response.body?.cancel();
      if(response.status===200){
        if(validated.size>=256)validated.delete(validated.keys().next().value!);
        validated.set(key,Math.min(entry.expires,now+300000));
        return json(200,{ok:true,verification:"provider_tin",submission_enabled:false});
      }
      if(response.status===401){cache.delete(key.split(":")[0]);return json(401,{ok:false,code:"authentication_required"});}
      if(response.status===429){
        const header=response.headers.get("Retry-After");
        const seconds=header&&/^\d+$/.test(header)?Number(header):NaN;
        const until=header?Date.parse(header):NaN;
        validationBackoff=now+Math.max(60000,Number.isFinite(seconds)?seconds*1000:Number.isFinite(until)?until-now:60000);
        return json(429,{ok:false,code:"rate_limited"});
      }
      const code=({400:"invalid_input",403:"permission_denied",404:"identity_not_matched"} as Record<number,string>)[response.status];
      return json(code?response.status:502,{ok:false,code:code||"provider_unavailable"});
    } catch {return json(502,{ok:false,code:"provider_unavailable"});}
    finally {validating.delete(key);}
  }
  async function login(environment:Env, target:string, id:string, secret:string):Promise<Entry> {
    const now=Date.now();
    if ((backoff.get(environment)||0)>now) throw new Error("rate_limited");
    const recent=(calls.get(environment)||[]).filter(t=>now-t<60000);
    // Conservative per-isolate ceiling; gateway also enforces limits.
    if (recent.length>=4) throw new Error("rate_limited");
    calls.set(environment,[...recent,now]);
    const res=await send(bases[environment]+"/connect/token", {
      method:"POST", redirect:"error", signal:AbortSignal.timeout(20000),
      headers:{"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json","onbehalfof":target},
      body:new URLSearchParams({client_id:id,client_secret:secret,grant_type:"client_credentials",scope:"InvoicingAPI"})
    });
    if (!res.ok) {
      await res.body?.cancel();
      if (res.status===429) {
        const retry=Number(res.headers.get("Retry-After"));
        backoff.set(environment,now+Math.max(60000,Math.min(3600000,Number.isFinite(retry)?retry*1000:60000)));
        throw new Error("rate_limited");
      }
      if (res.status===400 || res.status===401 || res.status===403) throw new Error("authorization_or_credentials_rejected");
      throw new Error("provider_unavailable");
    }
    const data=await res.json();
    if (res.status!==200 || typeof data?.access_token!=="string" || !data.access_token || data.access_token.length>32768 ||
        String(data.token_type).toLowerCase()!=="bearer" || !Number.isInteger(data.expires_in) || data.expires_in<=60 || data.expires_in>86400)
      throw new Error("invalid_provider_response");
    return {token:data.access_token,expires:now+data.expires_in*1000};
  }
  return async (req:Request):Promise<Response> => {
    try {
      const expected=env("MYR_LHDN_BRIDGE_SECRET")||"";
      const provided=(req.headers.get("Authorization")||"").replace(/^Bearer /,"");
      if (!await authorized(expected,provided)) return json(401,{ok:false,code:"unauthorized"});
      if (req.method!=="POST") return json(405,{ok:false,code:"method_not_allowed"});
      if (!req.headers.get("Content-Type")?.toLowerCase().startsWith("application/json")) return json(415,{ok:false,code:"json_required"});
      // Bounded body; never log taxpayer identity, provider response or tokens.
      const reader=req.body?.getReader();
      if (!reader) return json(400,{ok:false,code:"invalid_request"});
      const chunks:Uint8Array[]=[]; let size=0;
      for (;;) {
        const part=await reader.read(); if(part.done) break;
        size+=part.value.byteLength;
        if(size>2048){await reader.cancel();return json(413,{ok:false,code:"request_too_large"});}
        chunks.push(part.value);
      }
      let body;
      try { body=JSON.parse(await new Blob(chunks).text()); } catch { return json(400,{ok:false,code:"invalid_request"}); }
      if (!body || typeof body!=="object" || Array.isArray(body)) return json(400,{ok:false,code:"invalid_request"});
      if (!["sandbox","production"].includes(body.environment)) return json(400,{ok:false,code:"invalid_environment"});
      const environment=body.environment as Env;
      const prefix=environment==="production"?"MYR_LHDN_PROD_":"MYR_LHDN_SANDBOX_";
      const id=env(prefix+"CLIENT_ID")||"", secret=env(prefix+"CLIENT_SECRET")||"";
      const enabled=env(prefix+"CONNECTION_CHECK_ENABLED")==="true";
      if (body.action==="configuration_status" && Object.keys(body).every(k=>["action","environment"].includes(k)))
        return json(200,{ok:true,configured:!!id&&!!secret,connection_check_enabled:enabled,submission_enabled:false});
      const validate=body.action==="validate_self_tin";
      const allowed=validate?["action","environment","tenant_id","taxpayer","brn"]:["action","environment","tenant_id","taxpayer"];
      if ((!validate&&body.action!=="check_connection") || !Object.keys(body).every(k=>allowed.includes(k))) return json(400,{ok:false,code:"invalid_action"});
      if(validate && (environment!=="sandbox" || env("MYR_LHDN_SANDBOX_TIN_VALIDATION_ENABLED")!=="true"))
        return json(503,{ok:false,code:"tin_validation_disabled"});
      if (!enabled || !id || !secret) return json(503,{ok:false,code:"connection_check_disabled"});
      if (typeof body.tenant_id!=="string" || !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(body.tenant_id) ||
          typeof body.taxpayer!=="string" || !/^[A-Z]{1,3}[0-9]{1,20}(?::[A-Z0-9-]{1,40})?$/.test(body.taxpayer))
        return json(400,{ok:false,code:"invalid_taxpayer_identity"});
      // Trusted VPS must derive tenant and taxpayer from its authorized owner record.
      if(validate && (typeof body.brn!=="string" || !/^[A-Z0-9-]{1,40}$/.test(body.brn) ||
        (body.taxpayer.includes(":") && body.taxpayer.split(":")[1]!==body.brn)))
        return json(400,{ok:false,code:"invalid_taxpayer_identity"});
      const digest=await crypto.subtle.digest("SHA-256",enc.encode(JSON.stringify([environment,id,secret,body.tenant_id,body.taxpayer])));
      const key=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
      const now=Date.now();
      for(const [k,v] of cache) if(v.expires<=now+60000)cache.delete(k);
      const cached=cache.get(key);
      const validationKey=key+":"+String(body.brn||"");
      if(cached) return validate?await validateSelf(validationKey,cached,body.taxpayer.split(":")[0],body.brn):json(200,{ok:true,verification:"cached",expires_in:Math.floor((cached.expires-now)/1000),submission_enabled:false});
      let pending=inflight.get(key);
      if(!pending){
        pending=login(environment,body.taxpayer,id,secret);
        inflight.set(key,pending);
      }
      try {
        const entry=await pending;
        if(cache.size>=256)cache.delete(cache.keys().next().value!);
        cache.set(key,entry);
        if(validate)return await validateSelf(validationKey,entry,body.taxpayer.split(":")[0],body.brn);
        return json(200,{ok:true,verification:"provider_login",expires_in:Math.floor((entry.expires-Date.now())/1000),submission_enabled:false});
      } catch (err) {
        const code=err instanceof Error && ["rate_limited","authorization_or_credentials_rejected","invalid_provider_response","provider_unavailable"].includes(err.message)?err.message:"provider_unavailable";
        return json(code==="rate_limited"?429:code==="authorization_or_credentials_rejected"?422:502,{ok:false,code});
      } finally { if(inflight.get(key)===pending)inflight.delete(key); }
    } catch { return json(500,{ok:false,code:"connector_error"}); }
  };
}
