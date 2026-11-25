"""Build a separate native-auth frontend rehearsal. Never publish or open gates."""
import os,re,subprocess,tempfile
from pathlib import Path
import build_cutover_check
from build_hybrid_preview import once

ADAPTER=r"""
const myrNativeBase='/api/myr/native/auth/';
async function myrNativeRequest(path,body){
 const r=await fetch(myrNativeBase+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 if(!r.ok){const err=new Error(r.status===401?'Invalid credentials or sign-in required':r.status===429?'Too many requests. Try again later.':'Account service unavailable ('+r.status+')');err.status=r.status;throw err}
 return r.json()
}
function myrNativeAuth(client){
 const legacy=client.auth;
 let nativeActive=false;
 const getSession=async()=>{try{const p=await myrNativeRequest('me');nativeActive=true;return {data:{session:{native:true,user:{id:p.id,email:p.email,user_metadata:{name:p.name}}}},error:null}}
 catch(e){if(![401,404,503].includes(e.status))return {data:{session:null},error:e};nativeActive=false;return legacy.getSession()}};
 return {
 getSession,
 getUser:async()=>{const r=await getSession();return {data:{user:r.data.session?.user||null},error:r.error}},
 signInWithPassword:async({email,password})=>{
  try{await myrNativeRequest('login',{email,password});nativeActive=true;await legacy.signOut({scope:'local'});const r=await getSession();if(!r.data.session?.native)throw new Error('Native session not established');return {data:{session:r.data.session,user:r.data.session.user},error:null}}
  catch(e){if(!nativeActive&&[401,404,503].includes(e.status))return legacy.signInWithPassword({email,password});return {data:null,error:e}}},
 signOut:async()=>{try{if(nativeActive)await myrNativeRequest('logout',{});nativeActive=false;return legacy.signOut({scope:'local'})}catch(e){return {error:e}}},
 onAuthStateChange:(cb)=>legacy.onAuthStateChange((ev,s)=>{if(!nativeActive)cb(ev,s)}),
 signUp:async({email})=>{try{await myrNativeRequest('signup',{email});return {data:{session:null},error:null}}catch(e){return {data:null,error:e}}},
 resetPasswordForEmail:async(email)=>{try{await myrNativeRequest('reset-request',{email});return {data:{},error:null}}catch(e){return {data:null,error:e}}},
 updateUser:async()=>({data:null,error:new Error('Use Forgot password to change your password')})
 }
}
const myrAuthHeaders=(session,json=false)=>({...(!session.native?{Authorization:'Bearer '+session.access_token}:{}),...(json?{'Content-Type':'application/json'}:{})});
let MYR_FINISH_TOKEN='';
function myrFinishView(action){
 const labels={'verify-email':'Verify email and create account','reset-password':'Choose your new password','activate':'Activate your account'};
 if(!Object.hasOwn(labels,action))return vAuth('login');
 const token=new URLSearchParams(location.hash.split('?')[1]||'').get('token');
 if(token&&/^[A-Za-z0-9_-]{43}$/.test(token)){MYR_FINISH_TOKEN=token;history.replaceState(null,'','#/auth/'+action)}
 document.title=labels[action]+' — MYR Invoice';
 return '<div class="mobile-page"><div class="box" style="max-width:480px"><div class="card pad"><a href="#/" aria-label="MYR Invoice home">'+LOGO(40)+'</a><h1>'+labels[action]+'</h1><p class="muted mt8">Use at least 12 characters for your password.</p><div id="auth-err" aria-live="polite"></div><form onsubmit="event.preventDefault();myrFinishSubmit(\''+action+'\')">'+(action==='verify-email'?field('finish-name','Full name','','text','required maxlength="120" autocomplete="name"'):'')+field('finish-password','New password','','password','required minlength="12" maxlength="128" autocomplete="new-password"')+field('finish-confirm','Confirm password','','password','required minlength="12" maxlength="128" autocomplete="new-password"')+'<button class="btn p" type="submit">Continue</button></form><p class="mt8"><a href="#/login">Back to sign in</a></p></div></div></div>'
}
async function myrFinishSubmit(action){
 const btn=document.querySelector('#app form button[type=submit]');if(!btn||btn.disabled)return;
 const pw=val('finish-password'),confirm=val('finish-confirm'),name=val('finish-name');
 if(!MYR_FINISH_TOKEN)return authErr('Open the secure link from your email again.');
 if(pw.length<12||pw!==confirm)return authErr('Passwords must match and contain at least 12 characters.');
 btn.disabled=true;try{await myrNativeRequest(action,{token:MYR_FINISH_TOKEN,password:pw,name});MYR_FINISH_TOKEN='';go('#/login');toast('Account updated. Please sign in.')}catch(e){authErr(e.message)}finally{btn.disabled=false}
}
"""
def transform(html):
    # Do not manufacture a bearer token for cookie sessions.
    html=once(html,"async function cloudInit(publicOnly){",ADAPTER+"\nasync function cloudInit(publicOnly){")
    first=html.index("SB={auth:{getSession:client.auth.getSession")
    last=html.index("},from:()=>{throw new Error(",first)
    html=html[:first]+"SB={auth:myrNativeAuth(client)"+html[last+1:]
    html=once(html,"const session=(await client.auth.getSession()).data.session;if(!session)throw new Error('Sign in required');","const session=(await SB.auth.getSession()).data.session;if(!session)throw new Error('Sign in required');")
    assert html.count("headers:{Authorization:'Bearer '+session.access_token,'Content-Type':'application/json'}")>=1
    html=html.replace("headers:{Authorization:'Bearer '+session.access_token,'Content-Type':'application/json'}","headers:myrAuthHeaders(session,true)")
    assert html.count("headers:{Authorization:'Bearer '+session.access_token}")>=3
    html=html.replace("headers:{Authorization:'Bearer '+session.access_token}","headers:myrAuthHeaders(session)")
    html=once(html,"fetch('/api/myr/team/accept',{method:'POST',headers:myrAuthHeaders(session),cache:'no-store'})","fetch('/api/myr/team/accept',{method:'POST',headers:myrAuthHeaders(session,true),body:'{}',cache:'no-store'})")
    # Signup is email-first. Password is entered after verification.
    html=once(html,"const name=val('su-name'),email=val('su-email').toLowerCase(),pw=$('#su-pw').value;if(!name)return authErr('Enter your name.');","const name='',email=val('su-email').toLowerCase(),pw='';")
    html=once(html,"if(pw.length<8)return authErr('Password must be at least 8 characters.');","")
    html=once(html,"${su?myrAuthField('su-name','Full name','text','users','name',''):''}","")
    html=once(html,"${myrAuthField(su?'su-pw':'li-pw','Password','password','lock',su?'new-password':'current-password','')}","${su?'':myrAuthField('li-pw','Password','password','lock','current-password','')}")
    html=once(html,"Account created. Please check your email and click the verification link, then log in.","If eligible, a verification email has been sent. Open the link to choose your password and complete your account.")
    html=once(html,"['app','admin','login','signup','r','v'].includes(p[0])","['app','admin','login','signup','auth','r','v'].includes(p[0])")
    html=once(html,"if(p[0]==='login'||p[0]==='signup')return paint(vAuth(p[0]));","if(p[0]==='auth')return paint(myrFinishView(p[1]));if(p[0]==='login'||p[0]==='signup')return paint(vAuth(p[0]));")
    html=once(html,"await SB.auth.signOut();myrDraftClearAll();","const signedOut=await SB.auth.signOut();if(signedOut.error)return toast('Sign-out failed. Retry.','err');myrDraftClearAll();")
    assert "from:()=>{throw new Error(" in html
    return html

def main():
    root=Path.home()/"myr-staging"
    root.mkdir(mode=0o700,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as d:
        os.environ["MYR_BUSINESS_API_PREFIX"]="/api/myr"
        os.environ["MYR_CANDIDATE_DIR"]=d
        build_cutover_check.main()
        html=transform((Path(d)/"index.html").read_text())
        for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
            if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
                subprocess.run(["node","--check","-"],input=code,text=True,check=True)
        # The rehearsal is not an installable production asset.
        target=root/"native-auth-ui-check.html"
        target.write_text(html)
        target.chmod(0o600)
    print("MYR_NATIVE_AUTH_UI_BUILD_OK (private file only)")

if __name__=="__main__": main()
