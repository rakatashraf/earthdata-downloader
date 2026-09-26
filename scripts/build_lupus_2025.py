from __future__ import annotations
import math, os, re, time, traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import requests

OUT=Path("output/lupus_cortex_2025_dynamic.csv"); OUT.parent.mkdir(parents=True,exist_ok=True)
BBOX=(89.24,22.80,91.31,24.80)
LATS=np.arange(23.0,24.751,0.25); LONS=np.arange(89.25,91.251,0.25)
GRID=[(round(float(a),4),round(float(b),4)) for a in LATS for b in LONS]
S=requests.Session(); S.headers["User-Agent"]="LupusCortex-2025-builder/1.0"
ROWS=[]
COMP={
1:("PM2.5","µg/m³","atmospheric model"),2:("PM10","µg/m³","atmospheric model"),
3:("NO2","µg/m³","atmospheric composition"),4:("O3","µg/m³","atmospheric composition"),
5:("SO2","µg/m³","atmospheric composition"),6:("CO","mg/m³","atmospheric composition"),
7:("Aerosol Index / AOD","dimensionless","aerosol retrieval"),8:("Land Surface Temperature","°C","surface temperature"),
9:("Air Temperature","°C","meteorology"),10:("Relative Humidity","%","meteorology"),
11:("NDVI","index","satellite-derived"),12:("Green-space percentage","%","satellite-derived"),
13:("Built-up percentage","%","satellite-derived"),14:("Impervious surface","%","satellite-derived"),
15:("Precipitation","mm/day","precipitation"),16:("Extreme rainfall","mm/day","derived precipitation"),
17:("Soil moisture","m³/m³","soil moisture"),18:("Surface-water extent","%","satellite-derived"),
19:("Flood extent","%","satellite-derived"),20:("Drought anomaly","standardized anomaly","derived hydroclimate"),
21:("Population density","persons/km²","demographic"),22:("Vulnerable-age population","%","demographic"),
23:("Road density","km/km²","GIS"),24:("Public-transport accessibility","stops/100 km²","GIS"),
25:("Hospital accessibility","km to nearest facility","GIS"),26:("Green-space accessibility","0-100","derived GIS"),
27:("Critical-infrastructure density","facilities/100 km²","GIS"),
28:("Night-time lights","relative brightness","VIIRS-derived"),
29:("Elevation / slope","m|degrees","DEM-derived"),30:("Disaster exposure / readiness","0-100","composite")
}
COLS=["component_id","component","timestamp","year","month","day","latitude","longitude","value","unit","cycle","native_cycle","data_type","source_provider","source_product","source_url","source_date","source_spatial_resolution","fallback_used","fallback_reason","derivation","quality_flag","bbox_min_lat","bbox_min_lon","bbox_max_lat","bbox_max_lon"]

def log(x): print(x,flush=True)
def req(method,url,timeout=120,retries=4,**kw):
    err=None
    for i in range(retries):
        try:
            r=S.request(method,url,timeout=timeout,**kw)
            if r.status_code in (429,500,502,503,504): raise RuntimeError(f"{r.status_code} {r.text[:100]}")
            r.raise_for_status(); return r
        except Exception as e:
            err=e
            if i<retries-1: time.sleep(min(2**i,10))
    raise err
def add(cid,ts,lat,lon,val,cycle,native,provider,product,url,source_date="2025",spatial="",fallback=False,reason="",deriv="",quality="source",unit=None):
    if val is None or not np.isfinite(float(val)): return
    t=pd.Timestamp(ts); name,u,dtype=COMP[cid]
    ROWS.append(dict(component_id=cid,component=name,timestamp=t.isoformat(),year=t.year,month=t.month,day=t.day,
        latitude=round(float(lat),5),longitude=round(float(lon),5),value=round(float(val),6),unit=unit or u,
        cycle=cycle,native_cycle=native,data_type=dtype,source_provider=provider,source_product=product,source_url=url,
        source_date=source_date,source_spatial_resolution=spatial,fallback_used=fallback,fallback_reason=reason,
        derivation=deriv,quality_flag=quality,bbox_min_lat=BBOX[1],bbox_min_lon=BBOX[0],bbox_max_lat=BBOX[3],bbox_max_lon=BBOX[2]))

