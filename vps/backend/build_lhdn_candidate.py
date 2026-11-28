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
function myrCentralCustomer(){
 const co=CO(),hasIdentity=!!(co.tin&&co.brn),canSetup=can('Manage Settings')&&!co.demo&&hasIdentity;
 return myrAccountHeading('Integrations','Choose how your business connects to LHDN MyInvois.')+
 '<section class="card pad mb"><div class="row sb" style="flex-wrap:wrap;gap:8px"><h3>'+ic('plug',18)+' LHDN Connection</h3><span class="badge b-warn">Setup required</span></div><p class="muted sm mt8">Choose one connection method. You only need to set it up once; authorization or credentials may need renewal later.</p>'+
 '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px;margin-top:16px">'+
 '<div class="card pad" style="display:flex;flex-direction:column;gap:8px"><div class="row sb"><h3>'+ic('zap',18)+' Easy Connect</h3><span class="badge b-warn">Simpler setup</span></div><strong>Central Intermediary</strong><p class="muted sm">Authorize MYR Invoice in your MyInvois portal. No customer API keys to manage.</p><p class="sm">One-time appointment · Provider identity required</p><button type="button" class="btn p" style="margin-top:auto" aria-pressed="false" data-myr-lhdn-choice="easy" '+(!canSetup?'disabled':'')+' onclick="myrLhdnSelect(this)">Choose Easy Connect</button></div>'+
 '<div class="card pad" style="display:flex;flex-direction:column;gap:8px"><h3>'+ic('key',18)+' Direct Connect</h3><strong>Own ERP Credentials</strong><p class="muted sm">Connect using your company’s own MyInvois Client ID and Client Secret. No intermediary appointment.</p><p class="sm">One-time ERP setup · Credential renewal when required</p><button type="button" class="btn" style="margin-top:auto" aria-pressed="false" data-myr-lhdn-choice="direct" '+(!canSetup?'disabled':'')+' onclick="myrLhdnSelect(this)">Choose Direct Connect</button></div></div>'+
 (!canSetup?'<p class="note w mt8">A company owner or authorized settings user with complete company details is required to start setup.</p>':'')+
 '<p class="muted sm mt8">Connection verification and invoice submission are separate release stages. Selecting an option does not connect or submit anything.</p></section><div id="myr-lhdn-choice-panel" aria-live="polite"></div>';
}
function myrLhdnDirectContent(){
 const co=CO();
 return '<section class="card pad"><div class="row sb" style="flex-wrap:wrap;gap:8px"><h3>'+ic('key',18)+' Direct Connect · ERP</h3><span class="badge b-warn">Sandbox only</span></div>'+
 '<dl class="kv mt8"><dt>Company</dt><dd>'+esc(co.name||'—')+'</dd><dt>TIN</dt><dd>'+esc(co.tin||'—')+'</dd><dt>BRN</dt><dd>'+esc(co.brn||'—')+'</dd></dl>'+
 '<h3 class="mt">1. Register your ERP</h3><p class="muted sm mt8">Open MyInvois with your own company profile, register your ERP and generate a Sandbox Client ID and Client Secret. Keep production credentials separate.</p><a class="btn sm mt8" href="https://preprod.myinvois.hasil.gov.my/" target="_blank" rel="noopener noreferrer">Open Sandbox Portal ↗</a>'+
 '<h3 class="mt">2. Secure connection</h3><div id="myr-direct-pilot" aria-live="polite"><p class="note w mt8">Credential entry is not enabled yet. Checking availability. Do not send API secrets by chat or email.</p></div>'+
 '<h3 class="mt">3. Verification</h3><p class="muted sm mt8">The system checks login and TIN/BRN after saving. Issuer identity review and invoice submission are separate release stages. No invoice will be submitted from this screen.</p></section>';
}
function myrDirectView(el,result){
 if(!el||!el.isConnected)return;
 if(result?.available!==true||result.environment!=='sandbox'||result.mode!=='direct_erp'||result.issuer_binding_verified!==false||result.submission_enabled!==false||!Number.isSafeInteger(result.revision)||result.revision<0){
  el.innerHTML='<p class="note w mt8">Secure credential entry is unavailable. An approved Sandbox company owner is required. Do not send API secrets by chat or email.</p>';return;
 }
 const labels={not_configured:'Not connected',pending_identity_review:'Identity review pending',expired:'Credentials expired',disconnected:'Disconnected'};
 if(!Object.hasOwn(labels,result.status)){el.textContent='Connection status unavailable.';return;}
 const loginLabels={login_verified:'Login verified',cached_login:'Previous login verified',credentials_rejected:'Credentials rejected',rate_limited:'Rate limited',provider_unavailable:'Provider unavailable',invalid_provider_response:'Invalid provider response'};
 const expires=typeof result.expiry==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(result.expiry)?result.expiry:null;
 el.innerHTML='<div class="note mt8"><strong>'+labels[result.status]+'</strong><dl class="kv mt8"><dt>Authentication</dt><dd>'+(Object.hasOwn(loginLabels,result.last_login_status)?loginLabels[result.last_login_status]:'Not verified')+'</dd><dt>TIN/BRN lookup</dt><dd>'+(result.tin_brn_lookup_verified===true?'Matched':'Not verified')+'</dd><dt>Issuer identity</dt><dd>Pending independent verification</dd><dt>Submission</dt><dd>Disabled</dd>'+(expires?'<dt>Secret expiry (owner supplied)</dt><dd>'+esc(expires)+'</dd>':'')+'</dl></div>'+
 (result.verification_review_required===true?'<p class="note w mt8">Verification paused for operator review. Do not retry or replace credentials to bypass a provider wait.</p>':'')+
 (result.verification_deferred===true?'<p class="muted sm mt8">Verification deferred. Refresh status before retrying.</p>':'')+
 '<form id="myr-direct-credentials" method="post" action="/api/myr/lhdn/direct-pilot" autocomplete="off" onsubmit="event.preventDefault();myrDirectAction(this,\'save\')" class="mt"><input type="hidden" name="revision" value="'+result.revision+'"><label class="sm">Sandbox Client ID<input class="inp" name="client_id" type="password" autocomplete="new-password" required maxlength="512"></label><label class="sm">Sandbox Client Secret<input class="inp" name="client_secret" type="password" autocomplete="new-password" required maxlength="1024"></label><label class="sm">Secret expiry date (from your portal)<input class="inp" name="expiry" type="date" required></label><label class="sm mt8"><input type="checkbox" name="consent" required> I own or am authorized to manage this company and consent to encrypted storage and a Sandbox connection check.</label><div class="row mt8" style="flex-wrap:wrap;gap:8px"><button class="btn p" type="submit" '+(result.verification_review_required?'disabled':'')+'>Save &amp; verify</button>'+
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
 }catch(e){if(current())el.innerHTML='<p class="note w mt8">Secure connection unavailable. No connection has been confirmed. Refresh this page or contact support.</p>';}
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
 for(const el of document.querySelectorAll('[data-myr-lhdn-choice]'))el.setAttribute('aria-pressed',el===btn?'true':'false');
 panel.innerHTML=mode==='easy'?myrLhdnEasyContent():myrLhdnDirectContent();
 if(mode==='direct')myrDirectRefresh();
}
function myrLhdnEasyContent(){
 const co=CO(),party=MYR_CENTRAL_LHDN.intermediary,ready=!!(co.tin&&co.brn);
 return '<div class="card pad"><div class="row sb"><h3>'+ic('plug',18)+' LHDN MyInvois</h3><span class="badge b-warn">Authorization pending</span></div><div class="note mt">Production · Central intermediary · Invoice submission not released</div>'+
 '<h3 class="mt">1. Confirm company details</h3><dl class="kv mt8"><dt>Company</dt><dd>'+esc(co.name||'—')+'</dd><dt>TIN</dt><dd>'+esc(co.tin||'—')+'</dd><dt>BRN</dt><dd>'+esc(co.brn||'—')+'</dd></dl><a class="btn sm" href="#/app/settings">Review company profile</a>'+
 '<h3 class="mt">2. Authorize MYR Invoice</h3><p class="muted sm mt8">Sign in to MyTax, select your company, open Taxpayer Profile → Representatives → Intermediary and add the registered service provider with appropriate permissions.</p>'+
 (party?'<dl class="kv mt8"><dt>Registered name</dt><dd>'+esc(party.name)+'</dd><dt>Intermediary TIN</dt><dd>'+esc(party.tin)+'</dd><dt>BRN</dt><dd>'+esc(party.brn)+'</dd></dl>':'<p class="note w mt8">Registered intermediary details not yet published. Contact support before authorizing.</p>')+
 '<a class="btn mt8" href="https://mytax.hasil.gov.my/" target="_blank" rel="noopener noreferrer">Open MyTax Portal ↗</a>'+
 '<h3 class="mt">3. Verify connection</h3><p class="muted sm mt8">Only an approved pilot company owner can test. No invoice will be submitted.</p><button class="btn p mt8" '+(!can('Manage Settings')||!ready||!party||co.demo?'disabled':'')+' onclick="myrCentralCheck(this)">Test connection</button><div class="mt8" id="myr-central-result" role="status"></div></div>';
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
