"""Secret-free GitHub release gate. Does not connect to VPS, database or providers."""
import ast, json, re, subprocess, sys, hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def run(*args,**kwargs):
    subprocess.run([str(a) for a in args],cwd=ROOT,check=True,timeout=120,**kwargs)

def manifest_check():
    path=ROOT/"vps/approved-frontend-releases.json"
    m=json.loads(path.read_text())
    assert set(m)=={"version","releases"} and m["version"]==1
    assert isinstance(m["releases"],list) and len(m["releases"])<=100
    seen=set()
    for r in m["releases"]:
        assert set(r)=={"id","replacements"} and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}",r["id"])
        assert r["id"] not in seen
        seen.add(r["id"])
        assert 0<len(r["replacements"])<=50
        for p in r["replacements"]:
            assert set(p)=={"old","new"} and all(isinstance(v,str) and v for v in p.values())
            assert p["old"]!=p["new"] and len(p["old"])<=100000 and len(p["new"])<=150000
    print("MYR_APPROVED_MANIFEST_VALID",flush=True)

def sandbox_admin_check():
    # Extract the real route body without importing the production DB/auth stack.
    from types import SimpleNamespace
    from unittest.mock import Mock
    tree=ast.parse((ROOT/"vps/backend/business_api.py").read_text())
    route=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="admin_dashboard")
    route.decorator_list=[]
    route.args.defaults=[]
    for arg in route.args.args:
        arg.annotation=None
    conn=Mock()
    auth=Mock(side_effect=PermissionError("admin required"))
    dashboard=Mock(return_value={})
    production=Mock(return_value={"environment":"production","submission_enabled":False})
    sandbox=Mock(return_value={"environment":"sandbox","credentials_configured":True,
                               "connection_check_enabled":True,"submission_enabled":False})
    scope=dict(admin_identity=auth,dashboard=dashboard,
               central_lhdn=SimpleNamespace(configuration_status=production,
                                             sandbox_configuration_status=sandbox))
    exec(compile(ast.Module(body=[route],type_ignores=[]),"<isolated-route>","exec"),scope)
    try:
        scope["admin_dashboard"](object(),conn)
    except PermissionError:
        pass
    else:
        raise AssertionError("Non-admin route should fail")
    production.assert_not_called()
    sandbox.assert_not_called()
    dashboard.assert_not_called()
    auth.side_effect=None
    auth.return_value={"is_platform_admin":True}
    result=scope["admin_dashboard"](object(),conn)["central_lhdn"]
    assert result["environment"]=="production" and result["submission_enabled"] is False
    assert result["sandbox"]["environment"]=="sandbox" and result["sandbox"]["submission_enabled"] is False
    production.assert_called_once_with()
    sandbox.assert_called_once_with()
    # Execute the actual private frontend JS in Node with safe presentation stubs.
    t=ast.parse((ROOT/"vps/backend/build_lhdn_candidate.py").read_text())
    js=next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign)
            and any(isinstance(x,ast.Name) and x.id=="JS" for x in n.targets))
    run("node","--check","-",input=js,text=True)
    run("node","-",input="const ic=()=>''; const esc=String;\n"+js+r"""
const absent=myrCentralAdmin({});
const ready=myrCentralAdmin({central_lhdn:{bridge_reachable:true,connection_check_enabled:false,
 sandbox:{bridge_reachable:true,credentials_configured:true,connection_check_enabled:true}}});
if(!absent.includes('Sandbox testing readiness') || !absent.includes('Unknown')) throw Error('Missing safe fallback');
if(!ready.includes('Not verified by configuration check') || !ready.includes('Invoice submission') ||
 !ready.includes('No documents will be submitted.') || !ready.includes('<dd>Configured</dd>') ||
 !ready.includes('<dd>Enabled</dd>') || !ready.includes('<dd>Disabled</dd>')) throw Error('Readiness rendering incorrect');
""",text=True)
    print("MYR_SANDBOX_ADMIN_READINESS_OK",flush=True)

