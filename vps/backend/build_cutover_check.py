"""Build the current public UI into a separate business-cutover rehearsal.
No changes to the live root, no auth grants, no production write enablement.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path
import build_hybrid_preview as hybrid
import build_write_preview as write
import build_business_candidate as business

def main():
    root=Path.home()/"myr-staging"
    root.mkdir(mode=0o700,exist_ok=True)
    target=Path(os.environ.get("MYR_CANDIDATE_DIR",str(root/"cutover-check")))
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        base=Path(tmp)
        hybrid.TARGET=base/"hybrid"
        write.TARGET=hybrid.TARGET
        write.DEST=base/"write"
        business.SYNTHETIC=write.DEST
        business.TARGET=base/"candidate"
        hybrid.main(grant=False)
        write.main()
        business.main()
        html=(business.TARGET/"index.html").read_text()
        assert "from:()=>{throw new Error(" in html
        assert "/hybrid/test-" not in html
        assert "/hybrid/write-workspace" not in html
        for attrs,code in re.findall(r'<script([^>]*)>(.*?)</script>',html,re.S|re.I):
            if code.strip() and 'application/ld+json' not in attrs and 'application/json' not in attrs:
                subprocess.run(["node","--check","-"],input=code,text=True,check=True)
        target.mkdir(mode=0o700,exist_ok=True)
        for path in business.TARGET.iterdir():
            os.replace(path,target/path.name)
    print("MYR_CURRENT_UI_CUTOVER_BUILD_OK")
    print("Current source UI built with VPS business APIs, no direct Supabase business data access.")
    print("Still read-only; unsupported workflows and external services are not released.")
if __name__=="__main__":
    main()
