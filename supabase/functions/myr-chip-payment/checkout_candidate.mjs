// Private candidate. No network calls or production entitlement mutations.
const catalog=Object.freeze({Starter:900,Pro:1900,Business:3900});
function require(ok,msg){if(!ok)throw new Error(msg)}
function uuid(x){return typeof x==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(x)}
function makePurchase(intent,brand,email){
 require(uuid(intent.id)&&uuid(brand),"Invalid identifier");
 require(intent.mode==="test"&&Object.hasOwn(catalog,intent.plan)&&intent.amount_sen===catalog[intent.plan],"Invalid test plan");
 require(typeof email==="string"&&email.length<=254&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email),"Invalid email");
 return {brand_id:brand,reference:"myr-test-"+intent.id,client:{email},purchase:{currency:"MYR",products:[{name:"MYR Invoice "+intent.plan+" monthly TEST",price:intent.amount_sen,quantity:1}]},success_redirect:"https://myrinvoice.com/#/billing",failure_redirect:"https://myrinvoice.com/#/billing",cancel_redirect:"https://myrinvoice.com/#/billing"};
}
function checkPurchase(intent,brand,purchase){
 require(uuid(intent.id)&&uuid(brand)&&uuid(purchase?.id),"Invalid identifier");
 require(intent.mode==="test"&&purchase.is_test===true,"Non-test purchase rejected");
 require(Object.hasOwn(catalog,intent.plan)&&intent.amount_sen===catalog[intent.plan],"Invalid expected amount");
 require(purchase.brand_id===brand&&purchase.reference==="myr-test-"+intent.id,"Brand or reference mismatch");
 require(purchase.purchase?.currency==="MYR"&&purchase.purchase.total===intent.amount_sen,"Amount or currency mismatch");
 if(intent.provider_id!=null)require(purchase.id===intent.provider_id,"Purchase ID mismatch");
 if(purchase.status==="created"){
   const u="https://gate.chip-in.asia/p/"+purchase.id+"/";
   require(purchase.checkout_url===u,"Unsafe checkout URL");
   return {status:"created",provider_id:purchase.id,checkout_url:u,entitlement_changed:false};
 }
 if(purchase.status==="paid"){
   require(purchase.marked_as_paid===false&&purchase.payment?.is_outgoing===false&&purchase.payment?.currency==="MYR"&&purchase.payment?.amount===intent.amount_sen,"Actual incoming payment mismatch");
   return {status:"verified_test_paid",provider_id:purchase.id,entitlement_changed:false};
 }
 return {status:"unsettled",provider_id:purchase.id,entitlement_changed:false};
}
export {makePurchase,checkPurchase,catalog};
