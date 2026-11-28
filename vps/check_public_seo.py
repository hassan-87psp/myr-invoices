"""Offline SEO integrity check: public source files only, no network."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
import json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE="https://myrinvoice.com"
class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.canonical=[];self.meta={};self.links=[];self.h1=0;self.title=[];self.in_title=False;self.schemas=[];self.schema=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="link" and a.get("rel")=="canonical":self.canonical.append(a.get("href"))
        if tag=="meta" and ("name" in a or "property" in a):self.meta[a.get("name",a.get("property"))]=a.get("content")
        if tag=="a":self.links.append(a.get("href",""))
        if tag=="h1":self.h1+=1
        if tag=="title":self.in_title=True
        if tag=="script" and a.get("type")=="application/ld+json":self.schema=""
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        if self.schema is not None:self.schema+=data
    def handle_endtag(self,tag):
        if tag=="title":self.in_title=False
        if tag=="script" and self.schema is not None:
            self.schemas.append(json.loads(self.schema));self.schema=None
def main():
    urls=[x.text for x in ET.parse(ROOT/"sitemap.xml").getroot().findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert len(urls)==len(set(urls)) and BASE+"/" in urls
    assert "Sitemap: "+BASE+"/sitemap.xml" in (ROOT/"robots.txt").read_text()
    titles=set();descriptions=set()
    manifest=json.loads((ROOT/"vps/approved-frontend-releases.json").read_text())
    for url in urls:
        u=urlsplit(url);assert u.scheme=="https" and u.netloc=="myrinvoice.com" and not u.query and not u.fragment
        assert u.path.endswith("/") and ".." not in u.path
        raw=(ROOT/u.path.strip("/")/"index.html").read_text()
        if u.path=="/":
            for release in manifest["releases"]:
                if release["id"] in ("seo-homepage-metadata-v1","seo-rendered-title-v1"):
                    for p in release["replacements"]:
                        assert raw.count(p["old"])==1,release["id"]
                        raw=raw.replace(p["old"],p["new"],1)
        page=Page();page.feed(raw)
        title="".join(page.title).strip();desc=page.meta.get("description","")
        assert title and title not in titles and desc and desc not in descriptions,url
        titles.add(title);descriptions.add(desc)
        assert page.canonical==[url] and page.meta.get("og:url")==url,url
        assert page.meta.get("og:title")==title and page.meta.get("twitter:title")==title,url
        assert page.meta.get("og:description")==desc and page.meta.get("twitter:description")==desc,url
        assert page.h1==1 and page.schemas and "noindex" not in page.meta.get("robots",""),url
        # Each public resource links to all other resource pages.
        assert all(urlsplit(other).path in page.links for other in urls if other!=url),url
    print("MYR_PUBLIC_SEO_SOURCE_OK",len(urls),"pages (not a Google indexing check)")
if __name__=="__main__":main()
