from build_hybrid_preview import once
JS=r"""
let MYR_CENTRAL_LHDN={};
function myrCentralAdmin(d){
 const x=d.central_lhdn||{};
 const sb=x.sandbox||{};
 const flag=v=>v===true?'Enabled':v===false?'Disabled':'Unknown';
 const sandboxEntries=[['Environment','Sandbox (pre-production)'],['Secure bridge',sb.bridge_reachable===true?'Connected':'Unavailable / not checked'],['Central credentials',sb.credentials_configured===true?'Configured':sb.credentials_configured===false?'Not configured':'Unknown'],['Connection checks',sb.bridge_reachable===true?flag(sb.connection_check_enabled):'Unknown'],['Provider login','Not verified by configuration check'],['Invoice submission','Disabled']];
 const sandboxCard='<section class="card pad mb"><div class="row sb"><h3>'+ic('shield',18)+' Sandbox testing readiness</h3><span class="badge b-warn">Testing only</span></div><dl class="kv mt">'+sandboxEntries.map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl><p class="muted sm mt">Read-only configuration check. Authorized taxpayer login and TIN validation are separate tests. No documents will be submitted.</p></section>';
 const entries=[['Environment','Production'],['Mode','Central intermediary'],['Secure bridge',x.bridge_reachable===true?'Connected':'Unavailable / not checked'],['Central credentials',x.credentials_configured===true?'Configured':x.credentials_configured===false?'Not configured':'Unknown'],['Connection checks',x.bridge_reachable===true?flag(x.connection_check_enabled):'Unknown'],['Intermediary registration',x.intermediary_registration==='owner_confirmed'?'Owner confirmed':'Not checked'],['Provider login','Pending authorized pilot'],['Invoice submission','Disabled until release']];
 return '<section class="card pad mb"><div class="row sb"><h3>'+ic('plug',18)+' Central MyInvois connection</h3><button class="btn sm" onclick="adminFetch()">Refresh status</button></div><dl class="kv mt">'+entries.map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl><p class="muted sm mt">Configuration is not proof of customer authorization.</p></section>'+sandboxCard;
}
const MYR_LHDN_STYLE='<style>.mi-shell{max-width:1080px;margin:0 auto}.mi-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:16px 18px}.mi-head h3{font-size:16px}.mi-head p{margin:4px 0 0;color:var(--muted);font-size:12px}.mi-icon{display:inline-flex;align-items:center;justify-content:center;flex:0 0 38px;width:38px;height:38px;border-radius:12px;background:var(--b50);color:var(--blue)}.mi-status{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600;color:var(--muted)}.mi-dot{height:8px;width:8px;border-radius:50%;background:var(--warn)}.mi-choices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0}.mi-choice{display:flex;flex-direction:column;gap:10px;padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--white);transition:border-color .16s,box-shadow .16s;min-width:0}.mi-choice.mi-selected{border-color:var(--blue);box-shadow:0 0 0 1px var(--blue)}.mi-choice h3{font-size:16px}.mi-choice p{margin:0;font-size:12px;color:var(--muted);line-height:1.5}.mi-choice .btn{width:100%;margin-top:auto;height:35px}.mi-choice .mi-kicker{font-size:11px;font-weight:600;color:var(--muted)}.mi-selection{font-size:11px;color:var(--blue);font-weight:700}.mi-identity{display:grid;grid-template-columns:2fr 1fr 1fr auto;align-items:center;gap:10px;border-top:1px solid var(--line);padding:12px 18px;overflow-wrap:anywhere}.mi-identity small{display:block;color:var(--muted);font-size:11px}.mi-identity strong{font-size:13px;font-weight:600}.mi-panel{padding:16px 18px}.mi-panel h3{font-size:16px}.mi-panel .mi-step{display:grid;grid-template-columns:26px minmax(0,1fr);gap:10px;padding:13px 0;border-top:1px solid var(--line)}.mi-step:first-of-type{margin-top:12px}.mi-number{height:24px;width:24px;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;border-radius:8px;color:var(--blue);font-weight:700;font-size:12px}.mi-step h4{font-size:13px;margin:3px 0 5px}.mi-step p{margin:0 0 8px;color:var(--muted);font-size:12px;line-height:1.5}.mi-notice{background:var(--off);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.5}.mi-notice strong{display:block;color:var(--ink);font-size:12px}.mi-notice p{margin:3px 0 0}.mi-notice .btn{margin-top:8px}.mi-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.mi-form label{display:block;font-weight:600}.mi-form input:not([type=checkbox]){display:block;margin-top:4px}.mi-form .mi-consent,.mi-form .mi-form-actions{grid-column:1/-1}.mi-form .mi-consent{display:flex;gap:8px;align-items:flex-start;font-weight:400;color:var(--muted)}.mi-foot{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:11px;margin:12px 2px}.mi-provider{display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px;margin:10px 0;font-size:12px;overflow-wrap:anywhere}.mi-provider small{display:block;color:var(--muted)}@media(max-width:640px){.mi-choices,.mi-form{grid-template-columns:minmax(0,1fr)}.mi-head,.mi-panel{padding:14px}.mi-identity{grid-template-columns:1fr 1fr;padding:12px 14px}.mi-identity>div:first-child{grid-column:1/-1}.mi-provider{grid-template-columns:1fr}.mi-choice{padding:13px}.mi-form .btn{white-space:normal}}</style>';
function myrLhdnNotice(title,description,retry=false){
 return '<div class="mi-notice"><strong>'+esc(title)+'</strong><p>'+esc(description)+'</p>'+(retry?'<button type="button" class="btn sm" onclick="myrDirectRefresh()">Refresh status</button>':'')+'</div>';
}
function myrLhdnStep(n,title,content){
 return '<section class="mi-step"><span class="mi-number">'+n+'</span><div><h4>'+esc(title)+'</h4>'+content+'</div></section>';
}
function myrCentralCustomer(){
 const co=CO(),hasIdentity=!!(co.tin&&co.brn),canSetup=can('Manage Settings')&&!co.demo&&hasIdentity;
 return MYR_LHDN_STYLE+myrAccountHeading('Integrations','Manage your MyInvois connection.')+
 '<div class="mi-shell"><section class="card"><div class="mi-head"><div class="row nw"><span class="mi-icon">'+ic('plug',20)+'</span><div><h3>LHDN MyInvois</h3><p>Choose the connection that works for your business.</p></div></div><span class="mi-status"><span class="mi-dot"></span> Setup required</span></div>'+
 '<div class="mi-identity"><div><small>Company</small><strong>'+esc(co.name||'—')+'</strong></div><div><small>TIN</small><strong>'+esc(co.tin||'—')+'</strong></div><div><small>BRN</small><strong>'+esc(co.brn||'—')+'</strong></div><a class="btn sm" href="#/app/settings">Edit profile</a></div></section>'+
 '<div class="mi-choices"><section class="mi-choice"><div class="row sb"><span class="mi-icon">'+ic('plug',20)+'</span><span class="mi-kicker">SIMPLER SETUP</span></div><div><h3>Easy Connect</h3><p>Central intermediary</p></div><p>Authorize MYR Invoice in MyInvois. No API keys to manage.</p><p>One-time appointment · Provider details required</p><button type="button" class="btn" aria-pressed="false" data-myr-lhdn-choice="easy" '+(!canSetup?'disabled':'')+' onclick="myrLhdnSelect(this)">Choose Easy Connect</button></section>'+
 '<section class="mi-choice"><div class="row sb"><span class="mi-icon">'+ic('shield',20)+'</span><span class="mi-kicker">OWN ERP CREDENTIALS</span></div><div><h3>Direct Connect</h3><p>Direct ERP</p></div><p>Use your own Client ID and Client Secret. No intermediary appointment.</p><p>Renew credentials before expiry · Sandbox pilot</p><button type="button" class="btn" aria-pressed="false" data-myr-lhdn-choice="direct" '+(!canSetup?'disabled':'')+' onclick="myrLhdnSelect(this)">Choose Direct Connect</button></section></div>'+
 (!canSetup?myrLhdnNotice('Setup requires company access','Complete your company profile and sign in as an authorized settings user.'):'')+
 '<div id="myr-lhdn-choice-panel" aria-live="polite">'+(canSetup?'<div class="mi-notice">Select a method above to view the setup instructions.</div>':'')+'</div><div class="mi-foot">'+ic('shield',14)+' Connection verification and invoice submission are separate. No invoices are submitted during setup.</div></div>';
}
function myrLhdnDirectContent(){
 return '<section class="card mi-panel"><div class="row sb"><h3>Direct Connect setup</h3><span class="badge b-warn">Sandbox only</span></div>'+
 myrLhdnStep(1,'Register your ERP','<p>Sign in to your company’s Sandbox MyInvois account and generate a Client ID and Client Secret.</p><a class="btn sm" href="https://preprod.myinvois.hasil.gov.my/" target="_blank" rel="noopener noreferrer">Open Sandbox Portal ↗</a>')+
 myrLhdnStep(2,'Secure connection','<div id="myr-direct-pilot" aria-live="polite">'+myrLhdnNotice('Checking availability','Credential entry is not enabled yet. Never send API secrets in chat or email.')+'</div>')+
 myrLhdnStep(3,'Verify your connection','<p>Save and verify checks login and TIN/BRN. Independent issuer verification is required before submission.</p>')+'</section>';
}
function myrDirectView(el,result){
 if(!el||!el.isConnected)return;
 if(result?.available!==true||result.environment!=='sandbox'||result.mode!=='direct_erp'||result.issuer_binding_verified!==false||result.submission_enabled!==false||!Number.isSafeInteger(result.revision)||result.revision<0){
  el.innerHTML=myrLhdnNotice('Secure setup unavailable','Sandbox access is not enabled for this account. Contact support to request access.',true);return;
 }
 const labels={not_configured:'Not connected',pending_identity_review:'Identity review pending',expired:'Credentials expired',disconnected:'Disconnected'};
 if(!Object.hasOwn(labels,result.status)){el.textContent='Connection status unavailable.';return;}
 const loginLabels={login_verified:'Login verified',cached_login:'Previous login verified',credentials_rejected:'Credentials rejected',rate_limited:'Rate limited',provider_unavailable:'Provider unavailable',invalid_provider_response:'Invalid provider response'};
 const expires=typeof result.expiry==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(result.expiry)?result.expiry:null;
 el.innerHTML='<div class="note mt8"><strong>'+labels[result.status]+'</strong><dl class="kv mt8"><dt>Authentication</dt><dd>'+(Object.hasOwn(loginLabels,result.last_login_status)?loginLabels[result.last_login_status]:'Not verified')+'</dd><dt>TIN/BRN lookup</dt><dd>'+(result.tin_brn_lookup_verified===true?'Matched':'Not verified')+'</dd><dt>Issuer identity</dt><dd>Pending independent verification</dd><dt>Submission</dt><dd>Disabled</dd>'+(expires?'<dt>Secret expiry (owner supplied)</dt><dd>'+esc(expires)+'</dd>':'')+'</dl></div>'+
 (result.verification_review_required===true?'<p class="note w mt8">Verification paused for operator review. Do not retry or replace credentials to bypass a provider wait.</p>':'')+
 (result.verification_deferred===true?'<p class="muted sm mt8">Verification deferred. Refresh status before retrying.</p>':'')+
 '<form id="myr-direct-credentials" method="post" action="/api/myr/lhdn/direct-pilot" autocomplete="off" onsubmit="event.preventDefault();myrDirectAction(this,\'save\')" class="mi-form mt"><input type="hidden" name="revision" value="'+result.revision+'"><label class="sm">Sandbox Client ID<input class="inp" name="client_id" type="password" autocomplete="new-password" required maxlength="512"></label><label class="sm">Sandbox Client Secret<input class="inp" name="client_secret" type="password" autocomplete="new-password" required maxlength="1024"></label><label class="sm">Secret expiry date (from your portal)<input class="inp" name="expiry" type="date" required></label><label class="sm mi-consent"><input type="checkbox" name="consent" required> I consent to encrypted credential storage and a Sandbox connection check for this company.</label><div class="row mi-form-actions" style="flex-wrap:wrap;gap:8px"><button class="btn p" type="submit" '+(result.verification_review_required?'disabled':'')+'>Save &amp; verify</button>'+
 (result.status==='pending_identity_review'?'<button class="btn" type="button" '+(result.verification_review_required?'disabled':'')+' onclick="myrDirectAction(this.form,\'verify\')">Verify again</button>':'')+
 (result.revision>0&&result.status!=='disconnected'?'<button class="btn" type="button" onclick="myrDirectAction(this.form,\'disconnect\')">Disconnect</button>':'')+
 '<button class="btn" type="button" onclick="myrDirectRefresh()">Refresh status</button></div></form><p class="muted sm mt8">Disconnect removes the active saved credentials from MYR Invoice, not the ERP registration in MyInvois.</p>';
}
async function myrDirectRequest(action,extra,el,co){
 if(!co||!el||!el.isConnected||!can('Manage Settings')||co.demo||!Number.isSafeInteger(co._v))return;
 const cid=co.id,version=co._v;
 const current=()=>el.isConnected&&document.getElementById('myr-direct-pilot')===el&&CO()?.id===cid&&CO()?._v===version;
 try{
  const session=(await SB.auth.getSession()).data.session;
  if(!session?.native||!current())throw Error('Native business sign-in required');
  const response=await fetch('/api/myr/lhdn/direct-pilot',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',cache:'no-store',body:JSON.stringify({action,p_company_id:cid,p_version:version,...extra})});
  if(!response.ok)throw Error('Connection unavailable');
  const result=await response.json();
  if(current())myrDirectView(el,result);
 }catch(e){if(current())el.innerHTML=myrLhdnNotice('Setup not available yet','No connection has been confirmed. Refresh status or contact support.',true);}
 finally{if(extra){delete extra.client_id;delete extra.client_secret;}}
}
function myrDirectRefresh(){
 const el=document.getElementById('myr-direct-pilot'),co=CO();
 if(el)myrDirectRequest('status',{},el,co);
}
function myrDirectAction(form,action){
 const el=document.getElementById('myr-direct-pilot'),co=CO();
 if(!co||!el||!form||!el.contains(form)||!form.isConnected||!can('Manage Settings')||co.demo)return;
 const revision=Number(form.elements.revision.value),extra={revision};
 if(!Number.isSafeInteger(revision)||revision<0)return;
 if(action==='save'){
  if(!form.reportValidity()||!form.elements.consent.checked)return;
  Object.assign(extra,{client_id:form.elements.client_id.value,client_secret:form.elements.client_secret.value,expiry:form.elements.expiry.value,consent:true});
 }else if(action==='disconnect'){if(!confirm('Disconnect this Sandbox ERP? You can reconnect later.'))return;}
 else if(action!=='verify')return;
 // Never persist or log secrets in browser storage / company snapshots.
 form.elements.client_id.value='';form.elements.client_secret.value='';
 el.innerHTML='<p class="muted sm mt8" role="status">Checking secure connection…</p>';
 myrDirectRequest(action,extra,el,co);
}
function myrLhdnSelect(btn){
 const co=CO(),panel=document.getElementById('myr-lhdn-choice-panel');
 if(!co||!panel||btn.disabled||!can('Manage Settings')||co.demo||!co.tin||!co.brn)return;
 const mode=btn.dataset.myrLhdnChoice;if(mode!=='easy'&&mode!=='direct')return;
 for(const el of document.querySelectorAll('[data-myr-lhdn-choice]')){
  const selected=el===btn;
  el.setAttribute('aria-pressed',selected?'true':'false');
  el.classList.toggle('p',selected);
  el.closest('.mi-choice')?.classList.toggle('mi-selected',selected);
  el.textContent=selected?'Selected · '+(mode==='easy'?'Easy Connect':'Direct Connect'):'Choose '+(el.dataset.myrLhdnChoice==='easy'?'Easy Connect':'Direct Connect');
 }
 panel.innerHTML=mode==='easy'?myrLhdnEasyContent():myrLhdnDirectContent();
 if(mode==='direct')myrDirectRefresh();
}
function myrLhdnEasyContent(){
 const co=CO(),party=MYR_CENTRAL_LHDN.intermediary,ready=!!(co.tin&&co.brn);
 const details=party?'<div class="mi-provider"><div><small>Registered name</small>'+esc(party.name)+'</div><div><small>Intermediary TIN</small>'+esc(party.tin)+'</div><div><small>BRN</small>'+esc(party.brn)+'</div></div>':myrLhdnNotice('Provider details pending','Contact support before appointing an intermediary.');
 return '<section class="card mi-panel"><div class="row sb"><h3>Easy Connect setup</h3><span class="badge b-warn">Authorization pending</span></div>'+
 myrLhdnStep(1,'Authorize MYR Invoice','<p>Sign in to MyTax, select your company and open Taxpayer Profile → Representatives → Intermediary.</p>'+details+'<a class="btn sm mt8" href="https://mytax.hasil.gov.my/" target="_blank" rel="noopener noreferrer">Open MyTax Portal ↗</a>')+
 myrLhdnStep(2,'Test connection','<p>Connection checks are limited to approved company owners. Invoice submission is not enabled.</p><button type="button" class="btn sm p" '+(!can('Manage Settings')||!ready||!party||co.demo?'disabled':'')+' onclick="myrCentralCheck(this)">Test connection</button><div class="mt8" id="myr-central-result" role="status"></div>')+'</section>';
}
async function myrCentralCheck(btn){
 const co=CO();if(!co||btn.disabled)return;const cid=co.id;btn.disabled=true;
 const messages={review_required:'Company identity review required before connection testing.',connection_check_disabled:'Pilot connection test not enabled.',login_verified:'LHDN intermediary login verified for this check. Submission remains disabled.',cached_login:'Previous login cached; current permissions have not been rechecked.',authorization_or_credentials_rejected:'LHDN rejected authorization or credentials.',retry_later:'Please retry after 20 seconds.',rate_limited:'LHDN rate limit reached. Retry later.',bridge_unavailable:'Secure connector unavailable.'};
 try{const session=(await SB.auth.getSession()).data.session;if(!session)throw Error('Sign in required');const r=await fetch('/api/myr/lhdn/connection',{method:'POST',headers:myrAuthHeaders(session,true),body:JSON.stringify({p_company_id:cid}),cache:'no-store'});const d=await r.json();if(!r.ok)throw Error('Connection check unavailable ('+r.status+')');if(CO()?.id===cid&&document.getElementById('myr-central-result'))document.getElementById('myr-central-result').textContent=messages[d.status]||'Connection check unavailable. Contact support.';}catch(e){if(CO()?.id===cid&&document.getElementById('myr-central-result'))document.getElementById('myr-central-result').textContent=e.message;}finally{btn.disabled=false}
}
"""
def transform(html):
    html=once(html,"async function cloudInit(publicOnly){",JS+"\nasync function cloudInit(publicOnly){")
    html=once(html,"const rows=result.companies,mem={data:result.members},docs={data:result.documents},links={data:result.links||[]};","MYR_CENTRAL_LHDN=result.central_lhdn||{};const rows=result.companies,mem={data:result.members},docs={data:result.documents},links={data:result.links||[]};")
    html=once(html,"ADM={loaded:true,rows:d.rows,events:d.events,users:d.users,audit:d.audit,err:''}","ADM={loaded:true,rows:d.rows,events:d.events,users:d.users,audit:d.audit,central_lhdn:d.central_lhdn,err:''}")
    html=once(html,"function vIntegrationsContent(){const co=CO();const L2=co.lhdn;","function vIntegrationsContent(){return myrCentralCustomer();}\nfunction myrLegacyIntegrationsContent(){const co=CO();const L2=co.lhdn;")
    html=once(html,"head('LHDN API Monitor','Submission health across all companies. External LHDN processing time is separate from app performance.')+","head('LHDN API Monitor','Submission health across all companies. External LHDN processing time is separate from app performance.')+myrCentralAdmin(D)+")
    # Existing dashboard card: never infer authorization from imported legacy data.
    html=once(html,"connected=lhdnHealth(co)==='Connected'","connected=false")
    html=once(html,"LHDN Connection</h3>'+B(lhdnHealth(co))","LHDN Connection</h3>'+B('Authorization pending')")
    html=once(html,"<dt>Environment</dt><dd>'+(co.lhdn.env==='production'?'Production':'Sandbox (testing)')","<dt>Environment</dt><dd>'+('Production · central intermediary')")
    html=once(html,"<dt>Last success</dt><dd>'+fmtDT(co.lhdn.lastOk)","<dt>Authorization</dt><dd>'+('Pending verification')")
    return html
