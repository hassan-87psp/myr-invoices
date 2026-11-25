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
