"""Billing UI transform for an isolated native frontend build.
Never installs assets or enables production payment operations.
"""
from pathlib import Path
import re,subprocess,sys

JS=r"""
async function myrBillingRequest(path,body){
 const session=(await SB.auth.getSession()).data.session;
 if(!session||typeof myrAuthHeaders!=='function')throw Error('Sign in required');
 const options={method:body?'POST':'GET',headers:myrAuthHeaders(session,!!body),cache:'no-store',credentials:'same-origin'};
 if(body)options.body=JSON.stringify(body);
 const response=await fetch('/api/myr/billing/'+path,options);
 if(!response.ok)throw Error(response.status===503?'Billing service not released.':'Billing request unavailable ('+response.status+').');
 return response.json();
}
function myrBillingHistoryPanel(){
 return '<div class="card mt"><div class="ch"><h3>Payment history</h3><button class="btn sm" onclick="myrLoadBillingHistory(this)">Refresh</button></div><div id="myr-billing-history" class="pad" role="status">Select Refresh to load verified billing records. Online payments and automatic renewal are not released yet.</div></div>';
}
async function myrLoadBillingHistory(btn){
 const node=document.getElementById('myr-billing-history'),co=CO();
 if(!node||!co||!can('Access Billing'))return;
 btn.disabled=true;node.textContent='Loading billing records…';
 try{
  const d=await myrBillingRequest('customer/'+encodeURIComponent(co.id));
  if(!node.isConnected||CO()?.id!==co.id)return;
  const rows=Array.isArray(d.history)?d.history:[];
  node.innerHTML=rows.length?'<div class="tw"><table class="t"><thead><tr><th>Period</th><th>Plan</th><th>Amount</th><th>Status</th></tr></thead><tbody>'+rows.map(x=>'<tr><td>'+esc(String(x.period_start||''))+'</td><td>'+esc(String(x.plan||''))+'</td><td>'+esc(money(Number(x.amount_sen)||0))+'</td><td>'+esc(x.status==='recorded_paid'?'Manually recorded paid':'Unpaid')+'</td></tr>').join('')+'</tbody></table></div>':'No billing records yet.';
 }catch(e){if(node.isConnected)node.textContent=e.message;}finally{btn.disabled=false}
}
function myrChipAdminPanel(rows){
 const companies=Array.isArray(rows)?rows.filter(x=>x.status==='active'):[];
 return '<section class="card pad mt"><div class="row sb"><h3>CHIP sandbox payments</h3><span class="badge b-warn">Test only</span></div><p class="muted sm mt8">Live charges are disabled. Test receipts never activate a real subscription or count as revenue.</p><div class="grid g2 mt"><label>Company<select id="myr-chip-company" class="in"><option value="">Select company</option>'+companies.map(x=>'<option value="'+esc(x.id)+'">'+esc(x.name)+'</option>').join('')+'</select></label><label>Test plan<select id="myr-chip-plan" class="in"><option>Starter</option><option>Pro</option><option>Business</option></select></label></div><div class="row mt"><button class="btn p" onclick="myrChipAdminCreate(this)">Create sandbox checkout</button><button class="btn" onclick="myrChipAdminHistory(this)">Refresh history</button></div><div id="myr-chip-result" class="mt" role="status"></div><div id="myr-chip-history" class="mt"></div></section>';
}
const myrChipUuid=x=>typeof x==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(x);
async function myrChipAdminCreate(btn){
 const node=document.getElementById('myr-chip-result'),cid=document.getElementById('myr-chip-company')?.value,plan=document.getElementById('myr-chip-plan')?.value;
 if(!node||!myrChipUuid(cid)||!['Starter','Pro','Business'].includes(plan))return;
 if(!window.confirm('Create one CHIP sandbox checkout only? No real card or subscription charge.'))return;
 btn.disabled=true;node.textContent='Creating test checkout…';
 try{
  const d=await myrBillingRequest('admin/sandbox/checkout',{company_id:cid,plan});
  if(!node.isConnected)return;
  if(d.mode!=='test'||d.entitlement_changed!==false)throw Error('Unexpected checkout response.');
  if(d.status==='reconciliation_required'){node.textContent='Outcome unknown. Do not create another payment; reconcile this intent first.';return;}
  if(d.status!=='created'||!myrChipUuid(d.intent_id))throw Error('Unexpected checkout status.');
  const match=/^https:\/\/gate\.chip-in\.asia\/p\/([0-9a-f-]{36})\/$/i.exec(d.checkout_url||'');
  if(!match||!myrChipUuid(match[1]))throw Error('Unexpected checkout URL.');
  node.textContent='';
  const link=document.createElement('a');link.href=d.checkout_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open CHIP test checkout';link.className='btn p';node.append(link);
 }catch(e){if(node.isConnected)node.textContent=e.message+' Do not retry if the payment outcome is unknown.';}finally{btn.disabled=false}
}
async function myrChipAdminHistory(btn){
 const node=document.getElementById('myr-chip-history');
 if(!node)return;btn.disabled=true;node.textContent='Loading test payments…';
 try{
  const d=await myrBillingRequest('admin/sandbox');
  if(!node.isConnected)return;
  if(d.mode!=='test'||d.live_payments_enabled!==false)throw Error('Unexpected payment mode.');
  const rows=Array.isArray(d.test_history)?d.test_history:[];
  node.innerHTML='<p class="muted sm">Verified test payments: '+esc(String(d.test_paid_count||0))+' · Reconciliation required: '+esc(String(d.needs_reconciliation||0))+'</p>';
  const table=document.createElement('div');table.className='tw';
  table.innerHTML='<table class="t"><thead><tr><th>Plan</th><th>Amount</th><th>Status</th><th>Action</th></tr></thead><tbody></tbody></table>';
  const tbody=table.querySelector('tbody');
  for(const x of rows){
   const tr=document.createElement('tr');
   for(const value of [x.plan,money(Number(x.amount_sen)||0),x.state]){const td=document.createElement('td');td.textContent=String(value??'');tr.append(td);}
   const td=document.createElement('td');tr.append(td);
   if(x.state==='created'&&myrChipUuid(x.id)){const b=document.createElement('button');b.className='btn sm';b.textContent='Verify test payment';b.onclick=async()=>{b.disabled=true;try{const result=await myrBillingRequest('admin/sandbox/verify',{intent_id:x.id});b.textContent=result.status==='verified_test_paid'?'Verified test only':'Not paid';}catch(e){b.textContent='Verification unavailable';}finally{b.disabled=false}};td.append(b);}
   tbody.append(tr);
  }
  node.append(table);
 }catch(e){if(node.isConnected)node.textContent=e.message;}finally{btn.disabled=false}
}
"""
def once(html,before,after):
    if html.count(before)!=1:raise ValueError("Unexpected billing UI anchor")
    return html.replace(before,after,1)
