"""Read-only check for the approved public PNG, without credentials."""
from urllib.request import urlopen
from hashlib import sha256
from struct import unpack
url="https://nynghaleoaqilewmhbdi.supabase.co/storage/v1/object/public/myr-email-brand/myr-invoice-logo.png"
try:
    with urlopen(url,timeout=15) as r:
        raw=r.read(1048577)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n") and 24<len(raw)<=1048576
    w,h=unpack(">II",raw[16:24])
    assert w>0 and h>0 and 2.5<w/h<5
except Exception:
    raise SystemExit("MYR_APPROVED_LOGO_MISSING_OR_INVALID: upload myr-invoice-logo.png to myr-email-brand") from None
print("MYR_LOGO_AVAILABLE",w,h,sha256(raw).hexdigest())
