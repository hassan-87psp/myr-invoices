"""Small frontend-only startup fix; preserve the approved UI and crawlable SEO."""
import re,sys,subprocess
from pathlib import Path

BOOT=r"""
<style id="myr-fast-start-style">
#myr-fast-start{display:none}
html.myr-starting #app>.myr-seo-fallback{display:none}
html.myr-starting #myr-fast-start{display:grid;place-items:center;min-height:100vh;min-height:100svh;background:#f5f7fb;color:#0b1f3a;font-family:system-ui,-apple-system,Segoe UI,sans-serif}
#myr-fast-start .myr-start-box{display:grid;justify-items:center;gap:12px;text-align:center;padding:24px}
#myr-fast-start .myr-start-logo{width:48px;height:48px;display:block}
#myr-fast-start .myr-start-name{font-weight:750;font-size:23px;letter-spacing:-.5px}
#myr-fast-start .myr-start-msg{color:#64748b;font-size:13px;margin:0}
#myr-fast-start .myr-start-retry{display:none;color:#125be4;font-size:13px;text-decoration:underline}
html.myr-start-delayed #myr-fast-start .myr-start-retry{display:inline}
</style>
<script id="myr-fast-start-init">
(function(){
 var root=document.documentElement;
 root.classList.add('myr-starting');
 window.setTimeout(function(){
   var box=document.getElementById('myr-fast-start');
   if(!box)return;
   root.classList.add('myr-start-delayed');
   var message=box.querySelector('.myr-start-msg');
   if(message)message.textContent='Taking longer than expected. You can reload this page.';
 },10000);
})();
</script>
"""
SHELL=r"""<div id="myr-fast-start" role="status" aria-live="polite"><div class="myr-start-box"><img class="myr-start-logo" src="./pwa-icon-192.png" alt="" width="48" height="48" decoding="async"><div class="myr-start-name">MYR Invoice</div><p class="myr-start-msg">Opening MYR Invoice…</p><a class="myr-start-retry" href="#" onclick="location.reload();return false">Reload page</a></div></div>"""
def once(s,old,new):
    if s.count(old)!=1:raise ValueError("Unexpected startup anchor: "+old[:80])
    return s.replace(old,new,1)
def transform(html):
    if 'id="myr-fast-start-init"' in html:return html
    # The SEO fallback remains present in HTML and visible when JS is disabled.
    html=once(html,'<meta charset="utf-8">','<meta charset="utf-8">\n'+BOOT)
    pattern=r'(<link href="https://fonts\.googleapis\.com/css2\?[^"]+" rel="stylesheet">)'
    matches=list(re.finditer(pattern,html))
    if len(matches)!=1:raise ValueError("Unexpected font link")
    old=matches[0].group()
    new=old[:-1]+' media="print" onload="this.media=\'all\'"><noscript>'+old+'</noscript>'
    html=once(html,old,new)
    html=once(html,'<div id="app"><main class="myr-seo-fallback">','<div id="app">'+SHELL+'<main class="myr-seo-fallback">')
    html=once(html,"$('#app').innerHTML=html;","$('#app').innerHTML=html;document.documentElement.classList.remove('myr-starting','myr-start-delayed');")
    # No extra timers or session requests before route(); approved motion and auth UI remain intact.
    return html
def main():
    if len(sys.argv)!=2:raise SystemExit("Usage: patch_fast_start.py STAGED_INDEX")
    path=Path(sys.argv[1])
    original=path.read_text()
    result=transform(original)
    assert result.count('class="myr-seo-fallback"')==original.count('class="myr-seo-fallback"')
    assert 'id="myr-fast-start"' in result
    assert "myrNativeAuth" in original if "myrNativeAuth" in result else True
    for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",result,re.S|re.I):
        if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
            subprocess.run(["node","--check","-"],input=code,text=True,check=True)
    path.write_text(result)
    print("MYR_FAST_START_BUILD_OK")
if __name__=="__main__":main()
