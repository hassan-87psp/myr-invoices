'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const base='https://myrinvoice.com';
const sitemap=fs.readFileSync('sitemap.xml','utf8');
const urls=[...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map(x=>x[1]);
assert.equal(urls.length,7);
assert.equal(new Set(urls).size,urls.length);
const home=fs.readFileSync('index.html','utf8');
for(const url of urls){
 const p=new URL(url);
 assert.equal(p.origin,base);
 const file=p.pathname==='/'?'index.html':p.pathname.slice(1)+'index.html';
 const html=fs.readFileSync(file,'utf8');
 assert.ok(html.includes('rel="canonical" href="'+url+'"'),file+' canonical');
 assert.ok(/<title>[^<]+<\/title>/.test(html),file+' title');
 assert.ok(/<meta name="description" content="[^"]+"/.test(html),file+' description');
 assert.ok(/<h1>/.test(html),file+' initial heading');
 for(const m of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g))JSON.parse(m[1]);
 if(p.pathname!=='/')assert.ok(home.includes('href="'+p.pathname+'"'),file+' linked from homepage');
}
assert.ok(fs.readFileSync('robots.txt','utf8').includes('Sitemap: '+base+'/sitemap.xml'));
console.log('SEO validation passed: '+urls.length+' crawlable public URLs');
