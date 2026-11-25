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
    html=once(html,"rpc:blocked};","""rpc:async(name,args)=>{if(name!=='atomic_save_record')return blocked();try{const session=(await client.auth.getSession()).data.session;if(!session)throw new Error('Sign in required');const res=await fetch('/hybrid/test-record',{method:'POST',headers:{Authorization:'Bearer '+session.access_token,'Content-Type':'application/json'},body:JSON.stringify(args),cache:'no-store'});const data=await res.json();if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Record write rejected');return {data,error:null}}catch(error){return {data:null,error}}}};""")
    html=once(html,"fetch('/hybrid/workspace'","fetch('/hybrid/write-workspace'")
    html=once(html,"result.mode!=='read_only'","result.mode!=='synthetic_write'")
    html=once(html,"function save(){return;/* Read-only preview: no persistence. */","function save(){if(DB.companies.some(c=>c._v&&PUSHED[c.id]!==fnv(JSON.stringify(coBody(c))))){toast('This action is not connected in this rehearsal. Reload to discard local changes.','err');throw new Error('Unsupported rehearsal mutation')}return;/* Block all generic snapshot writes. */")
    html=once(html,"async function cloudPush(){return true;/* Read-only preview: no network writes. */","async function cloudPush(){return !DB.companies.some(c=>c._v&&PUSHED[c.id]!==fnv(JSON.stringify(coBody(c))));/* No generic snapshot writes. */")
    html=once(html,"if(CLOUD&&idx<0&&ED._autoNumber&&ED.number===ED._autoNumber){","if(false&&CLOUD&&idx<0&&ED._autoNumber&&ED.number===ED._autoNumber){")
    start=html.index("function atomicApply(co,result,before){")
    end=html.index("async function cloudLoad",start)
    html=html[:start]+"""function atomicApply(co,result,before){
 if(!result||!result.company_data||!Number.isInteger(result.version)||result.company_data.vpsSyntheticWriteTest!==true)return false;
 if(JSON.stringify(coBody(co))!==JSON.stringify(before)){toast('Record saved; local changes occurred. Reload before continuing.','err');return false}
 for(const k of ['customers','products','invoices'])co[k]=clone(result.company_data[k]||[]);
 co.nextNo=result.company_data.nextNo;co._v=result.version;
 BASELINES[co.id]=clone(coBody(co));PUSHED[co.id]=fnv(JSON.stringify(coBody(co)));UNSYNCED_CLOUD=false;
 return true;
}
"""+html[end:]
    html=once(html,"PRIVATE VPS PREVIEW — READ ONLY — Changes, email and LHDN submissions disabled","PRIVATE VPS WRITE TEST — SYNTHETIC DATA ONLY — Draft invoices, customers and products. Other writes disabled.")
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
