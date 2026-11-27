// Candidate entrypoint for a separate myr-lhdn-sandbox-dispatch Edge Function.
// Do not deploy until the review-only fence has passed isolated privilege tests.
import {createDispatchCandidate} from "./sandbox_dispatch_bridge_candidate.ts";
const env=(name:string)=>Deno.env.get(name);
const BASE="https://nynghaleoaqilewmhbdi.supabase.co";
const endpoint=BASE+"/rest/v1/myr_lhdn_sandbox_dispatch_fence";
Deno.serve(createDispatchCandidate(env,async grant=>{
  if(env("SUPABASE_URL")!==BASE)return false;
  const key=env("SUPABASE_SERVICE_ROLE_KEY");
  if(!key)return false;
  try{
    const r=await fetch(endpoint,{method:"POST",redirect:"error",signal:AbortSignal.timeout(10000),
       headers:{apikey:key,Authorization:"Bearer "+key,"Content-Type":"application/json",Prefer:"return=minimal"},
       body:JSON.stringify(grant)});
    await r.body?.cancel();
    return r.status===201;
  }catch{return false;}
}));
