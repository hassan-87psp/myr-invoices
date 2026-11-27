import assert from "node:assert/strict";
import {makePurchase,checkPurchase,catalog} from "./checkout_candidate.mjs";
import {buildTestTransport} from "./transport_candidate.mjs";
import {generateKeyPairSync,sign} from "node:crypto";
const id="a1111111-1111-4111-8111-111111111111",brand="b2222222-2222-4222-8222-222222222222",pid="c3333333-3333-4333-8333-333333333333";
const intent={id,plan:"Starter",amount_sen:900,mode:"test",state:"dispatching",provider_id:null};
const created={id:pid,brand_id:brand,reference:"myr-test-"+id,is_test:true,purchase:{currency:"MYR",total:900},status:"created",checkout_url:"https://gate.chip-in.asia/p/"+pid+"/"};
const paid={...created,status:"paid",marked_as_paid:false,payment:{amount:900,currency:"MYR",is_outgoing:false}};
for(const [plan,amount_sen] of Object.entries(catalog)){
  const body=makePurchase({...intent,plan,amount_sen},brand,"test@example.com");
  assert.equal(body.purchase.products[0].price,amount_sen);
}
assert.equal(checkPurchase(intent,brand,created).status,"created");
assert.equal(checkPurchase({...intent,provider_id:pid},brand,paid).status,"verified_test_paid");
assert.equal(checkPurchase(intent,brand,paid).entitlement_changed,false);
for(const bad of [{is_test:false},{is_test:undefined},{reference:"bad"},{brand_id:id},{marked_as_paid:true},{payment:{...paid.payment,amount:899}},{payment:{...paid.payment,currency:"USD"}},{payment:{...paid.payment,is_outgoing:true}},{purchase:{total:900,currency:"USD"}}])assert.throws(()=>checkPurchase(intent,brand,{...paid,...bad}));
assert.throws(()=>checkPurchase(intent,brand,{...created,checkout_url:"https://example.com/"}));
assert.throws(()=>makePurchase({...intent,mode:"live"},brand,"test@example.com"));
assert.throws(()=>makePurchase({...intent,amount_sen:1},brand,"test@example.com"));
assert.throws(()=>buildTestTransport({mode:"live",testCredentialVerified:true,brand,key:"mock-secret"}));
assert.throws(()=>buildTestTransport({mode:"test",testCredentialVerified:false,brand,key:"mock-secret"}));
const {privateKey,publicKey}=generateKeyPairSync("rsa",{modulusLength:2048});
const pem=publicKey.export({type:"spki",format:"pem"});
const calls=[];
const transport=buildTestTransport({mode:"test",testCredentialVerified:true,brand,key:"mock-secret"},async(url,options)=>{
  calls.push([url,options.method]);
  assert.equal(options.redirect,"error");
  assert.equal(options.headers.Authorization,"Bearer mock-secret");
  if(url.endsWith("/public_key/"))return new Response(JSON.stringify(pem),{status:200});
  if(options.method==="POST"){assert.equal(JSON.parse(options.body).purchase.products[0].price,900);return Response.json(created);}
  return Response.json(paid);
});
assert.equal((await transport.create(intent,"test@example.com")).provider_id,pid);
assert.equal((await transport.reconcile({...intent,provider_id:pid})).status,"verified_test_paid");
await assert.rejects(()=>transport.create({...intent,state:"reserved"},"test@example.com"));
const raw=new TextEncoder().encode(JSON.stringify(paid));
const sig=sign("sha256",raw,privateKey).toString("base64");
assert.equal((await transport.verifySuccessCallback(raw,sig)).provider_id,pid);
const tampered=new TextEncoder().encode(JSON.stringify({...paid,reference:"wrong"}));
await assert.rejects(()=>transport.verifySuccessCallback(tampered,sig));
assert.equal(calls.filter(x=>x[1]==="POST").length,1);
console.log("MYR_CHIP_PROTOCOL_OFFLINE_OK");
