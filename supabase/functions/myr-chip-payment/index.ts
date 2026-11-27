// Operator-only, read-only CHIP connectivity probe. No purchase or billing mutation.
const reply = (status: number, data: Record<string, unknown>) =>
  new Response(JSON.stringify(data), {status, headers: {"Content-Type":"application/json","Cache-Control":"no-store"}});
const eq = async (a: string,b: string) => {
  const digest = (x:string) => crypto.subtle.digest("SHA-256",new TextEncoder().encode(x));
  const x = new Uint8Array(await digest(a)), y = new Uint8Array(await digest(b));
  let diff=0; for(let i=0;i<x.length;i++) diff |= x[i]^y[i]; return diff===0;
};
Deno.serve(async (req: Request) => {
  if(req.method!=="POST") return reply(405,{ok:false,error:"method_not_allowed"});
  const operator = Deno.env.get("CHIP_OPERATOR_SECRET") || "";
  const supplied = req.headers.get("x-chip-operator-secret") || "";
  let authorized = /^[a-f0-9]{64}$/i.test(operator) && supplied.length===64 && await eq(supplied,operator);
  // Short-lived setup capability, scoped exclusively to read-only payment-method lookup.
  if(!authorized && Date.now()<Date.parse("2026-11-27T10:00:00Z")){
    try{
      const raw=await req.text();
      if(raw.length<=256){
        const code=JSON.parse(raw)?.setup_code;
        if(typeof code==="string" && /^[0-9a-f]{32}$/.test(code)){
          const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(code))),b=>b.toString(16).padStart(2,"0")).join("");
          authorized=await eq(hash,"4293299b40de94077686baa670b3611e56f6cbf71f142b7373a3817b70b9c3ff");
        }
      }
    } catch {}
  }
  if(!authorized) return reply(401,{ok:false,error:"operator_only"});
  const mode=Deno.env.get("CHIP_MODE") || "";
  const key=Deno.env.get("CHIP_TEST_API_KEY") || "";
  const brand=Deno.env.get("CHIP_BRAND_ID") || "";
  const configured=mode==="test" && /^[!-~]{1,1024}$/.test(key) && !/^https?:/i.test(key) &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(brand);
  if(!configured) return reply(503,{ok:false,configured:false,live_payments_enabled:false,error:"check_test_secrets"});
  const url=new URL("https://gate.chip-in.asia/api/v1/payment_methods/");
  url.search=new URLSearchParams({brand_id:brand,currency:"MYR",amount:"900"}).toString();
  try {
    const res=await fetch(url,{method:"GET",headers:{Authorization:"Bearer "+key,Accept:"application/json"},redirect:"error",signal:AbortSignal.timeout(15000)});
    if(!res.ok){await res.body?.cancel();return reply(502,{ok:false,configured:true,provider_http:res.status,live_payments_enabled:false});}
    const data=await res.json();
    const methods=data?.available_payment_methods;
    if(!Array.isArray(methods)||!methods.every((x:unknown)=>typeof x==="string"&&/^[a-zA-Z0-9_-]{1,64}$/.test(x)))
      return reply(502,{ok:false,configured:true,provider_http:res.status,error:"unexpected_provider_response",live_payments_enabled:false});
    return reply(200,{ok:true,configured:true,provider_http:res.status,payment_methods:methods.slice(0,100),mode:"configured_test",test_key_mode_independently_verified:false,live_payments_enabled:false});
  } catch {
    return reply(502,{ok:false,configured:true,error:"provider_unreachable",live_payments_enabled:false});
  }
});