def onboarding_check():
    html=(ROOT/"index.html").read_text()
    m=json.loads((ROOT/"vps/approved-frontend-releases.json").read_text())
    rel=next(r for r in m["releases"] if r["id"]=="business-onboarding-friendly-v1")
    for p in rel["replacements"]:
        assert html.count(p["new"])==1
    helper=html[html.index("const MYR_OB_MSIC="):html.index("function vOnboarding(){")]
    fixture=r"""
const els={};
const $=id=>els[id]??=( {value:'',disabled:false,required:false,hidden:false,textContent:'',innerHTML:'',reportValidity:()=>true} );
const val=id=>$('#'+id).value.trim();
const opt=(list)=>JSON.stringify(list);
const TIN_RE=/^C[0-9]{8,12}$/;
let saved=0,errors=[];
const toast=m=>errors.push(m);
const saveOnboard=async()=>{saved++};
"""
    tests=r"""
(async()=>{
if(MYR_OB_MSIC.length!==1175 || new Set(MYR_OB_MSIC.map(r=>r[0])).size!==1174)throw Error('MSIC data count');
if(myrObMatches('01111')[0]?.desc!=='Growing of maize'||!myrObMatches('programming').some(x=>x.code==='62010'))throw Error('MSIC search');
$('#ob-msic-search').value='01111';myrObSearch();
if(val('ob-msic')!=='01111'||val('ob-msicd')!=='Growing of maize')throw Error('Code/description selection');
$('#ob-sst-status').value='yes';myrObSst();
if(!$('#ob-sst').required||$('#ob-sst').disabled||$('#ob-sst-wrap').hidden)throw Error('SST yes');
$('#ob-sst').value='SST123';
$('#ob-sst-status').value='no';myrObSst();
if(val('ob-sst')!=='NA'||!$('#ob-sst').disabled||!$('#ob-sst-wrap').hidden)throw Error('SST no');
$('#myr-onboard-fields').querySelectorAll=()=>[];
$('#ob-tin').value='C1234567890';const btn={disabled:false,isConnected:true};
await myrObSubmit(btn);
if(saved!==1||btn.disabled)throw Error('Submit must preserve original handler');
$('#ob-sst-status').value='yes';myrObSst();await myrObSubmit(btn);
if(saved!==1||!errors.at(-1).includes('SST'))throw Error('SST missing gate');
$('#ob-msic-search').value='zzzz-no-match';myrObSearch();
$('#ob-msic-select').value='';myrObSelect();
if(val('ob-msic')||val('ob-msicd'))throw Error('Stale MSIC');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run("node","-",input=fixture+helper+tests,text=True)
    for marker in ("Tax Identification Number (TIN)","Business Registration Number (BRN)",
                   "Malaysia Standard Industrial Classification (MSIC)","Where to find this?",
                   "Registered Business Address","Automatically uses your account email",
                   "Starter plan automatically selected","@media(max-width:560px)"):
        assert marker in html,marker
    print("MYR_GUIDED_ONBOARDING_OK",flush=True)

def sidebar_motion_check():
    html=(ROOT/"index.html").read_text()
    m=json.loads((ROOT/"vps/approved-frontend-releases.json").read_text())
    rel=next(r for r in m["releases"] if r["id"]=="workspace-sidebar-motion-v1")
    for p in rel["replacements"]:
        assert html.count(p["new"])==1
    js=html[html.index("function myrSideClamp("):html.index("function paint(html)")]
    fixture=r"""