def transform(html):
    html=once(html,"function vBilling(...args){",JS+"\nfunction vBilling(...args){")
    html=once(html,"<div class=\"card mt\"><div class=\"ch\"><h3>Billing history</h3></div>${empty('receipt','No billing records','Subscription payments appear here once the payment gateway is connected. No charges have been made.')}</div>","${myrBillingHistoryPanel()}")
    html=once(html,"k('Monthly recurring revenue',money(active.reduce((a,r)=>a+price(r.plan)*100,0)),'List price, active companies')","k('Plan list-price value',money(active.reduce((a,r)=>a+price(r.plan)*100,0)),'Not collected revenue')")
    html=once(html,"k('Active subscriptions',active.length,'')","k('Active companies',active.length,'Not verified paid')")
    html=once(html,"head('Subscriptions','Plans, recurring revenue and quota pressure.')+","head('Subscriptions','Plans, payment status and quota pressure.')+myrChipAdminPanel(R)+")
    return html
if __name__=="__main__":
    root=Path(__file__).resolve().parents[2]
    source=(root/"index.html").read_text()
    result=transform(source)
    for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",result,re.S|re.I):
        if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
            subprocess.run(["node","--check","-"],input=code,text=True,check=True)
    assert "Not collected revenue" in result and "Test receipts never activate" in result
    print("MYR_CHIP_BILLING_UI_BUILD_OK")
