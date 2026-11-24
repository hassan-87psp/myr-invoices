/* MYR Invoice: network-only service worker. No Cache Storage, no offline invoice data. */
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{
 const req=event.request;
 if(req.method!=='GET'||req.mode!=='navigate'||new URL(req.url).origin!==self.location.origin)return;
 event.respondWith(fetch(req,{cache:'no-store'}).catch(()=>new Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MYR Invoice — Offline</title><body style="font-family:system-ui;background:#f3f6fb;color:#102442;padding:28px"><h1>MYR Invoice</h1><h2>You are offline</h2><p>Connect to the internet to securely access your invoices.</p><button onclick="location.reload()" style="padding:12px 20px;background:#125be4;color:white;border:0;border-radius:8px">Try again</button></body></html>',{status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}})));
});