const values={};let desktop=true;let innerWidth=1440;
const matchMedia=()=>({matches:desktop});
const localStorage={getItem:k=>values[k],setItem:(k,v)=>values[k]=v};
function element(){
 const attrs={},handlers={},children=[],classes=new Set(),props={};
 return {attrs,handlers,children,classes,props,classList:{add:k=>classes.add(k),toggle:(k,v)=>v?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)},
 style:{setProperty:(k,v)=>props[k]=v},setAttribute:(k,v)=>attrs[k]=v,
 append:e=>children.push(e),prepend:e=>children.unshift(e),querySelectorAll:()=>[],querySelector:()=>null,
 addEventListener:(k,f)=>handlers[k]=f,setPointerCapture:()=>{},getBoundingClientRect:()=>({width:desktop?Number(root.props['--myr-side-width'].replace('px','')):Number(root.props['--myr-drawer-width'].replace('px',''))})}
}
const root=element(),side=element(),top=element();root.querySelector=s=>s==='#side'?side:top;
const document={querySelector:()=>root,createElement:()=>element()};
"""
    tests=r"""
if(myrSideClamp(999,190,380)!==380||myrSideClamp(-5,190,380)!==190)throw Error('Width limits');
myrSideSetup();
const toggle=top.children[0],close=side.children[0],grip=side.children[1];
if(root.props['--myr-side-width']!=='252px'||toggle.attrs['aria-expanded']!=='true')throw Error('Default width');
toggle.onclick();if(!root.classes.has('myr-side-mini')||toggle.attrs['aria-expanded']!=='false'||!myrSideRead().mini)throw Error('Collapse persistence');
toggle.onclick();if(root.classes.has('myr-side-mini'))throw Error('Expand');
grip.handlers.pointerdown({button:0,pointerId:1,clientX:252,preventDefault(){}});
grip.handlers.pointermove({pointerId:1,clientX:350});grip.handlers.pointerup({pointerId:1});
if(myrSideRead().width!==350||root.props['--myr-side-width']!=='350px')throw Error('Pointer resize');
grip.handlers.keydown({key:'Home',preventDefault(){}});if(myrSideRead().width!==190)throw Error('Keyboard resize');
desktop=false;innerWidth=375;
grip.handlers.keydown({key:'End',preventDefault(){}});if(myrSideRead().drawer!==330||myrSideRead().width!==190)throw Error('Mobile bounds and independent width');
side.classes.add('open');close.onclick();if(side.classes.has('open'))throw Error('Drawer close');
values['myr.sidebar.v1']='broken';if(myrSideRead().width!==252)throw Error('Corrupt preferences');
"""
    run("node","-",input=fixture+js+tests,text=True)
    motion=html[html.index("function lpMotion(){"):html.index("function lpPhonePreview(){")]
    assert "lpMobileStatic(root,phone);return" not in motion
    assert "paused=media.matches" in motion
    assert ".ux-ref .ux-motion-toggle{display:none!important}" in html
    assert "myr-mobile-reveal" in html and "prefers-reduced-motion:no-preference" in html
    assert "desktop.matches" in html[html.index("function lpScrollMotion"):html.index("function lpMobileStatic")]
    print("MYR_SIDEBAR_MOTION_OK",flush=True)

def company_settings_check():
    html=(ROOT/"index.html").read_text()
    m=json.loads((ROOT/"vps/approved-frontend-releases.json").read_text())
    rel=next(r for r in m["releases"] if r["id"]=="company-settings-guided-v1")
    # Reconstruct the predecessor for its immutable release-manifest checks.
    previous=html
    successor=next(r for r in m["releases"] if r["id"]=="premium-company-settings-v1")
    for p in reversed(successor["replacements"]):
        assert previous.count(p["new"])==1
        previous=previous.replace(p["new"],p["old"],1)
    for p in rel["replacements"]:
        assert previous.count(p["new"])==1
    helpers=html[html.index("function myrStMsicOptions("):html.index("function vSettingsContent(){")]
    data=html[html.index("const MYR_OB_MSIC="):html.index("function vOnboarding(){")]
    fixture=r"""
const els={};const $=id=>els[id]??={value:'',textContent:'',hidden:false,disabled:false,required:false,innerHTML:'',reportValidity:()=>true};
const val=id=>$('#'+id).value.trim(),opt=list=>JSON.stringify(list),TIN_RE=/^C[0-9]{8,12}$/;
let permitted=true,errors=[],saved=[];const can=()=>permitted;const toast=m=>errors.push(m);
const saveSettings=async()=>saved.push({msic:val('st-msic'),desc:val('st-msicd'),sst:val('st-sst'),email:val('st-email'),ttx:val('st-ttx')});
"""
    tests=r"""
