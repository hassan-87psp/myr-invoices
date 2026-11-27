"""Generate public merchant policy pages. No backend, database or secret access."""
from pathlib import Path
from html import escape
import sys

pages={
"refund-policy":("Refund & Cancellation Policy",[
("Subscriptions","MYR Invoice offers digital software subscription plans. The applicable price, billing period and renewal terms must be shown before payment. Automatic renewal is available only where expressly authorized by the customer and enabled by our payment provider."),
("Cancellation","To cancel a subscription or prevent its next renewal, contact invoicesmyr@gmail.com before the next billing date. We will confirm the cancellation and any remaining access period. Cancelling does not automatically refund a previous charge."),
("Refund requests","Contact support with your payment reference, account email and reason for requesting a refund. Duplicate or unauthorized charges, incorrect amounts and paid services that were not supplied will be investigated. Refund eligibility is assessed on the circumstances and applicable Malaysian law. This policy does not limit statutory rights."),
("Refund processing","Approved refunds will be returned through the original payment method where possible. The payment provider and issuing bank determine when the funds become available. Do not send card numbers, passwords or verification codes to support."),
]),
"privacy-policy":("Privacy Policy",[
("About this notice","MYR Invoice is a business invoicing software service. This notice explains the processing of personal data for the service under Malaysia's Personal Data Protection Act 2010, as applicable."),
("Information processed","We may process account and contact information, company and tax identifiers, invoices and buyer records supplied by business users, payment references, access records and support correspondence. Business users should provide only information necessary for legitimate invoicing purposes."),
("Purposes and disclosures","Information is used to administer accounts, deliver invoicing and reporting features, support users, maintain security and comply with legal obligations. When enabled and authorized, relevant invoice data may be sent to LHDN MyInvois. Hosting and payment service providers may process information necessary to provide their services. Card payments are handled through the payment provider; do not submit card credentials to MYR Invoice support."),
("Security and retention","We use access controls and server-side credential handling. Records are retained as needed to deliver services, resolve disputes and meet applicable legal obligations. No system can guarantee absolute security."),
("Your choices and rights","Contact invoicesmyr@gmail.com to request access or correction, ask about processing, withdraw consent where applicable, or raise a privacy concern. Some information may need to be retained for lawful accounting or tax purposes. Requests are subject to identity verification and applicable law."),
]),
"shipping-policy":("Digital Service Delivery Policy",[
("Digital service only","MYR Invoice provides cloud-based invoicing software. No physical goods are shipped, and no shipping fees or physical delivery address are required for software subscriptions."),
("Access and activation","Access is provided through https://myrinvoice.com/ after account registration and any required verification. Paid features become available once a payment is verified and the subscription is activated. Features requiring LHDN authorization or provider approval are available only when those requirements are satisfied."),
("Delivery problems","If paid access is not available or a payment is pending, contact invoicesmyr@gmail.com with the account email and payment reference. Do not repeat a payment until its status has been checked."),
("Cancellation and refunds","See our Refund & Cancellation Policy for refund and cancellation requests."),
])}
root=Path(sys.argv[1])
if not root.is_dir():raise SystemExit("Existing web staging directory required")
nav=''.join(f'<a href="/{k}/">{escape(v[0])}</a>' for k,v in pages.items())
for slug,(title,sections) in pages.items():
    body=''.join(f'<section><h2>{escape(h)}</h2><p>{escape(p)}</p></section>' for h,p in sections)
    html=f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | MYR Invoice</title><link rel="canonical" href="https://myrinvoice.com/{slug}/">
<meta name="myr-policy-page" content="{slug}">
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6fb;color:#192b49;font:16px/1.7 system-ui,sans-serif}}header,footer{{background:#fff;border-bottom:1px solid #dce5f0}}.wrap{{max-width:850px;margin:auto;padding:18px 24px}}header a{{font-size:22px;font-weight:800;color:#1749cb;text-decoration:none}}main{{margin:36px auto;padding:0 16px;max-width:850px}}article{{background:#fff;border:1px solid #dce5f0;border-radius:18px;padding:clamp(20px,5vw,46px)}}h1{{line-height:1.2;font-size:clamp(28px,5vw,42px);margin:0 0 12px}}h2{{font-size:19px;margin:24px 0 6px}}p{{margin:0 0 12px}}a{{color:#164ac7}}.muted{{color:#52627a;font-size:14px}}nav{{display:flex;flex-wrap:wrap;gap:12px;font-size:14px}}footer{{border-top:1px solid #dce5f0}}
</style></head><body><header><div class="wrap"><a href="/">MYR Invoice</a></div></header><main><article><p class="muted">MYR INVOICE · CUSTOMER POLICIES</p><h1>{escape(title)}</h1><p class="muted">Last updated: 27 November 2026</p>{body}<section><h2>Contact</h2><p>Merchant: BINA FOREVER ENTERPRISE · SSM 201803149577<br>B-3-9, Oasis Square, Jalan PJU 1A/7A, Ara Damansara, 47301 Petaling Jaya, Selangor, Malaysia<br><a href="mailto:invoicesmyr@gmail.com">invoicesmyr@gmail.com</a></p></section></article></main><footer><div class="wrap"><nav>{nav}<a href="/">Home</a></nav></div></footer></body></html>'''
    folder=root/slug
    folder.mkdir(exist_ok=True)
    (folder/"index.html").write_text(html,encoding="utf-8")
    (folder/"index.html").chmod(0o644)
    folder.chmod(0o755)
print("MYR_POLICY_PAGES_GENERATED")
