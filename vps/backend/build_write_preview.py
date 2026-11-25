"""Build an isolated original-UI rehearsal from the existing read-only build."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from build_hybrid_preview import TARGET, once
DEST=TARGET.with_name("hybrid-write-website")

def main():
    html=(TARGET/"index.html").read_text()
    html=once(html,"rpc:blocked};","""rpc:async(name,args)=>{const endpoint={atomic_save_record:'/hybrid/test-record',atomic_add_payment:'/hybrid/test-payment',atomic_delete_record:'/hybrid/test-delete',atomic_save_profile:'/hybrid/test-profile'}[name];if(!endpoint)return blocked();try{const session=(await client.auth.getSession()).data.session;if(!session)throw new Error('Sign in required');const res=await fetch(endpoint,{method:'POST',headers:{Authorization:'Bearer '+session.access_token,'Content-Type':'application/json'},body:JSON.stringify(args),cache:'no-store'});const data=await res.json();if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Record write rejected');return {data,error:null}}catch(error){return {data:null,error}}}};""")
    html=once(html,"fetch('/hybrid/workspace'","fetch('/hybrid/write-workspace'")
    html=once(html,"result.mode!=='read_only'","result.mode!=='synthetic_write'")
    html=once(html,"function save(){return;/* Read-only preview: no persistence. */","function save(){if(DB.companies.some(c=>c._v&&PUSHED[c.id]!==fnv(JSON.stringify(coBody(c))))){toast('This action is not connected in this rehearsal. Reload to discard local changes.','err');throw new Error('Unsupported rehearsal mutation')}return;/* Block all generic snapshot writes. */")
    html=once(html,"async function cloudPush(){return true;/* Read-only preview: no network writes. */","async function cloudPush(){return !DB.companies.some(c=>c._v&&PUSHED[c.id]!==fnv(JSON.stringify(coBody(c))));/* No generic snapshot writes. */")
    html=once(html,"if(CLOUD&&idx<0&&ED._autoNumber&&ED.number===ED._autoNumber){","if(false&&CLOUD&&idx<0&&ED._autoNumber&&ED.number===ED._autoNumber){")
    html=once(html,"p_expected:expected\n   });","p_expected:expected,p_auto:idx<0&&!!ED._autoNumber&&ED.number===ED._autoNumber\\n   });")
    start=html.index("function saveSettings(){")
    end=html.index("function logoFile(f){",start)
    html=html[:start]+"""async function saveSettings(){const co=CO();if(!co||!can('Manage Settings')||!(await atomicReady(co)))return;const before=coBody(co);const p={name:val('st-name'),tin:val('st-tin').toUpperCase(),brn:val('st-brn'),sst:val('st-sst')||'NA',ttx:val('st-ttx')||'NA',msic:val('st-msic'),msicDesc:val('st-msicd'),email:val('st-email'),phone:val('st-phone'),addr:{line:val('st-line'),city:val('st-city'),postcode:val('st-post'),state:val('st-state'),country:co.addr?.country||'MYS'}};const {data,error}=await SB.rpc('atomic_save_profile',{p_company_id:co.id,p_version:co._v,p_profile:p});if(error||!data)return toast('Profile not saved: '+(error?.message||'Unknown error'),'err');if(!atomicApply(co,data,before))return;toast('Test profile saved');rerender()}
"""+html[end:]
    start=html.index("function delProd(id){")
    end=html.index("/* ================= Payments ================= */",start)
    html=html[:start]+"""function delProd(id){const co=CO(),p=co?.products.find(x=>x.id===id);if(!p||!can('Edit Draft'))return toast('Not allowed to delete item','err');confirmBox('Delete test item?','Existing invoices keep their lines.','Delete',()=>vpsDeleteRecord(co,'products',p),true)}
async function vpsDeleteRecord(co,kind,record){if(CO()?.id!==co.id||!can('Edit Draft')||!(await atomicReady(co)))return;const before=coBody(co);const {data,error}=await SB.rpc('atomic_delete_record',{p_company_id:co.id,p_kind:kind,p_expected:clone(record)});if(error||!data)return toast('Deletion rejected: '+(error?.message||'Unknown error'),'err');if(!atomicApply(co,data,before))return;toast('Test record deleted');if(kind==='invoices')go('#/app/invoices');else rerender()}
"""+html[end:]
    start=html.index("function delInvoice(id){")
    end=html.index("function cancelModal(id){",start)
    html=html[:start]+"""function delInvoice(id){const co=CO(),inv=co?.invoices.find(x=>x.id===id);if(!inv||!can('Edit Draft'))return toast('Not allowed to delete invoice','err');if(locked(inv)||inv.lhdn?.attempts?.length||inv.payments?.length)return toast('Protected invoice','err');confirmBox('Delete test draft?','Only an unpaid, unsubmitted test invoice can be deleted.','Delete',()=>vpsDeleteRecord(co,'invoices',inv),true)}
"""+html[end:]
    start=html.index("function atomicApply(co,result,before){")
    end=html.index("async function cloudLoad",start)
    html=html[:start]+"""function atomicApply(co,result,before){
 if(!result||!result.company_data||!Number.isInteger(result.version)||result.company_data.vpsSyntheticWriteTest!==true)return false;
 if(JSON.stringify(coBody(co))!==JSON.stringify(before)){toast('Record saved; local changes occurred. Reload before continuing.','err');return false}
 for(const k of ['customers','products','invoices'])co[k]=clone(result.company_data[k]||[]);
 for(const k of ['name','tin','brn','sst','ttx','msic','msicDesc','email','phone','addr'])if(Object.prototype.hasOwnProperty.call(result.company_data,k))co[k]=clone(result.company_data[k]);
 co.nextNo=result.company_data.nextNo;co._v=result.version;
 BASELINES[co.id]=clone(coBody(co));PUSHED[co.id]=fnv(JSON.stringify(coBody(co)));UNSYNCED_CLOUD=false;
 return true;
}
"""+html[end:]
    html=once(html,"PRIVATE VPS PREVIEW — READ ONLY — Changes, email and LHDN submissions disabled","PRIVATE VPS WRITE TEST — SYNTHETIC DATA ONLY — Draft invoices, customers, products and manual payments. Other writes disabled.")
    cfg=(TARGET/"config.js").read_text()
    cfg=once(cfg,'"atomicRecordWrites": false','"atomicRecordWrites": true')
    with tempfile.TemporaryDirectory(dir=DEST.parent) as tmp:
        root=Path(tmp)
        for p in TARGET.iterdir():
            if p.is_file(): shutil.copy2(p,root/p.name)
        (root/"index.html").write_text(html)
        (root/"config.js").write_text(cfg)
        DEST.mkdir(mode=0o700,exist_ok=True)
        for p in root.iterdir(): os.replace(p,DEST/p.name)
    print("VPS_ORIGINAL_UI_SYNTHETIC_WRITE_BUILD_OK")
if __name__=="__main__":
    main()
