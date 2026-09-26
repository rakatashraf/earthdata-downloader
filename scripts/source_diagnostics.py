import requests, json, re
from pprint import pprint

STAC="https://planetarycomputer.microsoft.com/api/stac/v1"
collections=["hls2-l30","modis-11A2-061","modis-13Q1-061","nasadem","hrea","gpm-imerg-hhr"]
bbox=[89.24,22.80,91.31,24.80]
for c in collections:
    print("\nCOLLECTION",c)
    r=requests.get(f"{STAC}/collections/{c}",timeout=30); print(r.status_code)
    if r.ok:
        j=r.json(); print("title",j.get("title")); print("assets",list((j.get("assets") or {}).keys()))
        s=requests.post(f"{STAC}/search",json={"collections":[c],"bbox":bbox,"datetime":"2025-01-01T00:00:00Z/2025-12-31T23:59:59Z","limit":2},timeout=60)
        print("search",s.status_code)
        if s.ok:
            sj=s.json(); print("features",len(sj.get("features",[])))
            for f in sj.get("features",[])[:1]:
                print("id",f["id"],"dt",f.get("properties",{}).get("datetime"),"assets",list(f.get("assets",{}).keys()))
        if c in ("hrea","nasadem"):
            s=requests.post(f"{STAC}/search",json={"collections":[c],"bbox":bbox,"limit":2},timeout=60)
            print("anytime",s.status_code)
            if s.ok and s.json().get("features"):
                f=s.json()["features"][0]; print("id",f["id"],"dt",f.get("properties",{}).get("datetime"),"assets",list(f.get("assets",{}).keys()))

for url in [
 "https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/assim/aqc_tavg_1hr_g1440x721_v1.dds",
 "https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/assim/met_tavg_1hr_g1440x721_x1.dds",
 "https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/assim/xgc_tavg_1hr_g1440x721_x1.dds",
]:
    print("\nGEOS",url)
    r=requests.get(url,timeout=60); print(r.status_code, r.text[:3500])

u="https://hub.worldpop.org/geodata/summary?id=95743"
print("\nWORLDPOP",u)
t=requests.get(u,timeout=60).text
print("status",len(t))
links=re.findall(r'href=["\\\']([^"\\\']+\\.tif[^"\\\']*)',t,re.I)
print("tiflinks",len(links)); print("\n".join(links[:30]))
for pat in ["bgd_t_00_2025","bgd_t_01_2025","bgd_t_65_2025","bgd_t_90_2025"]:
    m=re.search(r'href=["\\\']([^"\\\']*'+re.escape(pat)+r'[^"\\\']*)',t,re.I)
    print(pat, m.group(1) if m else None)
