from __future__ import annotations
import math, time
from pathlib import Path
import numpy as np
import pandas as pd
import requests

INFILE = Path("output/_batch/components_long_all_locations.csv")
OUTFILE = Path("output/LUPUS_CORTEX_2025_DYNAMIC_MASTER.csv")
START = "2025-01-01"
END = "2025-12-31"
BBOX = {"west": 89.24, "south": 22.80, "east": 91.31, "north": 24.80}

ORDER = [
"PM2_5","PM10","NO2","O3","SO2","CO","AEROSOL_INDEX","LST","AIR_TEMP","REL_HUMIDITY",
"NDVI","GREEN_SPACE_PCT","BUILTUP_PCT","IMPERVIOUS_PCT","PRECIPITATION","EXTREME_RAINFALL",
"SOIL_MOISTURE","SURFACE_WATER_EXTENT","FLOOD_EXTENT","DROUGHT_SPI","POP_DENSITY",
"VULNERABLE_AGE_PCT","ROAD_DENSITY","TRANSPORT_ACCESS_PCT","HOSPITAL_ACCESS","GREEN_ACCESS_PCT",
"CRIT_INFRA_DENSITY","NIGHT_LIGHTS","ELEVATION_SLOPE","DISASTER_READINESS"
]
NAMES = [
"PM₂.₅","PM₁₀","NO₂","O₃","SO₂","CO","Aerosol Index / AOD","Land Surface Temperature",
"Air Temperature","Relative Humidity","NDVI","Green-space percentage","Built-up percentage",
"Impervious surface","Precipitation","Extreme rainfall","Soil moisture","Surface-water extent",
"Flood extent","Drought anomaly","Population density","Vulnerable-age population","Road density",
"Public-transport accessibility","Hospital accessibility","Green-space accessibility",
"Critical-infrastructure density","Night-time lights","Elevation / slope","Disaster exposure / readiness"
]
NATIVE_CYCLE = {
"PM2_5":"hourly","PM10":"hourly","NO2":"daily","O3":"daily","SO2":"daily","CO":"daily",
"AEROSOL_INDEX":"daily","LST":"daily","AIR_TEMP":"hourly","REL_HUMIDITY":"hourly",
"NDVI":"16-day composite","GREEN_SPACE_PCT":"scene-based / reference land-cover",
"BUILTUP_PCT":"scene-based / reference land-cover","IMPERVIOUS_PCT":"scene / annual composite",
"PRECIPITATION":"30 minutes","EXTREME_RAINFALL":"30 minutes + derived daily/event",
"SOIL_MOISTURE":"daily","SURFACE_WATER_EXTENT":"~3-day optical / ~6-12-day SAR",
"FLOOD_EXTENT":"event / observation","DROUGHT_SPI":"monthly GRACE + daily SMAP / derived daily",
"POP_DENSITY":"reference epoch","VULNERABLE_AGE_PCT":"reference epoch","ROAD_DENSITY":"snapshot",
"TRANSPORT_ACCESS_PCT":"schedule / snapshot","HOSPITAL_ACCESS":"snapshot",
"GREEN_ACCESS_PCT":"annual / scene composite","CRIT_INFRA_DENSITY":"snapshot",
"NIGHT_LIGHTS":"monthly (VNP46A3 used by extractor)","ELEVATION_SLOPE":"static",
"DISASTER_READINESS":"derived daily"
}
SPATIAL = {
"PM2_5":"0.25° GEOS-CF / source-native","PM10":"0.25° GEOS-CF / source-native",
"NO2":"0.25° / source-native","O3":"source-native","SO2":"source-native","CO":"source-native",
"AEROSOL_INDEX":"source-native","LST":"1 km","AIR_TEMP":"0.25° / source-native",
"REL_HUMIDITY":"0.25° / source-native","NDVI":"500 m","GREEN_SPACE_PCT":"10-30 m aggregated",
"BUILTUP_PCT":"10-30 m aggregated","IMPERVIOUS_PCT":"10-30 m aggregated","PRECIPITATION":"0.1° preferred",
"EXTREME_RAINFALL":"derived from precipitation","SOIL_MOISTURE":"9 km preferred",
"SURFACE_WATER_EXTENT":"10-30 m aggregated","FLOOD_EXTENT":"derived model cell",
"DROUGHT_SPI":"model cell","POP_DENSITY":"100 m-1 km","VULNERABLE_AGE_PCT":"100 m-1 km",
"ROAD_DENSITY":"vector aggregated","TRANSPORT_ACCESS_PCT":"network-derived",
"HOSPITAL_ACCESS":"facility/network-derived","GREEN_ACCESS_PCT":"derived model cell",
"CRIT_INFRA_DENSITY":"vector aggregated","NIGHT_LIGHTS":"15 arc-sec (~500 m)",
"ELEVATION_SLOPE":"30 m preferred / sampled fallback","DISASTER_READINESS":"model grid"
}
KIND = {
**{k:"dynamic" for k in ORDER[:20]},
"POP_DENSITY":"static-reference","VULNERABLE_AGE_PCT":"static-reference","ROAD_DENSITY":"static-reference",
"TRANSPORT_ACCESS_PCT":"derived-static","HOSPITAL_ACCESS":"derived-static","GREEN_ACCESS_PCT":"derived-static",
"CRIT_INFRA_DENSITY":"static-reference","NIGHT_LIGHTS":"dynamic","ELEVATION_SLOPE":"static",
"DISASTER_READINESS":"derived"
}
PREFERRED = {
"PM2_5":("MERRA-2 aerosol diagnostics","M2T1NXAER","https://search.earthdata.nasa.gov/"),
"PM10":("MERRA-2 aerosol diagnostics","M2T1NXAER","https://search.earthdata.nasa.gov/"),
"NO2":("Aura OMI tropospheric NO₂","OMNO2d","https://aura.gsfc.nasa.gov/omi.html"),
"O3":("Aura OMI ozone","OMTO3d","https://aura.gsfc.nasa.gov/omi.html"),
"SO2":("Aura OMI SO₂","OMSO2e","https://aura.gsfc.nasa.gov/omi.html"),
"CO":("Aqua AIRS","AIRX3STD","https://airs.jpl.nasa.gov/"),
"AEROSOL_INDEX":("MODIS MAIAC AOD / OMI UVAI","MCD19A2 / OMAERUVd","https://worldview.earthdata.nasa.gov/"),
"LST":("MODIS Terra/Aqua LST","MOD11A1 / MYD11A1","https://worldview.earthdata.nasa.gov/"),
"AIR_TEMP":("MERRA-2 single-level diagnostics","M2T1NXSLV","https://search.earthdata.nasa.gov/"),
"REL_HUMIDITY":("MERRA-2 single-level diagnostics","M2T1NXSLV","https://search.earthdata.nasa.gov/"),
"NDVI":("MODIS vegetation index","MOD13A2 / MYD13A2","https://worldview.earthdata.nasa.gov/"),
"GREEN_SPACE_PCT":("HLS surface reflectance","HLSS30.002 + HLSL30.002","https://search.earthdata.nasa.gov/search?q=HLS"),
"BUILTUP_PCT":("Landsat/HLS derived","HLS/Landsat","https://science.nasa.gov/mission/landsat/data-overview/"),
"IMPERVIOUS_PCT":("HLS / impervious classification","HLS","https://search.earthdata.nasa.gov/"),
"PRECIPITATION":("GPM IMERG Final","GPM_3IMERGHH_07","https://gpm.nasa.gov/data/imerg"),
"EXTREME_RAINFALL":("GPM IMERG Final derived","GPM_3IMERGHH_07","https://gpm.nasa.gov/data/directory"),
"SOIL_MOISTURE":("SMAP Enhanced L3","SPL3SMP_E v6","https://science.nasa.gov/mission/smap/"),
"SURFACE_WATER_EXTENT":("OPERA DSWx-HLS / DSWx-S1","OPERA_L3_DSWX","https://worldview.earthdata.nasa.gov/"),
"FLOOD_EXTENT":("OPERA DSWx / LANCE flood","OPERA_L3_DSWX","https://worldview.earthdata.nasa.gov/"),
"DROUGHT_SPI":("GRACE-FO + SMAP anomaly","JPL RL06.3 / SPL3SMP_E","https://grace.jpl.nasa.gov/data/get-data/"),
"POP_DENSITY":("SEDAC GPWv4 / WorldPop fallback","GPWv4","https://sedac.ciesin.columbia.edu/data/collection/gpw-v4"),
"VULNERABLE_AGE_PCT":("SEDAC demographic grids / WorldPop fallback","GPW demographic","https://search.earthdata.nasa.gov/search?q=SEDAC"),
"ROAD_DENSITY":("OpenStreetMap / official GIS","OSM","https://www.openstreetmap.org/"),
"TRANSPORT_ACCESS_PCT":("GTFS + OSM","GTFS/OSM","https://www.openstreetmap.org/"),
"HOSPITAL_ACCESS":("OSM facilities + network + NASADEM","OSM/NASADEM","https://www.earthdata.nasa.gov/centers/lp-daac"),
"GREEN_ACCESS_PCT":("HLS green mask + network","HLS/OSM","https://search.earthdata.nasa.gov/search?q=HLS"),
"CRIT_INFRA_DENSITY":("OSM / official infrastructure","OSM","https://www.openstreetmap.org/"),
"NIGHT_LIGHTS":("VIIRS Black Marble","VNP46A3.002","https://www.earthdata.nasa.gov/data/projects/black-marble"),
"ELEVATION_SLOPE":("NASADEM","NASADEM_HGT.001","https://www.earthdata.nasa.gov/centers/lp-daac"),
"DISASTER_READINESS":("Lupus Cortex multi-source composite","multi-source","https://worldview.earthdata.nasa.gov/")
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent":"LupusCortex-2025-dataset/1.0"})

def get_json(url, params, tries=4, timeout=120):
    last=None
    for i in range(tries):
        try:
            r=SESSION.get(url,params=params,timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last=e
            time.sleep(2*(i+1))
    raise RuntimeError(f"{url}: {last}")

def daily_from_hourly(j, var, how="mean", scale=1.0):
    h=j.get("hourly",{})
    t=pd.to_datetime(h.get("time",[]),errors="coerce")
    v=pd.to_numeric(pd.Series(h.get(var,[])),errors="coerce")
    if len(t)!=len(v) or len(v)==0:
        return pd.Series(dtype=float)
    s=pd.Series(v.to_numpy(dtype=float)*scale,index=t)
    return s.resample("D").sum(min_count=1) if how=="sum" else s.resample("D").mean()

def fill_component(df, location_id, key, series, source, dataset, variable, unit=None, is_proxy=True):
    if series.empty: return 0
    series.index=pd.to_datetime(series.index).normalize()
    m=(df.location_id==location_id)&(df.component==key)&(df.value.isna())
    if not m.any(): return 0
    vals=df.loc[m,"date"].map(series)
    good=vals.notna()
    idx=df.loc[m].index[good.to_numpy()]
    if len(idx)==0: return 0
    df.loc[idx,"value"]=vals[good].astype(float).to_numpy()
    df.loc[idx,"status"]="fallback_observed"
    df.loc[idx,"source"]=source
    df.loc[idx,"dataset"]=dataset
    df.loc[idx,"variable"]=variable
    df.loc[idx,"method"]="Public API fallback used only where preferred-source extraction was unavailable"
    df.loc[idx,"measurement_date"]=df.loc[idx,"date"]
    df.loc[idx,"lag_days"]=0
    df.loc[idx,"is_proxy"]=bool(is_proxy)
    if unit:
        df.loc[idx,"unit"]=unit
    return len(idx)

def fallback_open_meteo(df):
    for lid,g in df.groupby("location_id"):
        lat=float(g.lat.iloc[0]); lon=float(g.lon.iloc[0])
        try:
            aq=get_json("https://air-quality-api.open-meteo.com/v1/air-quality",{
                "latitude":lat,"longitude":lon,"start_date":START,"end_date":END,"timezone":"UTC",
                "hourly":"pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,aerosol_optical_depth"
            })
            amap={
                "PM2_5":("pm2_5",1.0,"ug/m3"),"PM10":("pm10",1.0,"ug/m3"),
                "NO2":("nitrogen_dioxide",1.0,"ug/m3"),"O3":("ozone",1.0,"ug/m3"),
                "SO2":("sulphur_dioxide",1.0,"ug/m3"),"CO":("carbon_monoxide",0.001,"mg/m3"),
                "AEROSOL_INDEX":("aerosol_optical_depth",1.0,"AOD/index")
            }
            for key,(var,scale,unit) in amap.items():
                s=daily_from_hourly(aq,var,"mean",scale)
                fill_component(df,lid,key,s,"Open-Meteo Air Quality API (CAMS fallback)",
                    "CAMS European/Global air-quality model via Open-Meteo",var,unit,True)
        except Exception as e:
            print("air-quality fallback failed",lid,e,flush=True)
        try:
            wx=get_json("https://archive-api.open-meteo.com/v1/archive",{
                "latitude":lat,"longitude":lon,"start_date":START,"end_date":END,"timezone":"UTC",
                "hourly":"temperature_2m,relative_humidity_2m,precipitation,soil_moisture_0_to_7cm"
            })
            fill_component(df,lid,"AIR_TEMP",daily_from_hourly(wx,"temperature_2m"),"Open-Meteo Historical Weather API",
                "ERA5/ERA5-Land archive via Open-Meteo","temperature_2m","deg C",True)
            fill_component(df,lid,"REL_HUMIDITY",daily_from_hourly(wx,"relative_humidity_2m"),"Open-Meteo Historical Weather API",
                "ERA5/ERA5-Land archive via Open-Meteo","relative_humidity_2m","%",True)
            fill_component(df,lid,"PRECIPITATION",daily_from_hourly(wx,"precipitation","sum"),"Open-Meteo Historical Weather API",
                "ERA5/ERA5-Land archive via Open-Meteo","precipitation","mm/day",True)
            fill_component(df,lid,"SOIL_MOISTURE",daily_from_hourly(wx,"soil_moisture_0_to_7cm"),"Open-Meteo Historical Weather API",
                "ERA5-Land archive via Open-Meteo","soil_moisture_0_to_7cm","m3/m3",True)
            # Last-resort LST proxy is explicit and never mislabeled as satellite LST.
            fill_component(df,lid,"LST",daily_from_hourly(wx,"temperature_2m"),"Open-Meteo Historical Weather API",
                "ERA5/ERA5-Land archive via Open-Meteo","temperature_2m used as LST proxy","deg C",True)
        except Exception as e:
            print("weather fallback failed",lid,e,flush=True)

def fill_closest_nightlights(df):
    """Use the closest public VIIRS-derived HREA radiance composite when 2025 Black Marble needs EDL auth."""
    try:
        from pystac_client import Client
        import planetary_computer
        import rasterio
    except Exception as e:
        print("night-light fallback imports failed", e, flush=True)
        return
    try:
        cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                          modifier=planetary_computer.sign_inplace)
    except Exception as e:
        print("night-light catalog failed", e, flush=True)
        return
    for lid,g in df.groupby("location_id"):
        m=(df.location_id==lid)&(df.component=="NIGHT_LIGHTS")&df.value.isna()
        if not m.any():
            continue
        lat=float(g.lat.iloc[0]); lon=float(g.lon.iloc[0])
        value=np.nan
        item_date=None
        item_id=""
        try:
            items=list(cat.search(
                collections=["hrea"],
                intersects={"type":"Point","coordinates":[lon,lat]},
                datetime="2019-01-01/2020-12-31",
                max_items=20
            ).items())
            items=sorted(items,key=lambda x:x.datetime or pd.Timestamp("1900-01-01",tz="UTC").to_pydatetime(),reverse=True)
            for item in items:
                asset=item.assets.get("light-composite")
                if asset is None:
                    continue
                try:
                    with rasterio.open(asset.href) as ds:
                        z=float(next(ds.sample([(lon,lat)]))[0])
                        if ds.nodata is not None and z==ds.nodata:
                            continue
                        if np.isfinite(z) and z>-99999:
                            value=z
                            item_date=pd.Timestamp(item.datetime).tz_localize(None).normalize() if item.datetime else pd.Timestamp("2019-12-31")
                            item_id=item.id
                            break
                except Exception:
                    continue
        except Exception as e:
            print("night-light HREA search failed",lid,e,flush=True)
        if not np.isfinite(value):
            continue
        idx=df.loc[m].index
        df.loc[idx,"value"]=value
        df.loc[idx,"status"]="closest_available_observed"
        df.loc[idx,"source"]="HREA VIIRS-derived nighttime-light composite via Microsoft Planetary Computer"
        df.loc[idx,"dataset"]="HREA"
        df.loc[idx,"variable"]="light-composite"
        df.loc[idx,"method"]="Closest public annual VIIRS-derived radiance composite because 2025 VNP46A3 requires Earthdata authentication"
        df.loc[idx,"measurement_date"]=item_date.strftime("%Y-%m-%d") if item_date is not None else "2019-12-31"
        df.loc[idx,"lag_days"]=(pd.to_datetime(df.loc[idx,"date"])-item_date).dt.days if item_date is not None else np.nan
        df.loc[idx,"is_proxy"]=True
        df.loc[idx,"unit"]="radiance / HREA light-composite"
        df.loc[idx,"metadata_json"]='{"fallback_reason":"2025 VNP46A3 requires EDL authentication","HREA_item":"'+item_id+'"}'


def rolling_rank(s):
    out=[]
    for i,x in enumerate(s.to_numpy(dtype=float)):
        a=s.iloc[max(0,i-364):i+1].dropna()
        out.append(np.nan if not np.isfinite(x) or len(a)<10 else 100.0*float((a<=x).mean()))
    return pd.Series(out,index=s.index)

def rolling_z(s):
    m=s.rolling(365,min_periods=20).mean()
    sd=s.rolling(365,min_periods=20).std().replace(0,np.nan)
    return (s-m)/sd

def replace_component_series(df,lid,key,s,source,dataset,method,is_proxy=True):
    s=s.reindex(pd.date_range(START,END,freq="D"))
    m=(df.location_id==lid)&(df.component==key)
    idx=df.loc[m].sort_values("date").index
    if len(idx)!=len(s): return
    df.loc[idx,"value"]=s.to_numpy(dtype=float)
    df.loc[idx,"status"]=np.where(np.isfinite(s.to_numpy(dtype=float)),"derived_proxy","missing")
    df.loc[idx,"source"]=source
    df.loc[idx,"dataset"]=dataset
    df.loc[idx,"variable"]=key
    df.loc[idx,"method"]=method
    df.loc[idx,"measurement_date"]=df.loc[idx,"date"]
    df.loc[idx,"lag_days"]=0
    df.loc[idx,"is_proxy"]=is_proxy

def recompute_derived(df):
    for lid,g in df.groupby("location_id"):
        def ss(key):
            x=g[g.component==key].sort_values("date")
            return pd.Series(pd.to_numeric(x.value,errors="coerce").to_numpy(), index=pd.to_datetime(x.date))
        p=ss("PRECIPITATION")
        if p.notna().sum()>=10:
            replace_component_series(df,lid,"EXTREME_RAINFALL",rolling_rank(p),
                "Derived from precipitation","Lupus Cortex 2025","365-day empirical percentile",True)
        sm=ss("SOIL_MOISTURE")
        if p.notna().sum()>=20 or sm.notna().sum()>=20:
            p30=p.rolling(30,min_periods=10).sum()
            d=pd.concat([rolling_z(p30),rolling_z(sm)],axis=1).mean(axis=1,skipna=True)
            replace_component_series(df,lid,"DROUGHT_SPI",d,
                "Derived precipitation + soil-moisture anomaly","Lupus Cortex 2025",
                "mean standardized anomaly; proxy, not formal long-climatology SPI",True)
        crit=ss("CRIT_INFRA_DENSITY"); tr=ss("TRANSPORT_ACCESS_PCT"); hosp=ss("HOSPITAL_ACCESS")
        flood=ss("FLOOD_EXTENT"); extreme=ss("EXTREME_RAINFALL")
        ready=pd.concat([
            (crit/5*100).clip(0,100),tr.clip(0,100),(100-hosp/10*100).clip(0,100),
            (100-flood*5).clip(0,100),(100-extreme).clip(0,100)
        ],axis=1).mean(axis=1,skipna=True)
        replace_component_series(df,lid,"DISASTER_READINESS",ready,
            "Lupus Cortex deterministic multi-source composite","Lupus Cortex 2025",
            "mean normalized infrastructure/transit/hospital/flood/extreme-rain sub-scores",True)

def actual_url(source):
    s=str(source or "").lower()
    if "geos" in s: return "https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/v2/ana"
    if "planetary" in s or "modis" in s or "worldcover" in s: return "https://planetarycomputer.microsoft.com/api/stac/v1"
    if "worldpop" in s: return "https://api.worldpop.org/v2/"
    if "openstreetmap" in s or "overpass" in s: return "https://overpass-api.de/api/interpreter"
    if "open-meteo air" in s: return "https://air-quality-api.open-meteo.com/v1/air-quality"
    if "open-meteo" in s: return "https://archive-api.open-meteo.com/v1/archive"
    if "hrea" in s: return "https://planetarycomputer.microsoft.com/api/stac/v1/collections/hrea"
    if "black marble" in s: return "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/5200/VNP46A3/2025/"
    if "derived" in s or "lupus cortex" in s: return "derived from rows in this CSV"
    return ""

def main():
    if not INFILE.exists():
        raise SystemExit(f"missing {INFILE}")
    df=pd.read_csv(INFILE,low_memory=False)
    df["date"]=pd.to_datetime(df["date"],errors="coerce").dt.normalize()
    df=df[(df.date>=pd.Timestamp(START))&(df.date<=pd.Timestamp(END))].copy()
    df["value"]=pd.to_numeric(df["value"],errors="coerce")
    fallback_open_meteo(df)
    fill_closest_nightlights(df)
    recompute_derived(df)
    cid={k:i+1 for i,k in enumerate(ORDER)}
    cname=dict(zip(ORDER,NAMES))
    df.insert(0,"component_id",df.component.map(cid))
    df.insert(1,"component_name",df.component.map(cname))
    df["cycle"]="daily model-training grid"
    df["native_source_cycle"]=df.component.map(NATIVE_CYCLE)
    df["native_spatial_resolution"]=df.component.map(SPATIAL)
    df["data_type"]=df.component.map(KIND)
    df["preferred_source"]=df.component.map(lambda k:PREFERRED[k][0])
    df["preferred_product"]=df.component.map(lambda k:PREFERRED[k][1])
    df["workbook_source_url"]=df.component.map(lambda k:PREFERRED[k][2])
    df["actual_source_url"]=df.source.map(actual_url)
    df["closest_date_fallback_used"]=(pd.to_numeric(df.get("lag_days"),errors="coerce").fillna(0)>0) | df.status.astype(str).str.contains("fallback|carried",case=False,regex=True)
    df["model_ready"]=df.value.notna().astype(int)
    df["bbox_west"]=BBOX["west"]; df["bbox_south"]=BBOX["south"]
    df["bbox_east"]=BBOX["east"]; df["bbox_north"]=BBOX["north"]
    df["year"]=2025
    df["date"]=df["date"].dt.strftime("%Y-%m-%d")
    order_cols=[
        "date","year","location_id","location_name","lat","lon","component_id","component","component_name",
        "value","unit","status","model_ready","is_proxy","closest_date_fallback_used","cycle","native_source_cycle",
        "native_spatial_resolution","data_type","source","dataset","variable","method","measurement_date","lag_days",
        "qa_score","preferred_source","preferred_product","actual_source_url","workbook_source_url",
        "bbox_west","bbox_south","bbox_east","bbox_north","requested_date","retrieved_at","metadata_json","error"
    ]
    for c in order_cols:
        if c not in df: df[c]=""
    df=df[order_cols].sort_values(["date","location_id","component_id"])
    OUTFILE.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(OUTFILE,index=False,encoding="utf-8")
    print("FINAL",OUTFILE,"rows",len(df),"non_null",int(df.model_ready.sum()),
          "coverage_pct",round(100*df.model_ready.mean(),3),flush=True)
    print(df.groupby("component_name").model_ready.mean().to_string(),flush=True)

if __name__=="__main__":
    main()