(async()=>{
$('#st-msic').value='62010';$('#st-msicd').value='Existing description';
$('#st-email').value='billing@example.invalid';$('#st-ttx').value='TTX123';$('#st-tin').value='C1234567890';
$('#st-sst-choice').value='yes';$('#st-sst-number').value='SST123';
$('#myr-st-profile').querySelectorAll=()=>[];
$('#st-msic-search').value='maize';myrStMsicSearch();
if(val('st-msic')!=='62010'||val('st-msicd')!=='Existing description')throw Error('Search silently changed saved data');
$('#st-msic-select').value='';myrStMsicSelect();if(val('st-msic')!=='62010')throw Error('Empty selection wiped saved activity');
const idx=MYR_OB_MSIC.findIndex(r=>r[0]==='01111');
$('#st-msic-select').value=String(idx);myrStMsicSelect();
if(val('st-msic')!=='01111'||val('st-msicd')!=='Growing of maize')throw Error('MSIC change');
const btn={disabled:false,isConnected:true};
await myrStSave(btn);if(saved.length!==1||saved[0].sst!=='SST123'||saved[0].ttx!=='TTX123'||saved[0].email!=='billing@example.invalid')throw Error('Existing fields not preserved');
$('#st-sst-choice').value='no';myrStSst();if(!$('#st-sst-number').disabled||!$('#st-sst-box').hidden)throw Error('SST no UI');
await myrStSave(btn);if(saved[1].sst!=='NA')throw Error('SST no payload');
$('#st-sst-choice').value='yes';myrStSst();if($('#st-sst-number').disabled||!$('#st-sst-number').required||val('st-sst-number')!=='SST123')throw Error('SST yes preserves input');
$('#st-sst-number').value='';await myrStSave(btn);if(saved.length!==2||!errors.at(-1).includes('Tax registration'))throw Error('Missing SST blocked');
permitted=false;$('#st-sst-number').value='SST123';await myrStSave(btn);if(saved.length!==2)throw Error('Role guard');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    run("node","-",input=fixture+data+helpers+tests,text=True)
    profile=html[html.index("function vSettingsContent(){"):html.index("function saveSettings(){")]
    for marker in ("Additional details (optional)","Tax Identification Number (TIN)","Business Registration Number (BRN)","Malaysia Standard Industrial Classification (MSIC)","myrStSave(this)","st-msicd","st-sst-number","st-ttx","st-email"):
        assert marker in profile,marker
    print("MYR_GUIDED_SETTINGS_OK",flush=True)

def premium_settings_check():
    html=(ROOT/"index.html").read_text()
    helper=html[html.index("function myrStMsicOptions("):html.index("function vSettingsContent(){")]
    data=html[html.index("const MYR_OB_MSIC="):html.index("function vOnboarding(){")]
    fixture=r"""
const els={};const $=id=>els[id]??={value:'',hidden:false,disabled:false,required:false,innerHTML:'',attrs:{},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},getAttribute(k){return this.attrs[k]},focus(){},reportValidity:()=>true};
const val=id=>$('#'+id).value.trim(),opt=list=>JSON.stringify(list),TIN_RE=/^C[0-9]{8,12}$/;
const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
let permitted=true;const can=()=>permitted;
const document={querySelectorAll:()=>pill};
const pill=['no','yes'].map(v=>({dataset:{stSst:v},attrs:{},setAttribute(k,x){this.attrs[k]=x}}));
"""
    tests=r"""
$('#st-msic').value='62010';$('#st-msicd').value='Saved activity';
myrStComboSearch('maize');
if($('#st-msic-results').hidden||!$('#st-msic-results').innerHTML.includes('01111')||$('#st-msic-search').attrs['aria-expanded']!=='true')throw Error('Search results');
if(val('st-msic')!=='62010'||val('st-msicd')!=='Saved activity')throw Error('Search must not mutate stored selection');
myrStComboClose();if(!$('#st-msic-results').hidden||val('st-msic-search')!=='62010 — Saved activity')throw Error('Restore selected activity');
const index=MYR_OB_MSIC.findIndex(r=>r[0]==='01111');myrStComboPick(index);
if(val('st-msic')!=='01111'||val('st-msicd')!=='Growing of maize'||!$('#st-msic-results').hidden)throw Error('Select official pair');
myrStComboSearch('nonexistent-z-xyz');if(!$('#st-msic-results').innerHTML.includes('No matching'))throw Error('Empty search');
myrStSstPill('yes');if(val('st-sst-choice')!=='yes'||$('#st-sst-number').disabled||pill[1].attrs['aria-pressed']!=='true')throw Error('SST yes');
$('#st-sst-number').value='ABC123';myrStSstPill('no');if(!$('#st-sst-number').disabled||!$('#st-sst-box').hidden||val('st-sst-number')!=='ABC123')throw Error('SST no preserves input');
permitted=false;myrStComboPick(0);myrStSstPill('yes');if(val('st-msic')!=='01111'||val('st-sst-choice')!=='no')throw Error('Permissions');
"""
    run("node","-",input=fixture+data+helper+tests,text=True)
    profile=html[html.index("function vSettingsContent(){"):html.index("function saveSettings(){")]
    for marker in ('role="combobox"','aria-controls="st-msic-results"','st-country','st-address-grid','st-danger','Save Changes','myrStHelp','data-st-sst'):
        assert marker in profile,marker
    assert 'id="st-msic-select"' not in profile
    assert 'id="st-email"' not in profile or "field('st-email'" in profile
    print("MYR_PREMIUM_SETTINGS_OK",flush=True)

def main():
    for p in sorted((ROOT/"vps/backend").rglob("*.py")):
        ast.parse(p.read_text(),filename=str(p))
    print("MYR_BACKEND_SYNTAX_OK",flush=True)
    for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",(ROOT/"index.html").read_text(),re.S|re.I):
        if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
            run("node","--check","-",input=code,text=True)
    for p in sorted((ROOT/"vps").glob("*.sh")):
        run("bash","-n",p)
    manifest_check()
    sandbox_admin_check()
    onboarding_check()
    sidebar_motion_check()
    company_settings_check()
    premium_settings_check()
    run(sys.executable,"-B",ROOT/"vps/check_legacy_deployment_guard.py")
    run(sys.executable,"-B",ROOT/"vps/check_validation_redaction.py")
    run(sys.executable,"-B",ROOT/"vps/check_security_regression.py")
    run(sys.executable,"-B",ROOT/"vps/check_public_seo.py")
    run(sys.executable,"-B",ROOT/"vps/backend/check_private_reliability.py","--selftest")
    run(sys.executable,"-B",ROOT/"vps/backend/check_pilot_preflight.py","--selftest")
    run("node",ROOT/"vps/check_account_link_scope.mjs")
    run("node",ROOT/"vps/check_invoice_rounding.mjs")
    run("node",ROOT/"vps/check_mobile_suggestions.mjs")
    # Explicit offline-only tests. No dynamic discovery or database-dependent test execution.
    for name in ("chip_subscription_policy_candidate.py","chip_billing_view_candidate.py","chip_revenue_report_candidate.py",
                 "lhdn_protocol_candidate.py","lhdn_ubl_candidate.py","lhdn_saved_invoice_candidate.py",
                 "lhdn_lifecycle_candidate.py","lhdn_readiness_candidate.py","lhdn_sandbox_poll_candidate.py"):
        run(sys.executable,"-B",ROOT/"vps/backend"/name)
    print("MYR_OFFLINE_RELEASE_GATE_OK",flush=True)
if __name__=="__main__":main()
