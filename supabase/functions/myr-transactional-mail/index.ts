import { catalog, render } from "./templates.ts";
import nodemailer from "npm:nodemailer@6.10.1";
// Dedicated VPS-to-email gateway. No database or Supabase Auth privileges.
// No tokens, recipient addresses, credentials or provider response bodies logged.
const origin = "https://myrinvoice.com";
const senderEmail = "no-reply@myrinvoice.com";
const testRecipient = "invoicesmyr@gmail.com";
const encoder = new TextEncoder();
const businessEvents:Record<string,string[]>={
 invoice:["company","reference","link_token"],
 quotation:["company","reference"],
 payment_confirmation:["company","reference","amount"],
 payment_reminder:["company","reference","due_date"],
 overdue:["company","reference","due_date"],
 team_invitation:["company","role"],
 subscription_expiry:["company","plan","renewal_date"],
 direct_erp_expiry:["expiry_date","reminder_stage"],
 lhdn_status:["company","reference","status"]
};
const templates = {
  verify_email: ["Verify your MYR Invoice email", "Verify your email", "Confirm your email address to create your MYR Invoice account.", "Verify email", "verify-email", "60 minutes"],
  reset_password: ["Reset your MYR Invoice password", "Reset your password", "Use the secure link below to choose a new password.", "Reset password", "reset-password", "20 minutes"],
  activate_import: ["Activate your MYR Invoice account", "Activate your account", "Your existing invoices and company information will remain in your account. Choose a new password to activate VPS sign-in.", "Activate account", "activate", "60 minutes"],
} as const;
function reply(status:number, data:Record<string,unknown>) {
  return Response.json(data,{status,headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
}
async function authorized(given:string, expected:string) {
  if (!/^[a-f0-9]{64}$/.test(expected) || !/^[a-f0-9]{64}$/.test(given)) return false;
  const a=new Uint8Array(await crypto.subtle.digest("SHA-256",encoder.encode(given)));
  const b=new Uint8Array(await crypto.subtle.digest("SHA-256",encoder.encode(expected)));
  let diff=0; for(let i=0;i<a.length;i++) diff|=a[i]^b[i]; return diff===0;
}
function renderLegacy(title:string, body:string, link:string, button:string, validity:string) {
  return `<!doctype html><html><body style="margin:0;background:#eef2fa;color:#17254a;font-family:Arial,sans-serif"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:32px 12px"><table role="presentation" width="100%" style="max-width:560px;background:#fff;border:1px solid #dce3ef;border-radius:18px;overflow:hidden"><tr><td style="padding:25px 30px;background:#17254a;color:#fff;font-size:22px;font-weight:bold">MYR<span style="color:#a5b4fc"> Invoice</span></td></tr><tr><td style="padding:30px"><h1 style="font-size:26px;margin:0 0 16px">${title}</h1><p style="line-height:1.65;color:#52617a">${body}</p>${link?'<p style="margin:28px 0"><a href="'+link+'" style="display:inline-block;padding:14px 24px;border-radius:9px;background:#3446df;color:#fff;text-decoration:none;font-weight:bold">'+button+'</a></p><p style="color:#52617a;font-size:13px">This secure link expires in '+validity+'. If you did not request it, ignore this email.</p>':''}<hr style="border:0;border-top:1px solid #e4e9f5;margin:26px 0"><p style="font-size:12px;color:#67738b">MYR Invoice · Automated notification<br>myrinvoice.com</p></td></tr></table></td></tr></table></body></html>`;
}

Deno.serve(async req=>{
  if(req.method!=="POST")return reply(405,{accepted:false});
  const secret=Deno.env.get("MYR_MAIL_SHARED_SECRET")||"";
  if(!await authorized(req.headers.get("X-MYR-Mail-Secret")||"",secret))return reply(401,{accepted:false});
  if((req.headers.get("Content-Type")||"").split(";")[0]!=="application/json")return reply(415,{accepted:false});
  const host=Deno.env.get("SMTP_HOST")||"";
  const port=Number(Deno.env.get("SMTP_PORT")||"");
  const user=Deno.env.get("SMTP_USER")||"";
  const pass=Deno.env.get("SMTP_PASS")||"";
  const from=Deno.env.get("SMTP_FROM")||"";
  const fromName=Deno.env.get("SMTP_FROM_NAME")||"";
  if(!/^[a-zA-Z0-9.-]+$/.test(host)||![465,587].includes(port)||!user||!pass||from!==senderEmail||fromName!=="MYR Invoice")
    return reply(503,{accepted:false,code:"SMTP_NOT_CONFIGURED"});
  let data;try{
    const reader=req.body?.getReader();if(!reader)return reply(400,{accepted:false});
    let size=0;const chunks=[];while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>2048){await reader.cancel();return reply(413,{accepted:false});}chunks.push(value);}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    data=JSON.parse(new TextDecoder().decode(bytes));
  }catch{return reply(400,{accepted:false});}
  if(!data||typeof data!=="object"||Array.isArray(data))return reply(400,{accepted:false});
  const event=data.event;
  let to:string,subject:string,html:string,text:string;
  const validRecipient=(v:unknown)=>typeof v==="string"&&v.length<=254&&/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(v);
  const welcome=["Welcome to MYR Invoice","Welcome aboard","Your email is verified. Sign in to create invoices and manage your business."] as const;
  if(["test_verify","test_reset","test_welcome"].includes(event)){
    if(Object.keys(data).length!==1)return reply(422,{accepted:false});
    to=testRecipient;
    const t=event==="test_verify"?templates.verify_email:event==="test_reset"?templates.reset_password:welcome;
    subject="[Preview] "+t[0];
    text=t[2]+"\n\nDelivery preview only. No account was created or changed.";
    html=renderLegacy(t[1],text,"","","");
  }else if(event==="test"){
    if(Object.keys(data).length!==1)return reply(422,{accepted:false});
    to=testRecipient;subject="MYR Invoice — Email connection test";
    text="Your MYR Invoice email delivery connection is being tested. No account action is requested.";
    html=renderLegacy("Email connection test",text,"","","");

  }else if(event==="test_template"){
    const key=data.template;
    if(typeof key!=="string"||!Object.hasOwn(catalog,key)||Object.keys(data).length!==2)return reply(422,{accepted:false});
    const t=catalog[key];to=testRecipient;subject="[Preview] "+t.subject;
    text=t.body+"\n\nDelivery preview only. No account was created or changed.";
    html=render(key,"",true);
  }else if(typeof event==="string"&&Object.hasOwn(businessEvents,event)){
    if(Deno.env.get("MYR_BUSINESS_MAIL_ENABLED")!=="true")return reply(503,{accepted:false,code:"BUSINESS_MAIL_NOT_RELEASED"});
    if(event==="direct_erp_expiry"&&Deno.env.get("MYR_DIRECT_EXPIRY_SANDBOX_MAIL_ENABLED")!=="true")return reply(503,{accepted:false,code:"DIRECT_EXPIRY_MAIL_NOT_RELEASED"});
    if(Object.keys(data).length!==3||!validRecipient(data.recipient)||!data.details||typeof data.details!=="object"||Array.isArray(data.details))return reply(422,{accepted:false});
    const allowed=businessEvents[event],details:Record<string,string>={};
    for(const [k,v] of Object.entries(data.details)){
      if(!allowed.includes(k)||typeof v!=="string"||v.length<1||v.length>160||/[\x00-\x1f\x7f]/.test(v))return reply(422,{accepted:false});
      details[k]=v;
    }
    if(!allowed.every(k=>Object.hasOwn(details,k)))return reply(422,{accepted:false});
    if(event==="direct_erp_expiry"){
      const date=details.expiry_date;
      if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(Date.parse(date))||new Date(date).toISOString().slice(0,10)!==date||!["30-day window","7-day window","1-day window","Expired"].includes(details.reminder_stage))return reply(422,{accepted:false});
    }
    // Capability tokens are not printed as details and only allow our own invoice portal.
    let link="";
    if(Object.hasOwn(details,"link_token")){
      if(!/^[A-Za-z0-9_-]{43}$/.test(details.link_token))return reply(422,{accepted:false});
      link=origin+"/#/v/"+details.link_token;delete details.link_token;
    }else if(["team_invitation","subscription_expiry","lhdn_status","direct_erp_expiry"].includes(event))link=origin;
    to=data.recipient;subject=catalog[event].subject;html=render(event,link,false,details);
    text=catalog[event].body+"\n\n"+Object.entries(details).map(([k,v])=>k.replaceAll("_"," ")+": "+v).join("\n")+(link?"\n\n"+link:"");
  }else if(event==="welcome"){
    if(Object.keys(data).length!==2||!validRecipient(data.recipient))return reply(422,{accepted:false});
    to=data.recipient;subject=catalog.welcome.subject;text=catalog.welcome.body+"\n\n"+origin;html=render("welcome",origin);
  }else{
    if(typeof event!=="string"||!["verify_email","reset_password"].includes(event)||!Object.hasOwn(templates,event)||Object.keys(data).length!==3)return reply(422,{accepted:false});
    if(!validRecipient(data.recipient)||typeof data.token!=="string"||!/^[A-Za-z0-9_-]{43}$/.test(data.token))return reply(422,{accepted:false});
    to=data.recipient;
    const t=templates[event as keyof typeof templates];subject=catalog[event].subject;
    const link=origin+"/#/auth/"+t[4]+"?token="+encodeURIComponent(data.token);
    html=render(event,link);
    text=catalog[event].body+"\n\n"+link+"\n\n"+catalog[event].notice+" Ignore if not requested.";
  }
  try{
    const transport=nodemailer.createTransport({
      host,port,secure:port===465,requireTLS:port===587,
      auth:{user,pass},tls:{servername:host,rejectUnauthorized:true,minVersion:"TLSv1.2"},
      connectionTimeout:10000,greetingTimeout:10000,socketTimeout:15000,
      logger:false,debug:false
    });
    const result=await transport.sendMail({from:{name:fromName,address:from},to,subject,html,text,disableFileAccess:true,disableUrlAccess:true});
    if(!Array.isArray(result.accepted)||result.accepted.length!==1||result.rejected?.length)
      return reply(502,{accepted:false,code:"SMTP_RECIPIENT_REJECTED"});
    // Test-only trace: SMTP queue identifier, never log raw SMTP replies.
    const trace=typeof result.response==="string"?result.response.match(/(?:queued as|id=)\s*([A-Za-z0-9._-]{1,100})/i)?.[1]:undefined;
    return reply(200,{accepted:true,...(typeof event==="string"&&event.startsWith("test")&&trace?{queue_id:trace}:{})});
  }catch(error){
    const e=error as {code?:string,responseCode?:number};
    const code=e.code==="EAUTH"?"SMTP_AUTH_FAILED":e.code==="ETIMEDOUT"?"SMTP_TIMEOUT":
      ["ESOCKET","ECONNECTION","EDNS","ETLS","ECONNREFUSED"].includes(e.code||"")?"SMTP_CONNECTION_FAILED":"SMTP_SEND_FAILED";
    return reply(502,{accepted:false,code,...(Number.isInteger(e.responseCode)?{smtp_status:e.responseCode}:{})});
  }
});
