"""Private UI transform; not invoked by any live build or deploy script."""
import re
import subprocess
from pathlib import Path
from build_hybrid_preview import once

JS=r"""
async function myrOfflineReadiness(btn){
 const co=CO(),id=btn.dataset.invoice,inv=co?.invoices.find(x=>x.id===id);
 if(!co||!inv||btn.disabled||co.demo)return;
 const cid=co.id,version=co._v,total=calc(inv).total;
 if(!Number.isSafeInteger(version)||version<=0||!Number.isSafeInteger(total)||total<=0)return toast('Reload and check invoice totals.','warn');
 btn.disabled=true;
 const messages={offline_preview_ready:'Offline checks passed. LHDN authorization and submission are not enabled.',stale:'Invoice changed. Reload and try again.',identity_review_required:'Review your company identity.',existing_document:'An official document already exists.',invoice_review_required:'Review invoice details, customer identity and approval.'};
 try{
  const {data:{session}}=await SB.auth.getSession();
  if(!session)throw Error('Sign in required.');
  const r=await fetch('/api/myr/lhdn/readiness',{method:'POST',credentials:'same-origin',cache:'no-store',
   headers:myrAuthHeaders(session,true),body:JSON.stringify({p_company_id:cid,p_invoice_id:id,p_version:version,p_total_sen:total})});
  if(!r.ok)throw Error('Readiness check unavailable ('+r.status+').');
  const d=await r.json();
  if(d.submission_enabled!==false)throw Error('Unexpected readiness response.');
  if(CO()?.id===cid&&btn.isConnected)toast(messages[d.status]||'Readiness unavailable.','warn');
 }catch(e){if(CO()?.id===cid&&btn.isConnected)toast(e.message,'warn')}finally{btn.disabled=false}
}
"""
def transform(html):
    start=html.index("function vInvoiceView(id){")
    end=html.index("const acts=[];",start)
    html=html[:end]+html[end:].replace("const acts=[];","""const acts=[];
 if(!co.demo&&inv.docType==='01'&&inv.appStatus==='Ready'&&inv.lhdn?.status==='Not Submitted'&&can('Manage Settings'))
 acts.push('<button class="btn" type="button" data-invoice="'+esc(inv.id)+'" onclick="myrOfflineReadiness(this)">Check e-Invoice readiness</button>');""",1)
    return once(html,"function vInvoiceView(id){",JS+"\nfunction vInvoiceView(id){")

def main():
    # Read an already-built private native-auth candidate, never a live web root.
    source=Path.home()/"myr-staging/native-auth-ui-check.html"
    html=transform(source.read_text())
    for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
        if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
            subprocess.run(["node","--check","-"],input=code,text=True,check=True)
    target=source.with_name("lhdn-readiness-ui-check.html")
    target.write_text(html)
    target.chmod(0o600)
    print("MYR_LHDN_PRIVATE_UI_SYNTAX_OK")

if __name__=="__main__":
    main()
