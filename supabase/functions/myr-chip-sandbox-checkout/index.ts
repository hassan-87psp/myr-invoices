// Private manual sandbox smoke test only. Never mounted to the customer billing API.
// Do not automatically retry purchase creation. No receipt, recurring charge, or subscription mutation.
const reply=(status:number,body:Record<string,unknown>)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
const uuid=(v:unknown):v is string=>typeof v==="string"&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const equal=async(a:string,b:string)=>{
 const digest=(x:string)=>crypto.subtle.digest("SHA-256",new TextEncoder().encode(x));
 const x=new Uint8Array(await digest(a)),y=new Uint8Array(await digest(b));
 let diff=0;for(let i=0;i<x.length;i++)diff|=x[i]^y[i];return diff===0;
};
Deno.serve(async(req:Request)=>{
 if(req.method!=="POST")return reply(405,{ok:false});
 const secret=Deno.env.get("CHIP_OPERATOR_SECRET")||"";
 const auth=req.headers.get("x-chip-operator-secret")||"";
 if(!/^[a-f0-9]{64}$/i.test(secret)||auth.length!==64||!await equal(auth,secret))return reply(401,{ok:false,error:"operator_only"});
 const key=Deno.env.get("CHIP_TEST_API_KEY")||"";
 const brand=Deno.env.get("CHIP_BRAND_ID")||"";
 if(Deno.env.get("CHIP_MODE")!=="test"||!uuid(brand)||!(/^[!-~]{1,1024}$/.test(key))||/^https?:/i.test(key))return reply(503,{ok:false,error:"invalid_test_configuration"});
 let body;
 try{const raw=await req.text();if(raw.length>1024)throw Error();body=JSON.parse(raw);}catch{return reply(400,{ok:false,error:"invalid_request"});}
 if(!body||typeof body!=="object")return reply(400,{ok:false,error:"invalid_request"});
 const base="https://gate.chip-in.asia/api/v1/";
 const headers={Authorization:"Bearer "+key,Accept:"application/json","Content-Type":"application/json"};
 const create=body.action==="create_test"&&body.confirm==="I_VERIFIED_CHIP_TEST_KEY"&&Object.keys(body).length===2;
 const lookup=body.action==="verify_test"&&uuid(body.purchase_id)&&uuid(body.intent_id)&&Object.keys(body).length===3;
 if(!create&&!lookup)return reply(400,{ok:false,error:"invalid_action"});
 const intent=create?crypto.randomUUID():body.intent_id;
 const reference="myr-test-"+intent;
 try{
   const res=await fetch(base+(create?"purchases/":"purchases/"+body.purchase_id+"/"),{
    method:create?"POST":"GET",headers,redirect:"error",signal:AbortSignal.timeout(15000),
    ...(create?{body:JSON.stringify({brand_id:brand,reference,client:{email:"test@example.com"},purchase:{currency:"MYR",products:[{name:"MYR Invoice Starter TEST",price:900,quantity:1}]},send_receipt:false,force_recurring:false,success_redirect:"https://myrinvoice.com/",failure_redirect:"https://myrinvoice.com/",cancel_redirect:"https://myrinvoice.com/"})}:{})
   });
   if(!res.ok){await res.body?.cancel();return reply(502,{ok:false,provider_http:res.status,intent_id:intent,do_not_retry_create:create});}
   const p=await res.json();
   if(p.is_test!==true||p.brand_id!==brand||p.reference!==reference||p.purchase?.currency!=="MYR"||p.purchase?.total!==900||!uuid(p.id)||(!create&&p.id!==body.purchase_id))
     return reply(502,{ok:false,error:"test_purchase_verification_failed",intent_id:intent,do_not_retry_create:create});
   if(create){
    const expected="https://gate.chip-in.asia/p/"+p.id+"/";
    if(p.status!=="created"||p.checkout_url!==expected)return reply(502,{ok:false,error:"unexpected_checkout",intent_id:intent,do_not_retry_create:true});
    return reply(200,{ok:true,is_test:true,amount_sen:900,intent_id:intent,purchase_id:p.id,checkout_url:expected,status:"created",entitlement_changed:false});
   }
   if(p.status==="paid"&&(p.marked_as_paid!==false||p.payment?.is_outgoing!==false||p.payment?.currency!=="MYR"||p.payment?.amount!==900))return reply(502,{ok:false,error:"paid_amount_mismatch",entitlement_changed:false});
   return reply(200,{ok:true,is_test:true,amount_sen:900,purchase_id:p.id,status:typeof p.status==="string"&&/^[a-z_]{1,32}$/.test(p.status)?p.status:"unknown",verified_test_paid:p.status==="paid",entitlement_changed:false});
 }catch{return reply(502,{ok:false,error:"provider_outcome_unknown",intent_id:intent,do_not_retry_create:create});}
});
