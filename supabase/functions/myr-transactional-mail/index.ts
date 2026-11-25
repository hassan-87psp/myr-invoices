// Dedicated VPS-to-email gateway. No database or Supabase Auth privileges.
// No tokens, recipient addresses, credentials or provider response bodies logged.
const origin = "https://myrinvoice.com";
const sender = "MYR Invoice <no-reply@myrinvoice.com>";
const testRecipient = "invoicesmyr@gmail.com";
const encoder = new TextEncoder();
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
function render(title:string, body:string, link:string, button:string, validity:string) {
  return `<!doctype html><html><body style="margin:0;background:#eef2fa;color:#17254a;font-family:Arial,sans-serif"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:32px 12px"><table role="presentation" width="100%" style="max-width:560px;background:#fff;border:1px solid #dce3ef;border-radius:18px;overflow:hidden"><tr><td style="padding:25px 30px;background:#17254a;color:#fff;font-size:22px;font-weight:bold">MYR<span style="color:#a5b4fc"> Invoice</span></td></tr><tr><td style="padding:30px"><h1 style="font-size:26px;margin:0 0 16px">${title}</h1><p style="line-height:1.65;color:#52617a">${body}</p>${link?'<p style="margin:28px 0"><a href="'+link+'" style="display:inline-block;padding:14px 24px;border-radius:9px;background:#3446df;color:#fff;text-decoration:none;font-weight:bold">'+button+'</a></p><p style="color:#52617a;font-size:13px">This secure link expires in '+validity+'. If you did not request it, ignore this email.</p>':''}<hr style="border:0;border-top:1px solid #e4e9f5;margin:26px 0"><p style="font-size:12px;color:#67738b">MYR Invoice · Automated notification<br>myrinvoice.com</p></td></tr></table></td></tr></table></body></html>`;
}
Deno.serve(async req=>{
  if(req.method!=="POST")return reply(405,{accepted:false});
  const secret=Deno.env.get("MYR_MAIL_SHARED_SECRET")||"";
  if(!await authorized(req.headers.get("X-MYR-Mail-Secret")||"",secret))return reply(401,{accepted:false});
  if((req.headers.get("Content-Type")||"").split(";")[0]!=="application/json")return reply(415,{accepted:false});
  const provider=Deno.env.get("MYR_RESEND_API_KEY")||"";
  if(!provider)return reply(503,{accepted:false,code:"MAIL_PROVIDER_NOT_CONFIGURED"});
  let data;try{
    const reader=req.body?.getReader();if(!reader)return reply(400,{accepted:false});
    let size=0;const chunks=[];while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>2048){await reader.cancel();return reply(413,{accepted:false});}chunks.push(value);}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    data=JSON.parse(new TextDecoder().decode(bytes));
  }catch{return reply(400,{accepted:false});}
  if(!data||typeof data!=="object"||Array.isArray(data))return reply(400,{accepted:false});
  const event=data.event;
  let to:string,subject:string,html:string,text:string;
  if(event==="test"){
    if(Object.keys(data).length!==1)return reply(422,{accepted:false});
    to=testRecipient;subject="MYR Invoice — Email connection test";
    text="Your MYR Invoice email delivery connection is being tested. No account action is requested.";
    html=render("Email connection test",text,"","","");
  }else{
    if(Deno.env.get("MYR_ACCOUNT_MAIL_ENABLED")!=="true")return reply(503,{accepted:false,code:"ACCOUNT_MAIL_NOT_RELEASED"});
    if(!Object.prototype.hasOwnProperty.call(templates,event)||Object.keys(data).length!==3)return reply(422,{accepted:false});
    if(typeof data.recipient!=="string"||data.recipient.length>254||!/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(data.recipient)||typeof data.token!=="string"||!/^[A-Za-z0-9_-]{43}$/.test(data.token))return reply(422,{accepted:false});
    to=data.recipient;
    const t=templates[event as keyof typeof templates];subject=t[0];
    const link=origin+"/#/auth/"+t[4]+"?token="+encodeURIComponent(data.token);
    html=render(t[1],t[2],link,t[3],t[5]);
    text=t[2]+"\n\n"+link+"\n\nExpires in "+t[5]+". Ignore if not requested.";
  }
  try{
    const res=await fetch("https://api.resend.com/emails",{method:"POST",redirect:"error",signal:AbortSignal.timeout(10000),headers:{"Authorization":"Bearer "+provider,"Content-Type":"application/json"},body:JSON.stringify({from:sender,to:[to],subject,html,text})});
    if(!res.ok){await res.body?.cancel();return reply(502,{accepted:false,code:"PROVIDER_REJECTED",provider_status:res.status});}
    const result=await res.json();if(typeof result.id!=="string")return reply(502,{accepted:false,code:"INVALID_PROVIDER_RESPONSE"});
    return reply(200,{accepted:true});
  }catch{return reply(502,{accepted:false,code:"PROVIDER_UNAVAILABLE"});}
});