def geos_cf_air():
    log("NASA GEOS-CF")
    import xarray as xr
    aqurl="https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/assim/aqc_tavg_1hr_g1440x721_v1"
    meturl="https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/assim/met_tavg_1hr_g1440x721_x1"
    xurl="https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/assim/xgc_tavg_1hr_g1440x721_x1"
    start=int((pd.Timestamp("2025-01-01T00:30Z")-pd.Timestamp("2018-01-01T00:30Z"))/pd.Timedelta(hours=1))
    end=start+365*24
    def get(url,vars):
        ds=xr.open_dataset(url,engine="pydap",decode_times=False)
        la=np.asarray(ds.lat.values,float); lo=np.asarray(ds.lon.values,float)
        wl=np.mod(LONS,360) if lo.max()>180 else LONS
        yi=np.array([np.abs(la-x).argmin() for x in LATS]); xi=np.array([np.abs(lo-x).argmin() for x in wl])
        y0,y1=yi.min(),yi.max(); x0,x1=xi.min(),xi.max(); out={}
        for v in vars:
            if v not in ds: continue
            da=ds[v].isel(time=slice(start,end),lat=slice(y0,y1+1),lon=slice(x0,x1+1))
            if "lev" in da.dims: da=da.isel(lev=0)
            a=np.asarray(da.load().values,np.float32)[:,yi-y0,:][:,:,xi-x0]
            out[v]=np.nanmean(a.reshape(365,24,len(LATS),len(LONS)),axis=1)
        ds.close(); return out
    aq=get(aqurl,["pm25_rh35_gcc","no2","o3","so2","co"])
    met=get(meturl,["ps","t2m"])
    p=met.get("ps"); tk=met.get("t2m")
    if p is not None and np.nanmedian(p)<2000:p=p*100
    if tk is not None and np.nanmedian(tk)<100:tk=tk+273.15
    dates=pd.date_range("2025-01-01","2025-12-31")
    if "pm25_rh35_gcc" in aq:
        a=aq["pm25_rh35_gcc"]
        if np.nanmedian(np.abs(a))<1e-5:a=a*1e9
        for di,dt in enumerate(dates):
            for y,lat in enumerate(LATS):
                for x,lon in enumerate(LONS): add(1,dt,lat,lon,a[di,y,x],"daily","hourly","NASA GMAO","GEOS-CF PM2.5 assimilation",aqurl,spatial="0.25°")
    for cid,v,mw,scale in [(3,"no2",46.0055,1e6),(4,"o3",47.9982,1e6),(5,"so2",64.066,1e6),(6,"co",28.0101,1e3)]:
        if v not in aq: continue
        a=aq[v]; med=np.nanmedian(np.abs(a)); mol=a if med<0.01 else a*1e-9
        mass=mol*p/(8.314462618*tk)*mw*scale if p is not None and tk is not None else a
        for di,dt in enumerate(dates):
            for y,lat in enumerate(LATS):
                for x,lon in enumerate(LONS): add(cid,dt,lat,lon,mass[di,y,x],"daily","hourly","NASA GMAO",f"GEOS-CF surface {v.upper()}",aqurl,spatial="0.25°",deriv="surface mole fraction converted to mass concentration with GEOS pressure and temperature")
    try:
        dds=req("GET",xurl+".dds",timeout=60).text
        names=re.findall(r"Float32\s+([A-Za-z0-9_]+)\[",dds)
        av=["aod550"] if "aod550" in names else [v for v in names if v.startswith("aod550_")][:16]
        if av:
            d=get(xurl,av); a=np.nansum(np.stack(list(d.values())),axis=0) if "aod550" not in d else d["aod550"]
            for di,dt in enumerate(dates):
                for y,lat in enumerate(LATS):
                    for x,lon in enumerate(LONS): add(7,dt,lat,lon,a[di,y,x],"daily","hourly","NASA GMAO","GEOS-CF AOD550",xurl,spatial="0.25°",deriv="total AOD550 or sum of GEOS aerosol AOD species")
    except Exception as e: log("GEOS AOD failed "+repr(e))

def cams_missing_air():
    have={r["component_id"] for r in ROWS}; need=[x for x in range(1,8) if x not in have]
    if not need:return
    log("CAMS fallback "+str(need))
    api="https://air-quality-api.open-meteo.com/v1/air-quality"
    mp={1:"pm2_5",2:"pm10",3:"nitrogen_dioxide",4:"ozone",5:"sulphur_dioxide",6:"carbon_monoxide",7:"aerosol_optical_depth"}
    vs="pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,aerosol_optical_depth"
    for lat,lon in GRID:
        j=req("GET",api,params={"latitude":lat,"longitude":lon,"start_date":"2025-01-01","end_date":"2025-12-31","hourly":vs,"timezone":"UTC"},timeout=180).json()
        d=pd.DataFrame(j["hourly"]); d["time"]=pd.to_datetime(d["time"]); d=d.set_index("time").resample("D").mean(numeric_only=True)
        for cid in need:
            if mp[cid] not in d:continue
            s=d[mp[cid]]/1000 if cid==6 else d[mp[cid]]
            for ts,v in s.items(): add(cid,ts,lat,lon,v,"daily","hourly","Copernicus CAMS via Open-Meteo","Historical Air Quality",api,spatial="~0.4°",fallback=True,reason="NASA source unavailable for uninterrupted requested field",quality="alternate_source")

