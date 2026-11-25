"""Build isolated original-UI preview. Never edit the production index/config."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from hybrid_workspace import APP_ROOT, ORIGIN, GRANT, config
from app import connect

TARGET=Path.home()/ "myr-staging"/"hybrid-website"
def once(text,old,new):
    if text.count(old)!=1:
        raise SystemExit("Frontend anchor changed: "+old[:90])
    return text.replace(old,new,1)

def main():
    html=(APP_ROOT/"index.html").read_text()
    html=once(html,"SB=window.supabase.createClient(CFG.supabaseUrl,CFG.supabaseAnonKey);", """const client=window.supabase.createClient(CFG.supabaseUrl,CFG.supabaseAnonKey,{auth:{persistSession:false,detectSessionInUrl:false}});const blocked=async()=>({data:null,error:new Error('Not available in read-only VPS staging')});SB={auth:{getSession:client.auth.getSession.bind(client.auth),getUser:client.auth.getUser.bind(client.auth),signInWithPassword:client.auth.signInWithPassword.bind(client.auth),signOut:()=>client.auth.signOut({scope:'local'}),onAuthStateChange:client.auth.onAuthStateChange.bind(client.auth),signUp:blocked,updateUser:blocked,resetPasswordForEmail:blocked},from:()=>{throw new Error('Direct cloud data access blocked in VPS staging')},rpc:blocked};""")
    start=html.index(" await SB.rpc('accept_invites');",html.index("async function cloudLoad"))
    end=html.index(" DB.companies=rows.map",start)
    html=html[:start]+""" const session=(await SB.auth.getSession()).data.session;
 if(!session)throw new Error('Please sign in');
 const response=await fetch('/hybrid/workspace',{headers:{Authorization:'Bearer '+session.access_token},cache:'no-store'});
 if(!response.ok)throw new Error('VPS workspace access denied or unavailable ('+response.status+')');
 const result=await response.json();if(result.mode!=='read_only'||result.profile.id!==u.id)throw new Error('Workspace identity mismatch');
 PROFILE=result.profile;DB.session=email;DB.users=[{email,name:PROFILE.name||email.split('@')[0]}];
 const rows=result.companies,mem={data:result.members},docs={data:result.documents},links={data:[]};
"""+html[end:]
    html=once(html,"function save(){if(CLOUD)", "function save(){return;/* Read-only preview: no persistence. */if(CLOUD)")
    html=once(html,"async function cloudPush(){", "async function cloudPush(){return true;/* Read-only preview: no network writes. */")
    html=once(html,"const LHDN={base(co){","const LHDN={base(co){return '';/* All LHDN network calls disabled. */")
    html=once(html,"if('serviceWorker' in navigator&&location.protocol==='https:')","if(false&&'serviceWorker' in navigator&&location.protocol==='https:')")
    html=once(html,"</body>",'<div style="position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#172554;color:white;text-align:center;padding:7px;font:13px system-ui">PRIVATE VPS PREVIEW — READ ONLY — Changes, email and LHDN submissions disabled</div></body>')
    TARGET.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TARGET.parent) as tmp:
        root=Path(tmp)
        (root/"index.html").write_text(html)
        (root/"config.js").write_text("window.MYR_CONFIG = "+json.dumps({"supabaseUrl":ORIGIN,"supabaseAnonKey":config(),"allowDemo":False,"atomicRecordWrites":False})+";")
        for f in ("concurrency.js","klcc-skyline.webp","myr-auth-night.svg","pwa-icon-192.png","pwa-icon-512.png","manifest.webmanifest","seo.css"):
            if (APP_ROOT/f).is_file(): shutil.copy2(APP_ROOT/f,root/f)
        (root/"robots.txt").write_text("User-agent: *\nDisallow: /\n")
        TARGET.mkdir(mode=0o700,exist_ok=True)
        for p in root.iterdir(): os.replace(p,TARGET/p.name)
    print("ORIGINAL_UI_PRIVATE_BUILD_OK")
    with connect() as conn:
        rows=conn.execute("""SELECT DISTINCT u.id,u.email FROM myr_native.users u
            JOIN myr_native.company_members m ON m.email=u.email
            WHERE u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin AND m.role='Owner' AND m.status='active'""").fetchall()
    if len(rows)!=1:
        print("No unique imported owner; hybrid grant not changed")
        return
    uid,email=rows[0]
    print("Read-only preview candidate:",email)
    if GRANT.is_file() and GRANT.read_text().strip()==str(uid):
        print("HYBRID_OWNER_GRANT_ALREADY_CONFIGURED")
    elif input("Allow this existing owner to view the VPS snapshot after verified Supabase login? Type YES or press Enter to skip: ").strip()=="YES":
        fd,name=tempfile.mkstemp(dir=GRANT.parent,prefix=".hybrid-")
        with os.fdopen(fd,"w") as f: f.write(str(uid)+"\n")
        os.replace(name,GRANT)
        print("HYBRID_OWNER_READ_ONLY_GRANTED")
    else: print("HYBRID_OWNER_GRANT_NOT_ENABLED")

if __name__=="__main__":
    main()
