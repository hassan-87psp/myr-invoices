from build_hybrid_preview import once
JS=r"""
let MYR_CENTRAL_LHDN={};
function myrCentralAdmin(d){
 const x=d.central_lhdn||{};
 const entries=[['Environment','Production'],['Mode','Central intermediary'],['Secure bridge',x.bridge_reachable===true?'Connected':'Unavailable / not checked'],['Central credentials',x.credentials_configured===true?'Configured':x.credentials_configured===false?'Not configured':'Unknown'],['Intermediary registration',x.intermediary_registration==='owner_confirmed'?'Owner confirmed':'Not checked'],['Provider login','Pending authorized pilot'],['Invoice submission','Disabled until release']];
 return '<section class="card pad mb"><div class="row sb"><h3>'+ic('plug',18)+' Central MyInvois connection</h3><button class="btn sm" onclick="adminFetch()">Refresh status</button></div><dl class="kv mt">'+entries.map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl><p class="muted sm mt">Configuration is not proof of customer authorization.</p></section>';
}
function myrCentralCustomer(){
 const co=CO(),party=MYR_CENTRAL_LHDN.intermediary,ready=!!(co.tin&&co.brn);
 return myrAccountHeading('Integrations','Connect MyInvois without creating API keys.')+
 '<div class="card pad"><div class="row sb"><h3>'+ic('plug',18)+' LHDN MyInvois</h3><span class="badge b-warn">Authorization pending</span></div><div class="note mt">Production · Central intermediary · Invoice submission not released</div>'+
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
    return html
