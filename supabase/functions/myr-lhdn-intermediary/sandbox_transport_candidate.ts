// Sandbox provider transport candidate. Not imported by the deployed handler.
// Only a trusted server-side worker may supply a token and durable reservation.
// No arbitrary URLs, production host, automatic write retry, or raw error forwarding.
const BASE="https://preprod-api.myinvois.hasil.gov.my";
const MAX=250000;
const enc=new TextEncoder();
const id=(v:unknown):v is string=>typeof v==="string"&&/^[A-Za-z0-9]{26}$/.test(v);
const tin=(v:unknown):v is string=>typeof v==="string"&&/^[A-Z]{1,3}[0-9]{1,13}$/.test(v);
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==="object"&&!Array.isArray(v);
function check(ok:unknown):asserts ok {if(!ok)throw new Error("invalid_transport_input");}
type Grant={tenant_id:string;taxpayer:string;document_hash:string;code_number:string};
type Context={enabled:boolean;environment:string;tenant_id:string;taxpayer:string;token:string;grant:Grant};
function bound(c:Context){
  check(c.enabled===true&&c.environment==="sandbox");
  check(/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(c.tenant_id));
  check(tin(c.taxpayer));
  check(c.grant?.tenant_id===c.tenant_id&&c.grant.taxpayer===c.taxpayer);
  check(/^[a-f0-9]{64}$/.test(c.grant.document_hash)&&typeof c.grant.code_number==="string"&&c.grant.code_number.length>0&&c.grant.code_number.length<=50);
  check(typeof c.token==="string"&&c.token.length>0&&c.token.length<=32768&&!/[\s\x00-\x1f]/.test(c.token));
}
async function read(res:Response){
  const reader=res.body?.getReader();check(reader);
  const bytes=new Uint8Array(65536);let size=0;
  for(;;){const p=await reader.read();if(p.done)break;
    if(p.value.byteLength>bytes.length-size){await reader.cancel();throw new Error("provider_response_too_large");}
    bytes.set(p.value,size);size+=p.value.byteLength;
  }
  return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes.subarray(0,size)));
}
function wait(res:Response){
  const v=res.headers.get("Retry-After");if(v&&/^\d{1,12}$/.test(v))return Math.max(5,Number(v));
  const d=v?Date.parse(v):NaN;return Number.isFinite(d)?Math.max(5,Math.ceil((d-Date.now())/1000)):60;
}
function headers(c:Context){return {Authorization:"Bearer "+c.token,Accept:"application/json"};}
async function validateEnvelope(c:Context,payload:unknown){
  check(object(payload)&&Object.keys(payload).length===1&&Array.isArray(payload.documents)&&payload.documents.length===1);
  const d=payload.documents[0];check(object(d)&&Object.keys(d).sort().join(",")==="codeNumber,document,documentHash,format");
  check(d.format==="JSON"&&d.codeNumber===c.grant.code_number&&d.documentHash===c.grant.document_hash);
  check(typeof d.document==="string"&&d.document.length<=Math.ceil(MAX/3)*4&&/^[A-Za-z0-9+/]+={0,2}$/.test(d.document));
  const raw=Uint8Array.from(atob(d.document),x=>x.charCodeAt(0));check(raw.length>0&&raw.length<=MAX);
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",raw)),x=>x.toString(16).padStart(2,"0")).join("");
  check(hash===c.grant.document_hash);
  const root=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(raw));
  const inv=root?.Invoice;
  check(Array.isArray(inv)&&inv.length===1&&inv[0]?.ID?.length===1&&inv[0].ID[0]._===c.grant.code_number);
  const type=inv[0]?.InvoiceTypeCode;
  check(Array.isArray(type)&&type.length===1&&type[0]._==="01"&&type[0].listVersionID==="1.0");
  check(!inv[0].UBLExtensions&&!inv[0].Signature);
  const ids=inv[0]?.AccountingSupplierParty?.[0]?.Party?.[0]?.PartyIdentification;
  check(Array.isArray(ids));
  const matches=ids.flatMap((x:Record<string,unknown>)=>Array.isArray(x?.ID)?x.ID:[]).filter((x:Record<string,unknown>)=>x?.schemeID==="TIN");
  check(matches.length===1&&matches[0]._===c.taxpayer);
  return {documents:[{format:"JSON",document:d.document,documentHash:hash,codeNumber:c.grant.code_number}]};
}
export async function submitSandbox(c:Context,payload:unknown,send:typeof fetch){
  bound(c);const envelope=await validateEnvelope(c,payload);
  try{
    const r=await send(BASE+"/api/v1.0/documentsubmissions/",{method:"POST",headers:{...headers(c),"Content-Type":"application/json"},
      body:JSON.stringify(envelope),redirect:"error",signal:AbortSignal.timeout(25000)});
    if(r.status!==202){await r.body?.cancel();return {state:"outcome_unknown",http_status:r.status,retry_after:wait(r),retry_enabled:false};}
    const data=await read(r);check(object(data));
    const uid=data.submissionUID??data.submissionUid;
    check(id(uid)&&(!(data.submissionUID&&data.submissionUid)||data.submissionUID===data.submissionUid));
    check(Array.isArray(data.acceptedDocuments)&&data.acceptedDocuments.length===1&&Array.isArray(data.rejectedDocuments)&&data.rejectedDocuments.length===0);
    const a=data.acceptedDocuments[0];check(object(a)&&id(a.uuid)&&a.invoiceCodeNumber===c.grant.code_number);
    return {state:"accepted",http_status:202,receipt:{submissionUID:uid,acceptedDocuments:[{uuid:a.uuid,invoiceCodeNumber:c.grant.code_number}],rejectedDocuments:[]}};
  }catch{return {state:"outcome_unknown",retry_enabled:false};}
}
export async function pollSandbox(c:Context,submission:unknown,uuid:unknown,send:typeof fetch){
  bound(c);check(id(submission)&&id(uuid));
  try{
    const r=await send(BASE+"/api/v1.0/documentsubmissions/"+submission+"?pageNo=1&pageSize=10",
      {method:"GET",headers:headers(c),redirect:"error",signal:AbortSignal.timeout(15000)});
    if(r.status!==200){await r.body?.cancel();return {state:"poll_unavailable",http_status:r.status,retry_after:wait(r)};}
    const d=await read(r);check(object(d)&&d.submissionUid===submission&&d.documentCount===1&&Array.isArray(d.documentSummary)&&d.documentSummary.length===1);
    const x=d.documentSummary[0];check(object(x)&&x.uuid===uuid&&x.submissionUid===submission&&x.internalId===c.grant.code_number&&x.issuerTin===c.taxpayer);
    check(["Submitted","Valid","Invalid","Cancelled"].includes(String(x.status)));
    const result:Record<string,unknown>={uuid,submissionUid:submission,internalId:c.grant.code_number,issuerTin:c.taxpayer,status:x.status};
    if(x.status==="Valid"){
      check(typeof x.longId==="string"&&/^[A-Za-z0-9_-]{1,256}$/.test(x.longId)&&typeof x.dateTimeValidated==="string"&&/Z$/.test(x.dateTimeValidated)&&Number.isFinite(Date.parse(x.dateTimeValidated)));
      result.longId=x.longId;result.dateTimeValidated=x.dateTimeValidated;
    }
    return {state:"polled",http_status:200,response:{submissionUid:submission,documentSummary:[result]}};
  }catch{return {state:"poll_unavailable"};}
}
