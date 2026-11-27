// Operator-only, read-only CHIP connectivity probe. No purchase or billing mutation.
const reply = (status: number, data: Record<string, unknown>) =>
  new Response(JSON.stringify(data), {status, headers: {"Content-Type":"application/json","Cache-Control":"no-store"}});
const eq = async (a: string,b: string) => {
  const digest = (x:string) => crypto.subtle.digest("SHA-256",new TextEncoder().encode(x));
  const x = new Uint8Array(await digest(a)), y = new Uint8Array(await digest(b));
  let diff=0; for(let i=0;i<x.length;i++) diff |= x[i]^y[i]; return diff===0;
};
Deno.serve(async (req: Request) => {
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = req.headers.get("authorization") || "";
  if (!service || supplied.length>4096 || !await eq(supplied,"Bearer "+service)) return reply(401,{ok:false,error:"operator_only"});
  if(req.method!=="POST") return reply(405,{ok:false,error:"method_not_allowed"});
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