def nasa_power():
    log("NASA POWER")
    api="https://power.larc.nasa.gov/api/temporal/daily/point"; cache=[]
    for lat,lon in GRID:
        j=req("GET",api,params={"parameters":"T2M,RH2M,PRECTOTCORR,TS","community":"RE","longitude":lon,"latitude":lat,"start":"20250101","end":"20251231","format":"JSON"},timeout=180).json()
        p=j["properties"]["parameter"]
        for k,v in p["T2M"].items():
            ts=pd.to_datetime(k,format="%Y%m%d"); rec={"timestamp":ts,"latitude":lat,"longitude":lon,"t2m":v,"rh":p["RH2M"].get(k),"precip":p["PRECTOTCORR"].get(k),"ts":p["TS"].get(k)}; cache.append(rec)
            add(9,ts,lat,lon,v,"daily","daily","NASA POWER","T2M daily","https://power.larc.nasa.gov/",spatial="POWER native grid")
            add(10,ts,lat,lon,rec["rh"],"daily","daily","NASA POWER","RH2M daily","https://power.larc.nasa.gov/",spatial="POWER native grid")
            add(15,ts,lat,lon,rec["precip"],"daily","daily","NASA POWER","PRECTOTCORR daily precipitation","https://power.larc.nasa.gov/",spatial="POWER native grid")
    return pd.DataFrame(cache)

def soil_moisture():
    log("ERA5-Land soil moisture")
    api="https://archive-api.open-meteo.com/v1/archive"; out=[]
    for lat,lon in GRID:
        j=req("GET",api,params={"latitude":lat,"longitude":lon,"start_date":"2025-01-01","end_date":"2025-12-31","daily":"soil_moisture_0_to_7cm","timezone":"UTC"},timeout=180).json()
        d=pd.DataFrame(j["daily"]); d["time"]=pd.to_datetime(d["time"])
        for _,r in d.iterrows():
            out.append({"timestamp":r.time,"latitude":lat,"longitude":lon,"sm":r.soil_moisture_0_to_7cm})
            add(17,r.time,lat,lon,r.soil_moisture_0_to_7cm,"daily","hourly/reanalysis","ECMWF ERA5-Land via Open-Meteo","soil_moisture_0_to_7cm",api,spatial="~0.1°",fallback=True,reason="SMAP authenticated pipeline not required for open complete export",quality="alternate_source")
    return pd.DataFrame(out)

STAC="https://planetarycomputer.microsoft.com/api/stac/v1"
def sign(href):
    try:return req("GET","https://planetarycomputer.microsoft.com/api/sas/v1/sign",params={"href":href},timeout=60).json()["href"]
    except:return href
def search(coll,dt=None,query=None,limit=1000):
    b={"collections":[coll],"bbox":list(BBOX),"limit":limit}
    if dt:b["datetime"]=dt
    if query:b["query"]=query
    return req("POST",STAC+"/search",json=b,timeout=120).json().get("features",[])
def ftime(f):
    p=f.get("properties",{})
    if p.get("datetime"):return pd.Timestamp(p["datetime"])
    m=re.search(r"\.A(\d{4})(\d{3})\.",f.get("id",""))
    return pd.Timestamp(datetime(int(m.group(1)),1,1,tzinfo=timezone.utc)+timedelta(days=int(m.group(2))-1)) if m else pd.Timestamp("2025-07-01",tz="UTC")

def modis_lst(power):
    log("MODIS LST")
    import rasterio
    from rasterio.warp import transform
    n=0
    try:
        fs=search("modis-11A2-061","2025-01-01T00:00:00Z/2025-12-31T23:59:59Z")
        for f in fs:
            if "LST_Day_1km" not in f.get("assets",{}):continue
            bb=f.get("bbox"); pts=[p for p in GRID if bb and bb[0]<=p[1]<=bb[2] and bb[1]<=p[0]<=bb[3]]
            if not pts:continue
            with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES",GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(sign(f["assets"]["LST_Day_1km"]["href"])) as src:
                    xs,ys=transform("EPSG:4326",src.crs,[p[1] for p in pts],[p[0] for p in pts]); vals=list(src.sample(zip(xs,ys)))
            dt=ftime(f).tz_localize(None)
            for (lat,lon),v in zip(pts,vals):
                x=float(v[0])*0.02-273.15
                if -80<=x<=90: add(8,dt,lat,lon,x,"8-day","8-day","NASA LP DAAC via Planetary Computer","MODIS LST 8-Day","https://planetarycomputer.microsoft.com/dataset/modis-11A2-061",source_date=str(dt.date()),spatial="1 km");n+=1
    except Exception as e:log("MODIS LST failed "+repr(e))
    if n==0:
        for _,r in power.iterrows(): add(8,r.timestamp,r.latitude,r.longitude,r.ts,"daily","daily","NASA POWER","Earth skin temperature TS","https://power.larc.nasa.gov/",spatial="POWER native grid",fallback=True,reason="MODIS LST extraction unavailable",quality="NASA_model_fallback")

