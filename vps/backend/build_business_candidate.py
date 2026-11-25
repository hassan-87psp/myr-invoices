"""Build production API integration preview without changing live web assets.
Reuse the proven private UI adaptations, but connect only to business_api.
All real mutations remain hard-disabled by the API until cutover.
"""
import os
import shutil
import tempfile
from pathlib import Path
from build_hybrid_preview import once, APP_ROOT
from build_write_preview import DEST as SYNTHETIC

TARGET=Path(os.environ.get("MYR_CANDIDATE_DIR",str(Path.home()/"myr-staging"/"business-candidate")))

def main():
    html=(SYNTHETIC/"index.html").read_text()
    for before,after in (
        ("/hybrid/write-workspace","/workspace"),
        ("result.mode!=='synthetic_write'","result.mode!=='native_candidate'"),
        ("result.company_data.vpsSyntheticWriteTest!==true","result.company_data.vpsSyntheticWriteTest===true"),
        ("'/hybrid/test-record'","'/records'"),
        ("'/hybrid/test-payment'","'/payments'"),
        ("'/hybrid/test-delete'","'/delete'"),
        ("'/hybrid/test-profile'","'/profile'"),
        ("atomic_team:'/hybrid/test-team',atomic_approval:'/hybrid/test-approval',atomic_onboard:'/hybrid/test-onboard'","atomic_team:'/team',atomic_approval:'/approval',atomic_onboard:'/onboard'"),
        ("const rows=result.companies,mem={data:result.members},docs={data:result.documents},links={data:[]};","const rows=result.companies,mem={data:result.members},docs={data:result.documents},links={data:result.links||[]};"),
        ("PRIVATE VPS WRITE TEST — SYNTHETIC DATA ONLY — Draft invoices, customers, products and manual payments. Other writes disabled.","PRIVATE VPS DATABASE CANDIDATE — Real imported data read-only. Production saves and external integrations disabled."),
    ):
        html=once(html,before,after)
    # Do not let the rehearsal-only onboarding UI send misleading payloads.
    start=html.index("async function saveOnboard(){")
    end=html.index("async function demoCompany(){",start)
    html=html[:start]+"""async function saveOnboard(){const p={name:val('ob-name'),tin:val('ob-tin').toUpperCase(),brn:val('ob-brn'),sst:val('ob-sst')||'NA',ttx:'NA',msic:val('ob-msic'),msicDesc:val('ob-msicd'),email:val('ob-email'),phone:val('ob-phone'),addr:{line:val('ob-line'),city:val('ob-city'),postcode:val('ob-post'),state:val('ob-state'),country:'MYS'}};const {data,error}=await SB.rpc('atomic_onboard',{p_profile:p});if(error||!data)return toast(error?.message||'Onboarding unavailable','err');await cloudLoad();DB.currentId=data.id;go(myrStartRoute())}
"""+html[end:]
    start=html.index("async function vpsTeam(")
    end=html.index("function verifyAudit(){",start)
    html=html[:start]+"""async function vpsTeam(op,email,role){const co=CO();if(!co||!can('Invite Team')||!(await atomicReady(co)))return;const {data,error}=await SB.rpc('atomic_team',{p_company_id:co.id,p_operation:op,p_email:email,p_role:role||null});if(error||!data)return toast(error?.message||'Team action rejected','err');await cloudLoad();closeModal();rerender();toast(op==='invite'?'Invitation recorded; email delivery not enabled.':'Team updated')}
async function saveInvite(){return vpsTeam('invite',val('iv-e').trim().toLowerCase(),val('iv-r'))}
async function setRole(e,r){return vpsTeam('role',e,r)}
function rmMember(e){confirmBox('Remove member?','This removes company access.','Remove',()=>vpsTeam('remove',e),true)}
"""+html[end:]
    html=once(html,"toast('Test workflow: '+data.record.appStatus)","toast('Workflow: '+data.record.appStatus)")
    html=once(html,"toast('Test profile saved')","toast('Profile saved')")
    # Public capability routes do not use a user bearer token. They still
    # fail closed at the backend until a real cutover is approved.
    html=once(html,"rpc:async(name,args)=>{const endpoint=","""rpc:async(name,args)=>{const publicEndpoint={get_public_link:'/links/read',submit_public_link:'/links/submit'}[name];if(publicEndpoint){try{const payload=structuredClone(args);if(name==='submit_public_link'&&payload.p_payload&&Object.prototype.hasOwnProperty.call(payload.p_payload,'addr')){delete payload.p_payload.at;payload.p_payload.consent=!!document.getElementById('by-ok')?.checked}const res=await fetch(publicEndpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),cache:'no-store'});const data=await res.json();if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Link unavailable');return {data,error:null}}catch(error){return {data:null,error}}}const endpoint=""")
    # Admin reads now use one authorized aggregate endpoint, not direct tables.
    start=html.index("async function adminFetch(){")
    end=html.index("function adminLocal(){",start)
    html=html[:start]+"""async function adminFetch(){try{const session=(await SB.auth.getSession()).data.session;if(!session)throw new Error('Sign in required');const response=await fetch('/admin/dashboard',{headers:{Authorization:'Bearer '+session.access_token},cache:'no-store'});if(!response.ok)throw new Error('Admin data unavailable ('+response.status+')');const d=await response.json();ADM={loaded:true,rows:d.rows,events:d.events,users:d.users,audit:d.audit,err:''}}catch(err){ADM={loaded:true,rows:[],events:[],users:[],audit:[],err:'Could not load admin data: '+err.message}}if(location.hash.startsWith('#/admin'))route()}
"""+html[end:]
    # The old mirror dashboard cannot describe the native canonical store.
    start=html.index("async function adminLoadParity(){")
    end=html.index("function vAdmin(",start)
    html=html[:start]+"""async function adminLoadParity(){PARITY={loaded:true,rows:[],recovery:[],err:'Native database integrity dashboard not released. Use server reconciliation checks.'};if(location.hash.startsWith('#/admin/integrity'))route()}
"""+html[end:]
    start=html.index(" if(t==='integrity'){")
    end=html.index("  const title=",start)
    html=html[:start]+""" if(t==='integrity'){return adminShell(t,head('Data Integrity','Native VPS database')+'<div class="note w">Native integrity dashboard not released. Use server reconciliation checks.</div>')}
 if(false&&t==='integrity'){
"""+html[end:]
    html=once(html,"const endpoint={atomic_save_record:","const endpoint={admin_set_company:'/admin/company',atomic_save_record:")
    html=once(html,"SB.rpc('admin_set_company',{p_id:id,p_status:status||null,p_plan:plan||null})","SB.rpc('admin_set_company',{p_company_id:id,p_version:ADM.rows.find(r=>r.id===id)?.version,p_status:status||null,p_plan:plan||null})")
    # Candidate reads never activate invitations. The write endpoint is invoked
    # only after the workspace explicitly reports production writes enabled.
    html=once(html,"const result=await response.json();if(result.mode!==","let result=await response.json();if(result.writes_enabled===true){const accepted=await fetch('/team/accept',{method:'POST',headers:{Authorization:'Bearer '+session.access_token},cache:'no-store'});if(!accepted.ok)throw new Error('Could not check team invitations');const state=await accepted.json();if(state.accepted>0){const updated=await fetch('/workspace',{headers:{Authorization:'Bearer '+session.access_token},cache:'no-store'});if(!updated.ok)throw new Error('Could not reload team workspace');result=await updated.json()}}if(result.mode!==")
    # All link changes are typed native transactions, never unrestricted snapshots.
    html=once(html,"const endpoint={admin_set_company:","const endpoint={link_manage:'/links/manage',admin_set_company:")
    html=once(html,"if(!inv.share?.token||String(inv.share.exp)<todayStr()){inv.share={token:rid(32),exp:addDays(todayStr(),30)};save()}","if(!(await vpsLinkOp(co,'share',{id})))return;")
    html=once(html,"  if(!(await syncLinks(co)))return;","  // Link was committed by the native operation.")
    html=once(html,"const token=inv.share.token;if(!(await myrLinkConfirmed(token,id)))","const token=CO()?.invoices.find(x=>x.id===id)?.share?.token;if(!token||!(await myrLinkConfirmed(token,id)))")
    html=once(html,"fmtDate(inv.share.exp)","fmtDate(CO().invoices.find(x=>x.id===id).share.exp)")
    start=html.index("function myrRevokeShare(")
    end=html.index("/* ================= E-Invoice Centre",start)
    html=html[:start]+"""async function vpsLinkOp(co,action,payload){if(!co||!can('Edit Draft')||!(await atomicReady(co)))return null;const {data,error}=await SB.rpc('link_manage',{p_company_id:co.id,p_version:co._v,p_action:action,p_payload:payload});if(error||!data){toast(error?.message||'Link operation unavailable','err');return null}try{await cloudLoad();return data}catch(e){toast('Operation saved; reload to view it.','warn');return null}}
function myrRevokeShare(id){const co=CO();confirmBox('Revoke customer link?','The existing link will stop working.','Revoke',async()=>{if(await vpsLinkOp(co,'revoke',{id})){closeModal();rerender();toast('Link revoked')}},true)}
"""+html[end:]
    start=html.index("function qrSave(){")
    end=html.index("function qrShow(",start)
    html=html[:start]+"""async function qrSave(){const co=CO(),id=uuid();if(await vpsLinkOp(co,'qr_create',{id,label:val('qr-l')||'QR request',receipt:val('qr-r'),days:+val('qr-x')||7})){rerender();qrShow(id)}}
"""+html[end:]
    start=html.index("function qrRegen(")
    end=html.index("function qrReview(",start)
    html=html[:start]+"""async function qrRegen(id){if(await vpsLinkOp(CO(),'qr_regenerate',{id})){rerender();qrShow(id)}}
"""+html[end:]
    start=html.index("function qrApprove(")
    end=html.index("function vBuyer(",start)
    html=html[:start]+"""async function qrApprove(id){const co=CO(),r=co.requests.find(x=>x.id===id),d=await vpsLinkOp(co,'qr_approve',{id});if(!d)return;closeModal();const n=blankInvoice(CO());n.customerId=d.customer_id;n.notes=r.receipt?'Receipt ref: '+r.receipt:'';PREFILL=n;go('#/app/invoices/new')}
async function qrReject(id){if(await vpsLinkOp(CO(),'qr_decline',{id})){closeModal();rerender()}}
"""+html[end:]
    html=once(html,"data.data?'Received':'Open'","data.meta?.received?'Received':'Open'")
    # Optional same-origin production routing build. Private candidate stays
    # unchanged by default and the API write gate is never opened here.
    prefix=os.environ.get("MYR_BUSINESS_API_PREFIX","")
    if prefix not in ("","/api/myr"):
        raise SystemExit("Unapproved API prefix")
    if prefix:
        html=html.replace("fetch('/workspace',","fetch('/api/myr/workspace',")
        for route in ("/records","/payments","/delete","/profile","/team","/team/accept","/approval","/onboard","/links/read","/links/submit","/links/manage","/admin/dashboard","/admin/company"):
            html=once(html,"'"+route+"'","'"+prefix+route+"'")
    # No fallback to the Supabase data API.
    assert "from:()=>{throw new Error(" in html
    assert "/hybrid/test-" not in html and "/hybrid/write-workspace" not in html
    assert "persistSession:false" in html
    TARGET.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TARGET.parent) as tmp:
        root=Path(tmp)
        for p in SYNTHETIC.iterdir():
            if p.is_file(): shutil.copy2(p,root/p.name)
        (root/"index.html").write_text(html)
        TARGET.mkdir(mode=0o700,exist_ok=True)
        for p in root.iterdir(): os.replace(p,TARGET/p.name)
    print("MYR_BUSINESS_FRONTEND_CANDIDATE_BUILT")

if __name__=="__main__":
    main()
