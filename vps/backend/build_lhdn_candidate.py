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
 return '<section class="card pad"><div class="row sb" style="flex-wrap:wrap;gap:8px"><h3>'+ic('key',18)+' Direct Connect · ERP</h3><span class="badge b-warn">Pilot preparation</span></div>'+
 '<dl class="kv mt8"><dt>Company</dt><dd>'+esc(co.name||'—')+'</dd><dt>TIN</dt><dd>'+esc(co.tin||'—')+'</dd><dt>BRN</dt><dd>'+esc(co.brn||'—')+'</dd></dl>'+
 '<h3 class="mt">1. Register your ERP</h3><p class="muted sm mt8">Open MyInvois using your own company profile, go to ERP registration and generate the Client ID and Client Secret. Sandbox and production credentials are different.</p><a class="btn sm mt8" href="https://preprod.myinvois.hasil.gov.my/" target="_blank" rel="noopener noreferrer">Open Sandbox Portal ↗</a>'+
 '<h3 class="mt">2. Secure connection</h3><p class="note w mt8">Credential entry is not enabled yet. Do not send your API secrets by chat or email. The secure connection form will become available only after the server-side pilot is released.</p>'+
 '<h3 class="mt">3. Automatic processing</h3><p class="muted sm mt8">After a verified connection, MYR Invoice will manage token renewal, document submission and status updates when those features are released. No connection has been verified and no invoice will be submitted from this screen.</p></section>';
}
function myrLhdnSelect(btn){
 const co=CO(),panel=document.getElementById('myr-lhdn-choice-panel');
 if(!co||!panel||btn.disabled||!can('Manage Settings')||co.demo||!co.tin||!co.brn)return;
 const mode=btn.dataset.myrLhdnChoice;if(mode!=='easy'&&mode!=='direct')return;
 for(const el of document.querySelectorAll('[data-myr-lhdn-choice]'))el.setAttribute('aria-pressed',el===btn?'true':'false');
 panel.innerHTML=mode==='easy'?myrLhdnEasyContent():myrLhdnDirectContent();
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