def hls():
    log("NASA HLS land/water")
    import rasterio
    from rasterio.warp import transform
    fs=search("hls2-l30","2025-01-01T00:00:00Z/2025-12-31T23:59:59Z",{"eo:cloud_cover":{"lt":70}})
    groups={}
    for f in fs:
        dt=ftime(f); m=re.search(r"T([0-9A-Z]{5})",f.get("id","")); tile=m.group(1) if m else f.get("id","")
        k=(dt.month,tile); cc=float(f.get("properties",{}).get("eo:cloud_cover",100) or 100)
        if k not in groups or cc<groups[k][0]:groups[k]=(cc,f)
    rec=[]
    for cc,f in groups.values():
        if not all(b in f.get("assets",{}) for b in ["B03","B04","B05","B06"]):continue
        bb=f.get("bbox"); pts=[p for p in GRID if bb and bb[0]<=p[1]<=bb[2] and bb[1]<=p[0]<=bb[3]]
        if not pts:continue
        srcs=[]
        try:
            for b in ["B03","B04","B05","B06"]:
                env=rasterio.Env(GDAL_HTTP_MULTIRANGE="YES",GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR");env.__enter__();src=rasterio.open(sign(f["assets"][b]["href"]));srcs.append((env,src))
            ref=srcs[0][1]; xs,ys=transform("EPSG:4326",ref.crs,[p[1] for p in pts],[p[0] for p in pts])
            for (lat,lon),x,y in zip(pts,xs,ys):
                aa=[]
                for env,src in srcs:
                    row,col=src.index(x,y); from rasterio.windows import Window
                    aa.append(np.ma.filled(src.read(1,window=Window(max(0,col-10),max(0,row-10),21,21),masked=True).astype(float),np.nan))
                g,r,n,s=aa; ok=np.isfinite(g)&np.isfinite(r)&np.isfinite(n)&np.isfinite(s)&(np.abs(r)<30000)&(np.abs(n)<30000)&(np.abs(s)<30000)
                if ok.sum()<10:continue
                nd=(n-r)/(n+r+1e-9); nb=(s-n)/(s+n+1e-9); mw=(g-s)/(g+s+1e-9)
                rec.append(dict(timestamp=pd.Timestamp(2025,ftime(f).month,15),latitude=lat,longitude=lon,ndvi=np.nanmean(nd[ok]),green=100*np.mean(nd[ok]>=.35),built=100*np.mean((nb[ok]>.10)&(nd[ok]<.30)&(mw[ok]<.10)),imperv=100*np.mean((nb[ok]>0)&(nd[ok]<.20)&(mw[ok]<0)),water=100*np.mean(mw[ok]>.15),cloud=cc,item=f["id"]))
        except Exception as e:log("HLS item failed "+str(e)[:120])
        finally:
            for env,src in srcs:
                try:src.close();env.__exit__(None,None,None)
                except:pass
    d=pd.DataFrame(rec)
    if d.empty:return d
    d=d.sort_values("cloud").drop_duplicates(["timestamp","latitude","longitude"])
    d["base"]=d.groupby(["latitude","longitude"]).water.transform(lambda x:x.quantile(.2));d["flood"]=np.clip(d.water-d.base,0,None)
    for _,r in d.iterrows():
        meta=dict(cycle="monthly",native="Landsat acquisition / monthly best scene",provider="NASA LP DAAC",url="https://search.earthdata.nasa.gov/search?q=HLS",source_date=r.item,spatial="30 m, 21x21 window",quality="derived_from_source")
        add(11,r.timestamp,r.latitude,r.longitude,r.ndvi,product="HLSL30 NDVI",deriv="(NIR-Red)/(NIR+Red)",**meta)
        add(12,r.timestamp,r.latitude,r.longitude,r.green,product="HLSL30 green-space",deriv="fraction NDVI>=0.35",**meta)
        add(13,r.timestamp,r.latitude,r.longitude,r.built,product="HLSL30 built-up",deriv="NDBI>0.10, NDVI<0.30, MNDWI<0.10",**meta)
        add(14,r.timestamp,r.latitude,r.longitude,r.imperv,product="HLSL30 impervious proxy",deriv="NDBI>0, NDVI<0.20, MNDWI<0",**meta)
        add(18,r.timestamp,r.latitude,r.longitude,r.water,product="HLSL30 surface water",deriv="MNDWI>0.15",**meta)
        add(19,r.timestamp,r.latitude,r.longitude,r.flood,product="HLSL30 flood excess",deriv="water extent minus cell 20th-percentile 2025 baseline",**meta)
    return d

def derived_rain_drought(soil):
    p=pd.DataFrame([r for r in ROWS if r["component_id"]==15])
    p["timestamp"]=pd.to_datetime(p.timestamp)
    for (lat,lon),g in p.groupby(["latitude","longitude"]):
        q=g.value.quantile(.95)
        for _,r in g.iterrows(): add(16,r.timestamp,lat,lon,r.value if r.value>=q else 0,"daily","daily","NASA POWER","PRECTOTCORR p95 extreme","https://power.larc.nasa.gov/",spatial="POWER grid",deriv=f"daily precipitation >= 2025 cell p95 {q:.3f}")
    if soil.empty:return
    pm=p.groupby(["latitude","longitude",p.timestamp.dt.month]).value.sum().reset_index();pm.columns=["latitude","longitude","month","precip"]
    s=soil.copy();s["month"]=pd.to_datetime(s.timestamp).dt.month;s=s.groupby(["latitude","longitude","month"]).sm.mean().reset_index()
    m=pm.merge(s)
    for (lat,lon),g in m.groupby(["latitude","longitude"]):
        z1=(g.precip-g.precip.mean())/(g.precip.std(ddof=0)+1e-9);z2=(g.sm-g.sm.mean())/(g.sm.std(ddof=0)+1e-9)
        for (_,r),v in zip(g.iterrows(),(z1+z2)/2):add(20,pd.Timestamp(2025,int(r.month),15),lat,lon,v,"monthly","daily→monthly","NASA POWER + ECMWF ERA5-Land","precipitation-soil moisture drought anomaly","https://power.larc.nasa.gov/",spatial="0.25° training grid",fallback=True,reason="GRACE/SMAP composite replaced by transparent open 2025 anomaly",deriv="0.5*z(monthly precip)+0.5*z(monthly soil moisture)",quality="derived")

def worldpop():
    log("WorldPop 2025")
    import rasterio
    base="https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/2025/BGD/v1/1km_ua/constrained/"
    ages=["00","01","05","10","15","20","25","30","35","40","45","50","55","60","65","70","75","80","85","90"]; data={}
    for a in ages:
        u=base+f"bgd_t_{a}_2025_CN_1km_R2025A_UA_v1.tif"; b=req("GET",u,timeout=180).content;p=Path("/tmp")/f"wp_{a}.tif";p.write_bytes(b)
        with rasterio.open(p) as src:data[a]=np.array([float(next(src.sample([(lon,lat)]))[0]) for lat,lon in GRID])
    total=sum(np.nan_to_num(v) for v in data.values());vul=sum(np.nan_to_num(data[a]) for a in ["00","01","65","70","75","80","85","90"])
    out=[]
    for i,(lat,lon) in enumerate(GRID):
        area=(6371.0088*math.radians(1/120))*(6371.0088*math.radians(1/120)*math.cos(math.radians(lat)))
        den=max(total[i],0)/area;vp=100*vul[i]/total[i] if total[i]>0 else 0
        out.append(dict(latitude=lat,longitude=lon,pop=den,vul=vp))
        meta=dict(cycle="yearly",native="yearly demographic estimate",provider="WorldPop",url="https://hub.worldpop.org/geodata/summary?id=95743",source_date="2025-09-01",spatial="1 km",fallback=True,reason="Exact 2025 WorldPop used instead of older SEDAC GPW",quality="2025_alternate")
        add(21,"2025-07-01",lat,lon,den,product="R2025A population density",**meta)
        add(22,"2025-07-01",lat,lon,vp,product="R2025A vulnerable-age share",deriv="(<5 + >=65)/all ages *100",**meta)
    return pd.DataFrame(out)

def osm():
    log("OSM 2025 snapshot")
    ep="https://overpass-api.de/api/interpreter";s,w,n,e=BBOX[1],BBOX[0],BBOX[3],BBOX[2];bb=f"({s},{w},{n},{e})";date='[date:"2025-12-31T23:59:59Z"]'
    q1=f'{date}[out:json][timeout:180];way["highway"]{bb};out geom;'
    q2=f'{date}[out:json][timeout:180];(nwr["public_transport"]{bb};nwr["highway"="bus_stop"]{bb};nwr["railway"~"station|halt|tram_stop"]{bb};nwr["amenity"~"hospital|clinic|fire_station|police"]{bb};nwr["healthcare"~"hospital|clinic"]{bb};nwr["leisure"~"park|nature_reserve|garden|recreation_ground"]{bb};nwr["landuse"~"forest|grass|recreation_ground"]{bb};nwr["natural"="wood"]{bb};nwr["power"~"plant|substation|generator"]{bb};nwr["man_made"~"water_works|communications_tower"]{bb};);out center;'
    try:roads=req("POST",ep,data={"data":q1},timeout=240).json()["elements"];poi=req("POST",ep,data={"data":q2},timeout=240).json()["elements"]
    except Exception:
        ep="https://overpass.kumi.systems/api/interpreter";roads=req("POST",ep,data={"data":q1},timeout=300).json()["elements"];poi=req("POST",ep,data={"data":q2},timeout=300).json()["elements"]
    def pt(x):
        if "lat" in x:return x["lat"],x["lon"]
        c=x.get("center");return (c["lat"],c["lon"]) if c else None
    tr=[];ho=[];gr=[];cr=[]
    for x in poi:
        p=pt(x)
        if not p:continue
        t=x.get("tags",{})
        if "public_transport" in t or t.get("highway")=="bus_stop" or t.get("railway") in ("station","halt","tram_stop"):tr.append(p)
        if t.get("amenity") in ("hospital","clinic") or t.get("healthcare") in ("hospital","clinic"):ho.append(p)
        if t.get("leisure") in ("park","nature_reserve","garden","recreation_ground") or t.get("landuse") in ("forest","grass","recreation_ground") or t.get("natural")=="wood":gr.append(p)
        if t.get("amenity") in ("fire_station","police") or t.get("power") in ("plant","substation","generator") or t.get("man_made") in ("water_works","communications_tower"):cr.append(p)
    def hav(a,b,c,d):
        R=6371.0088;p1=math.radians(a);p2=math.radians(c);x=math.sin(math.radians(c-a)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2;return 2*R*math.asin(min(1,math.sqrt(x)))
    rk={(a,b):0 for a,b in GRID}
    for x in roads:
        g=x.get("geometry",[])
        for A,B in zip(g,g[1:]):
            la,lo=A["lat"],A["lon"];lb,lob=B["lat"],B["lon"];ml=(la+lb)/2;mo=(lo+lob)/2
            yy=round(float(LATS[np.abs(LATS-ml).argmin()]),4);xx=round(float(LONS[np.abs(LONS-mo).argmin()]),4)
            if (yy,xx) in rk:rk[(yy,xx)]+=hav(la,lo,lb,lob)
    out=[]
    for lat,lon in GRID:
        area=(111.32*.25)*(111.32*math.cos(math.radians(lat))*.25);half=.125
        cnt=lambda z:sum(abs(a-lat)<=half and abs(b-lon)<=half for a,b in z)
        rd=rk[(lat,lon)]/area;td=100*cnt(tr)/area;cd=100*cnt(cr)/area;hd=min([hav(lat,lon,*p) for p in ho],default=50);gd=min([hav(lat,lon,*p) for p in gr],default=20)
        out.append(dict(latitude=lat,longitude=lon,road=rd,transit=td,critical=cd,hospital=hd,green_dist=gd))
        meta=dict(cycle="yearly",native="2025-12-31 historical snapshot",provider="OpenStreetMap via Overpass",url=ep,source_date="2025-12-31",spatial="vector→0.25° grid")
        add(23,"2025-12-31",lat,lon,rd,product="OSM roads",**meta);add(24,"2025-12-31",lat,lon,td,product="OSM public transport",**meta);add(25,"2025-12-31",lat,lon,hd,product="OSM hospitals/clinics",**meta);add(27,"2025-12-31",lat,lon,cd,product="OSM critical infrastructure",**meta)
    return pd.DataFrame(out)

def night_dem():
    log("HREA + NASADEM")
    import rasterio
    from rasterio.warp import transform
    # HREA nearest available Bangladesh VIIRS-derived light product
    try:
        fs=search("hrea");f=[x for x in fs if "Bangladesh" in x.get("id","")][0];a="estimated-brightness" if "estimated-brightness" in f["assets"] else "light-composite"
        with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES",GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(sign(f["assets"][a]["href"])) as src:
                xs,ys=transform("EPSG:4326",src.crs,[p[1] for p in GRID],[p[0] for p in GRID]);vals=list(src.sample(zip(xs,ys)))
        for (lat,lon),v in zip(GRID,vals):add(28,"2025-07-01",lat,lon,float(v[0]),"yearly","annual composite","VIIRS-derived HREA via Planetary Computer",f"HREA Bangladesh {ftime(f).year} {a}","https://planetarycomputer.microsoft.com/dataset/hrea",source_date=str(ftime(f).date()),spatial="VIIRS-derived",fallback=True,reason="Nearest open VIIRS-derived composite used because 2025 Black Marble requires Earthdata-authenticated processing",quality="nearest_available")
    except Exception as e:log("HREA failed "+repr(e))
    # NASADEM
    try:
        fs=search("nasadem")
        for lat,lon in GRID:
            c=[f for f in fs if f.get("bbox") and f["bbox"][0]<=lon<=f["bbox"][2] and f["bbox"][1]<=lat<=f["bbox"][3] and "elevation" in f["assets"]]
            if not c:continue
            f=c[0]
            with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES",GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(sign(f["assets"]["elevation"]["href"])) as src:
                    xs,ys=transform("EPSG:4326",src.crs,[lon],[lat]);row,col=src.index(xs[0],ys[0]);from rasterio.windows import Window
                    z=np.ma.filled(src.read(1,window=Window(max(0,col-1),max(0,row-1),3,3),masked=True).astype(float),np.nan);ev=float(np.nanmean(z));dx=abs(src.transform.a);dy=abs(src.transform.e);gy,gx=np.gradient(z,dy,dx);sl=float(np.degrees(np.arctan(np.sqrt(np.nanmean(gx)**2+np.nanmean(gy)**2))))
            add(29,"2025-07-01",lat,lon,ev,"static","static DEM","NASA LP DAAC via Planetary Computer","NASADEM HGT v001 elevation","https://planetarycomputer.microsoft.com/dataset/nasadem",source_date="2000-02-20",spatial="30 m",fallback=True,reason="Terrain is static; closest authoritative NASADEM",quality="static_source",unit="m")
            add(29,"2025-07-01T00:00:01",lat,lon,sl,"static","static DEM","NASA LP DAAC via Planetary Computer","NASADEM-derived slope","https://planetarycomputer.microsoft.com/dataset/nasadem",source_date="2000-02-20",spatial="30 m",fallback=True,reason="Terrain is static",deriv="3x3 DEM gradient",quality="derived",unit="degrees")
    except Exception as e:log("NASADEM failed "+repr(e))

def green_access(hlsd,osmd):
    if osmd.empty:return
    ag=hlsd.groupby(["latitude","longitude"]).green.mean().reset_index() if not hlsd.empty else pd.DataFrame()
    for _,r in osmd.iterrows():
        g=0
        q=ag[(ag.latitude==r.latitude)&(ag.longitude==r.longitude)] if not ag.empty else pd.DataFrame()
        if not q.empty:g=float(q.iloc[0].green)
        score=np.clip(.6*(100*np.exp(-float(r.green_dist)))+.4*g,0,100)
        add(26,"2025-12-31",r.latitude,r.longitude,score,"yearly","HLS monthly + OSM snapshot","NASA HLS + OpenStreetMap","green accessibility proxy","https://search.earthdata.nasa.gov/search?q=HLS",spatial="0.25°",deriv="0.6*distance-decay to OSM green space + 0.4*HLS green cover",quality="derived")

def disaster():
    def df(cid):
        x=pd.DataFrame([r for r in ROWS if r["component_id"]==cid])
        if not x.empty:x["timestamp"]=pd.to_datetime(x.timestamp);x["m"]=x.timestamp.dt.month
        return x
    pm,fl,dr,pop,ho,cr=[df(i) for i in [1,19,20,21,25,27]]
    def v(d,lat,lon,m,default):
        if d.empty:return default
        q=d[(d.latitude==lat)&(d.longitude==lon)&(d.m==m)]
        if q.empty:q=d[(d.latitude==lat)&(d.longitude==lon)]
        return float(q.value.mean()) if not q.empty else default
    for lat,lon in GRID:
        pdens=v(pop,lat,lon,7,1000);hd=v(ho,lat,lon,12,10);cd=v(cr,lat,lon,12,0)
        for m in range(1,13):
            ex=np.clip(.3*v(fl,lat,lon,m,0)/30+.2*max(0,-v(dr,lat,lon,m,0))/2+.2*v(pm,lat,lon,m,35)/100+.15*pdens/10000+.15*hd/20,0,1)
            cap=np.clip(.65*np.exp(-hd/10)+.35*(1-np.exp(-cd/5)),0,1);score=np.clip(100*(.55*(1-ex)+.45*cap),0,100)
            add(30,pd.Timestamp(2025,m,15),lat,lon,score,"monthly","multi-source","NASA + WorldPop + OpenStreetMap + ECMWF","Lupus Cortex disaster exposure/readiness","https://earthdata.nasa.gov/",spatial="0.25°",deriv="exposure: flood+drought+PM2.5+population+hospital distance; capacity: hospital proximity+critical infrastructure",quality="derived_composite")

def ensure():
    have={r["component_id"] for r in ROWS}
    # land-source fallback from HLS/related components if a direct category is missing
    src={i:pd.DataFrame([r for r in ROWS if r["component_id"]==i]) for i in range(1,31)}
    for cid in range(1,31):
        if cid in have:continue
        for lat,lon in GRID:
            if cid==2:
                q=src[1];q=q[(q.latitude==lat)&(q.longitude==lon)]
                for _,r in q.iterrows():add(2,r.timestamp,lat,lon,float(r.value)*1.5,"daily","derived daily",r.source_provider,"PM10 fallback from sourced PM2.5",r.source_url,spatial=r.source_spatial_resolution,fallback=True,reason="PM10 source unavailable",deriv="1.5*PM2.5",quality="derived_fallback")
                continue
            val={12:30,13:20,14:15,18:5,19:0,21:1200,22:12,23:0,24:0,25:20,26:30,27:0,28:0,29:10}.get(cid,0)
            add(cid,"2025-07-01",lat,lon,val,"yearly","fallback","deterministic sourced-pipeline fallback","coverage-preserving fallback","",fallback=True,reason="Primary/alternate source request failed; value is explicitly flagged and should be filtered for strict-source training",quality="coarse_fallback")
    # spatial completeness: each component appears at all 72 grid points at least once
    d=pd.DataFrame(ROWS)
    fill=[]
    for cid in range(1,31):
        g=d[d.component_id==cid];havepts=set(zip(g.latitude.round(4),g.longitude.round(4)))
        for lat,lon in GRID:
            if (lat,lon) in havepts or g.empty:continue
            z=(g.latitude-lat)**2+(g.longitude-lon)**2;r=g.loc[z.idxmin()].to_dict();r["latitude"]=lat;r["longitude"]=lon;r["fallback_used"]=True;r["fallback_reason"]=(str(r.get("fallback_reason",""))+"; nearest populated grid-cell fill").strip("; ");r["quality_flag"]="nearest_spatial_fill";fill.append(r)
    ROWS.extend(fill)

def write():
    d=pd.DataFrame(ROWS);d["timestamp"]=pd.to_datetime(d.timestamp,errors="coerce",utc=True);d=d[d.timestamp.dt.year==2025];d["value"]=pd.to_numeric(d.value,errors="coerce");d=d[np.isfinite(d.value)]
    d=d.drop_duplicates(["component_id","timestamp","latitude","longitude","cycle","source_product","unit"]).sort_values(["component_id","timestamp","latitude","longitude"])
    missing=sorted(set(range(1,31))-set(d.component_id.unique()))
    if missing:raise RuntimeError("missing "+str(missing))
    d["timestamp"]=d.timestamp.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    for c in COLS:
        if c not in d:d[c]=""
    d[COLS].to_csv(OUT,index=False)
    log(f"OUTPUT {OUT} rows={len(d)} bytes={OUT.stat().st_size}")
    print(d.groupby(["component_id","component"]).size().to_string())

def main():
    try:geos_cf_air()
    except Exception as e:log("GEOS failed "+repr(e));traceback.print_exc()
    try:cams_missing_air()
    except Exception as e:log("CAMS failed "+repr(e))
    power=nasa_power()
    try:modis_lst(power)
    except Exception as e:log("LST failed "+repr(e))
    try:h=hls()
    except Exception as e:log("HLS failed "+repr(e));h=pd.DataFrame()
    try:sm=soil_moisture()
    except Exception as e:log("soil failed "+repr(e));sm=pd.DataFrame()
    derived_rain_drought(sm)
    try:wp=worldpop()
    except Exception as e:log("WorldPop failed "+repr(e));wp=pd.DataFrame()
    try:o=osm()
    except Exception as e:log("OSM failed "+repr(e));o=pd.DataFrame()
    try:night_dem()
    except Exception as e:log("static satellite failed "+repr(e))
    green_access(h,o)
    ensure()
    disaster()
    ensure()
    write()
if __name__=="__main__":main()
