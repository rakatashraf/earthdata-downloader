#!/usr/bin/env python3
import csv, json, math, os, time, hashlib
from datetime import datetime, timezone, timedelta
from calendar import monthrange

import numpy as np
import pandas as pd
import requests

START = "2025-01-01"
END = "2025-12-31"
SW_LAT, SW_LON, NE_LAT, NE_LON = 22.80, 89.24, 24.80, 91.31
OUT = "artifacts/lupus_cortex_2025_dynamic.csv"
RETRIEVED = datetime.now(timezone.utc).isoformat()
S = requests.Session()
S.headers.update({"User-Agent": "LupusCortexDataBuilder/1.0 (research; GitHub Actions)"})

def req(method, url, **kwargs):
    last = None
    for i in range(6):
        try:
            r = S.request(method, url, timeout=120, **kwargs)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30, 2 ** i))
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(min(30, 2 ** i))
    raise RuntimeError(f"request failed {url}: {last}")

def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None

def hav_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1, math.sqrt(a)))

def sigmoid01(x):
    if x is None or not math.isfinite(x): return 0.5
    return 1/(1+math.exp(-x))

def zseries(s):
    s = pd.Series(s, dtype=float)
    sd = s.std(ddof=0)
    if not math.isfinite(sd) or sd == 0: return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - s.mean()) / sd

def iso_date(x):
    return pd.Timestamp(x).date().isoformat()

lat_vals = np.linspace(SW_LAT + 0.10, NE_LAT - 0.10, 3)
lon_vals = np.linspace(SW_LON + 0.10, NE_LON - 0.10, 3)
POINTS = []
n = 1
for lat in lat_vals:
    for lon in lon_vals:
        POINTS.append({"grid_id": f"G{n:02d}", "lat": round(float(lat), 5), "lon": round(float(lon), 5)})
        n += 1

rows = []
features = {p["grid_id"]: {} for p in POINTS}

def add(p, component_id, component, timestamp, cycle, value, unit, source_name, source_product, source_url,
        data_status, method, quality_flag="actual", source_date=None, fallback=False, subcomponent=""):
    v = fnum(value)
    if v is None: return
    ts = pd.Timestamp(timestamp)
    rid = hashlib.sha1(f'{p["grid_id"]}|{component_id}|{subcomponent}|{ts.isoformat()}|{cycle}'.encode()).hexdigest()[:20]
    rows.append({
        "record_id": rid,
        "component_id": component_id,
        "component": component,
        "subcomponent": subcomponent,
        "grid_id": p["grid_id"],
        "latitude": p["lat"],
        "longitude": p["lon"],
        "bbox_sw_lat": SW_LAT,
        "bbox_sw_lon": SW_LON,
        "bbox_ne_lat": NE_LAT,
        "bbox_ne_lon": NE_LON,
        "timestamp": ts.isoformat(),
        "cycle": cycle,
        "value": round(v, 8),
        "unit": unit,
        "data_status": data_status,
        "quality_flag": quality_flag,
        "source_name": source_name,
        "source_product": source_product,
        "source_url": source_url,
        "source_date": source_date or ts.date().isoformat(),
        "fallback_closest_date": bool(fallback),
        "method": method,
        "retrieved_at_utc": RETRIEVED,
    })

# ---------- Open-Meteo atmospheric + weather ----------
def fetch_openmeteo_point(p):
    aq_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    aq_params = {
        "latitude": p["lat"], "longitude": p["lon"],
        "start_date": START, "end_date": END, "timezone": "UTC",
        "domains": "cams_global",
        "hourly": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,aerosol_optical_depth"
    }
    aq = req("GET", aq_url, params=aq_params).json()
    h = aq["hourly"]
    adf = pd.DataFrame(h)
    adf["time"] = pd.to_datetime(adf["time"], utc=True)
    for c in [x for x in adf.columns if x != "time"]:
        adf[c] = pd.to_numeric(adf[c], errors="coerce")

    # WHO-relevant O3 metric: max rolling 8h mean each day.
    adf["o3_8h"] = adf["ozone"].rolling(8, min_periods=6).mean()
    daily = adf.set_index("time").resample("1D").mean(numeric_only=True)
    o3max = adf.set_index("time")["o3_8h"].resample("1D").max()
    for ts, r in daily.iterrows():
        add(p, 1, "PM₂.₅", ts, "daily", r.get("pm2_5"), "µg/m³",
            "Open-Meteo / Copernicus CAMS", "CAMS Global Atmospheric Composition", "https://open-meteo.com/en/docs/air-quality-api",
            "model", "Daily mean of hourly near-surface CAMS PM2.5.")
        add(p, 2, "PM₁₀", ts, "daily", r.get("pm10"), "µg/m³",
            "Open-Meteo / Copernicus CAMS", "CAMS Global Atmospheric Composition", "https://open-meteo.com/en/docs/air-quality-api",
            "model", "Daily mean of hourly near-surface CAMS PM10.")
        add(p, 3, "NO₂", ts, "daily", r.get("nitrogen_dioxide"), "µg/m³",
            "Open-Meteo / Copernicus CAMS", "CAMS Global Atmospheric Composition", "https://open-meteo.com/en/docs/air-quality-api",
            "model", "Daily mean of hourly near-surface NO2; surface concentration, not satellite column.")
        add(p, 4, "O₃", ts, "daily", o3max.get(ts), "µg/m³",
            "Open-Meteo / Copernicus CAMS", "CAMS Global Atmospheric Composition", "https://open-meteo.com/en/docs/air-quality-api",
            "model", "Daily maximum rolling 8-hour mean O3 from hourly CAMS values.")
        add(p, 5, "SO₂", ts, "daily", r.get("sulphur_dioxide"), "µg/m³",
            "Open-Meteo / Copernicus CAMS", "CAMS Global Atmospheric Composition", "https://open-meteo.com/en/docs/air-quality-api",
            "model", "Daily mean of hourly near-surface SO2.")
        co = r.get("carbon_monoxide")
        add(p, 6, "CO", ts, "daily", None if pd.isna(co) else co/1000.0, "mg/m³",
            "Open-Meteo / Copernicus CAMS", "CAMS Global Atmospheric Composition", "https://open-meteo.com/en/docs/air-quality-api",
            "model", "Daily mean hourly CO converted from µg/m³ to mg/m³.")
        add(p, 7, "Aerosol Index / AOD", ts, "daily", r.get("aerosol_optical_depth"), "dimensionless",
            "Open-Meteo / Copernicus CAMS", "CAMS Global AOD 550nm", "https://open-meteo.com/en/docs/air-quality-api",
            "model/reanalysis", "Daily mean aerosol optical depth at 550 nm.")

    wx_url = "https://archive-api.open-meteo.com/v1/archive"
    wx_params = {
        "latitude": p["lat"], "longitude": p["lon"],
        "start_date": START, "end_date": END, "timezone": "UTC",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,soil_moisture_0_to_7cm,soil_temperature_0_to_7cm"
    }
    wx = req("GET", wx_url, params=wx_params).json()
    features[p["grid_id"]]["elevation_api"] = fnum(wx.get("elevation"))
    w = pd.DataFrame(wx["hourly"])
    w["time"] = pd.to_datetime(w["time"], utc=True)
    for c in [x for x in w.columns if x != "time"]:
        w[c] = pd.to_numeric(w[c], errors="coerce")
    idx = w.set_index("time")
    wd = pd.DataFrame({
        "air_temp": idx["temperature_2m"].resample("1D").mean(),
        "rh": idx["relative_humidity_2m"].resample("1D").mean(),
        "precip": idx["precipitation"].resample("1D").sum(min_count=1),
        "soil_m": idx["soil_moisture_0_to_7cm"].resample("1D").mean(),
        "soil_t": idx["soil_temperature_0_to_7cm"].resample("1D").mean(),
    })
    p95 = float(wd["precip"].quantile(.95))
    features[p["grid_id"]]["weather_daily"] = wd
    features[p["grid_id"]]["precip_p95"] = p95

    rollp = wd["precip"].rolling(30, min_periods=20).sum()
    zm = zseries(wd["soil_m"])
    zp = zseries(rollp.fillna(rollp.median()))
    drought = (zp + zm) / 2.0

    for ts, r in wd.iterrows():
        add(p, 9, "Air Temperature", ts, "daily", r.air_temp, "°C",
            "Open-Meteo Historical Weather", "ECMWF/ERA5 historical weather", "https://open-meteo.com/en/docs/historical-weather-api",
            "reanalysis/model", "Daily mean of hourly 2-m temperature.")
        add(p, 10, "Relative Humidity", ts, "daily", r.rh, "%",
            "Open-Meteo Historical Weather", "ECMWF/ERA5 historical weather", "https://open-meteo.com/en/docs/historical-weather-api",
            "reanalysis/model", "Daily mean of hourly 2-m relative humidity.")
        add(p, 15, "Precipitation", ts, "daily", r.precip, "mm/day",
            "Open-Meteo Historical Weather", "ECMWF/ERA5 historical weather", "https://open-meteo.com/en/docs/historical-weather-api",
            "reanalysis/model", "Daily precipitation sum from hourly historical fields.")
        extreme = r.precip if (not pd.isna(r.precip) and r.precip >= p95) else 0.0
        add(p, 16, "Extreme rainfall", ts, "daily", extreme, "mm/day",
            "Open-Meteo Historical Weather", "ECMWF/ERA5 historical weather", "https://open-meteo.com/en/docs/historical-weather-api",
            "derived from reanalysis", f"Daily rainfall retained when >= local 2025 95th percentile ({p95:.3f} mm/day), else 0.",
            quality_flag="derived")
        add(p, 17, "Soil moisture", ts, "daily", r.soil_m, "m³/m³",
            "Open-Meteo Historical Weather", "ERA5-Land/ECMWF soil moisture", "https://open-meteo.com/en/docs/historical-weather-api",
            "reanalysis/model", "Daily mean 0-7 cm volumetric soil moisture.")
        add(p, 20, "Drought anomaly", ts, "daily", drought.loc[ts], "standardized anomaly",
            "Derived from Open-Meteo weather", "30-day precipitation + soil-moisture anomaly", "https://open-meteo.com/en/docs/historical-weather-api",
            "derived", "Mean of standardized 30-day precipitation and daily soil-moisture anomalies; lower values indicate drier conditions.",
            quality_flag="derived")
    return wd

# ---------- Open-Meteo flood ----------
def fetch_flood(p):
    url = "https://flood-api.open-meteo.com/v1/flood"
    js = req("GET", url, params={"latitude":p["lat"],"longitude":p["lon"],"start_date":START,"end_date":END,"daily":"river_discharge"}).json()
    d = pd.DataFrame(js["daily"])
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d["river_discharge"] = pd.to_numeric(d["river_discharge"], errors="coerce")
    q = d["river_discharge"]
    q90, q99 = float(q.quantile(.90)), float(q.quantile(.99))
    features[p["grid_id"]]["flood_df"] = d.set_index("time")
    features[p["grid_id"]]["flood_q90"] = q90
    features[p["grid_id"]]["flood_q99"] = q99
    # Actual flood extent is populated later after surface-water baseline is known.
    return d

# ---------- NASA ORNL MODIS REST ----------
def modis_dates(product, p):
    try:
        r = req("GET", f"https://modis.ornl.gov/rst/api/v1/{product}/dates", params={"latitude":p["lat"],"longitude":p["lon"]}).json()
        ds = r.get("dates", r if isinstance(r, list) else [])
        out = []
        for x in ds:
            if isinstance(x, dict):
                md = x.get("modis_date") or x.get("date")
                cd = x.get("calendar_date")
                if md:
                    out.append((md, cd or ""))
        return out
    except Exception:
        return []

def nearest_dates(ds, year=2025):
    exact = [x for x in ds if str(x[0]).startswith(f"A{year}")]
    if exact: return exact, False
    def doy_to_dt(md):
        try: return datetime.strptime(md, "A%Y%j")
        except: return datetime(1900,1,1)
    target = datetime(year,7,2)
    ranked = sorted(ds, key=lambda x: abs((doy_to_dt(x[0])-target).days))
    return ranked[:max(1,min(24,len(ranked)))], True

def modis_subset(product, band, p, km=0, select_all_year=False):
    ds = modis_dates(product, p)
    if not ds: return [], True
    chosen, fallback = nearest_dates(ds)
    if not select_all_year and product == "MCD12Q1":
        chosen = chosen[:1]
    vals = []
    for i in range(0, len(chosen), 10):
        batch = chosen[i:i+10]
        params = {
            "latitude":p["lat"],"longitude":p["lon"],
            "startDate":batch[0][0],"endDate":batch[-1][0],
            "kmAboveBelow":km,"kmLeftRight":km,"band":band
        }
        try:
            js = req("GET", f"https://modis.ornl.gov/rst/api/v1/{product}/subset", params=params, headers={"Accept":"application/json"}).json()
        except Exception:
            continue
        scale = fnum(js.get("scale")) or 1.0
        units = js.get("units","")
        for rec in js.get("subset", []):
            if rec.get("band") and rec.get("band") != band: 
                continue
            arr = [fnum(x) for x in rec.get("data", [])]
            arr = [x for x in arr if x is not None]
            vals.append({
                "modis_date": rec.get("modis_date"),
                "calendar_date": rec.get("calendar_date"),
                "data": arr,
                "scale": scale,
                "units": units,
                "nrows": js.get("nrows"), "ncols": js.get("ncols")
            })
    return vals, fallback

def fetch_modis(p):
    gid = p["grid_id"]
    # LST, 8-day
    lst, fb = modis_subset("MOD11A2", "LST_Day_1km", p, km=0, select_all_year=True)
    if lst:
        for r in lst:
            good = [x for x in r["data"] if x > 0]
            if not good: continue
            k = float(np.median(good)) * (r["scale"] if r["scale"] != 1 else 0.02)
            c = k - 273.15
            add(p, 8, "Land Surface Temperature", r["calendar_date"] or datetime.strptime(r["modis_date"],"A%Y%j"), "8-day", c, "°C",
                "NASA ORNL DAAC", "MOD11A2 Terra MODIS LST 8-Day 1km", "https://modis.ornl.gov/rst/api/v1/MOD11A2/subset",
                "direct satellite retrieval", "Scaled median of the returned MOD11A2 LST_Day_1km subset pixel(s).",
                source_date=r["calendar_date"], fallback=fb)
    else:
        # Fallback is still observed/reanalysis ground-surface temperature, explicitly marked proxy.
        wd = features[gid].get("weather_daily")
        if wd is not None:
            for ts, v in wd["soil_t"].resample("8D").mean().items():
                add(p, 8, "Land Surface Temperature", ts, "8-day", v, "°C",
                    "Open-Meteo Historical Weather", "Near-surface soil temperature fallback", "https://open-meteo.com/en/docs/historical-weather-api",
                    "proxy", "8-day mean 0-7 cm soil temperature used only when MOD11A2 subset service returned no data.",
                    quality_flag="proxy", fallback=True)

    # NDVI, 16-day
    ndvi, fb2 = modis_subset("MOD13Q1", "250m_16_days_NDVI", p, km=0, select_all_year=True)
    if ndvi:
        for r in ndvi:
            good = [x for x in r["data"] if -2000 <= x <= 10000]
            if not good: continue
            scale = r["scale"] if r["scale"] != 1 else 0.0001
            v = float(np.median(good))*scale
            add(p, 11, "NDVI", r["calendar_date"] or datetime.strptime(r["modis_date"],"A%Y%j"), "16-day", v, "index",
                "NASA ORNL DAAC", "MOD13Q1 Terra MODIS Vegetation Indices 16-Day 250m", "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset",
                "derived satellite index", "Scaled median NDVI of the returned center subset.",
                source_date=r["calendar_date"], fallback=fb2)
        features[gid]["ndvi_ok"] = True
    else:
        features[gid]["ndvi_ok"] = False

    # Annual land cover, 5-km neighborhood around each point.
    lc, fb3 = modis_subset("MCD12Q1", "LC_Type1", p, km=5)
    land = None
    if lc:
        land = lc[0]
        classes = [int(round(x)) for x in land["data"] if 1 <= x <= 17]
        if classes:
            total = len(classes)
            green = 100.0 * sum(1 for x in classes if x in set(range(1,11))) / total
            built = 100.0 * sum(1 for x in classes if x == 13) / total
            water = 100.0 * sum(1 for x in classes if x == 17) / total
            features[gid].update({"green_pct":green, "built_pct":built, "water_pct":water, "landcover_date":land["calendar_date"]})
            t = land["calendar_date"] or "2025-07-01"
            add(p, 12, "Green-space percentage", t, "yearly", green, "% area",
                "NASA ORNL DAAC", "MCD12Q1 MODIS Land Cover Type 1", "https://modis.ornl.gov/rst/api/v1/MCD12Q1/subset",
                "derived", "Percent of valid 5-km-neighborhood IGBP pixels in vegetation classes 1-10.",
                quality_flag="derived", source_date=land["calendar_date"], fallback=fb3)
            add(p, 13, "Built-up percentage", t, "yearly", built, "% area",
                "NASA ORNL DAAC", "MCD12Q1 MODIS Land Cover Type 1", "https://modis.ornl.gov/rst/api/v1/MCD12Q1/subset",
                "derived", "Percent of valid 5-km-neighborhood IGBP pixels in urban/built-up class 13.",
                quality_flag="derived", source_date=land["calendar_date"], fallback=fb3)
            add(p, 14, "Impervious surface", t, "yearly", built, "% impervious cover",
                "NASA ORNL DAAC", "MCD12Q1 built-up proxy", "https://modis.ornl.gov/rst/api/v1/MCD12Q1/subset",
                "proxy", "MCD12Q1 urban/built-up fraction used as an impervious-surface proxy.",
                quality_flag="proxy", source_date=land["calendar_date"], fallback=fb3)
            add(p, 18, "Surface-water extent", t, "yearly", water, "% area",
                "NASA ORNL DAAC", "MCD12Q1 MODIS Land Cover Type 1", "https://modis.ornl.gov/rst/api/v1/MCD12Q1/subset",
                "derived", "Percent of valid 5-km-neighborhood IGBP pixels in permanent-water class 17.",
                quality_flag="derived", source_date=land["calendar_date"], fallback=fb3)
    if not features[gid].get("ndvi_ok") and features[gid].get("green_pct") is not None:
        add(p, 11, "NDVI", "2025-07-01", "yearly", features[gid]["green_pct"]/100.0, "index",
            "NASA ORNL DAAC", "MCD12Q1 vegetation-fraction fallback", "https://modis.ornl.gov/rst/api/v1/MCD12Q1/subset",
            "proxy", "Vegetation fraction scaled to 0-1 only because MOD13Q1 returned no usable data.",
            quality_flag="proxy", fallback=True)

# ---------- WorldPop Global2 ----------
def worldpop_task(endpoint, payload):
    r = req("POST", f"https://api.worldpop.org/v2/{endpoint}", json=payload).json()
    tid = r.get("task_id")
    if not tid:
        raise RuntimeError(f"WorldPop task missing: {r}")
    for _ in range(90):
        js = req("GET", f"https://api.worldpop.org/v2/tasks/{tid}").json()
        if js.get("status") == "success":
            return js.get("result", {})
        if js.get("status") == "failure":
            raise RuntimeError(str(js.get("error")))
        time.sleep(1.5)
    raise RuntimeError("WorldPop task timeout")

def cell_polygon(p, d=0.05):
    la, lo = p["lat"], p["lon"]
    return {"type":"Polygon","coordinates":[[
        [lo-d,la-d],[lo+d,la-d],[lo+d,la+d],[lo-d,la+d],[lo-d,la-d]
    ]]}

def fetch_worldpop(p):
    poly = cell_polygon(p)
    base = {"geojson":poly,"year":2025,"resolution":"1km"}
    try:
        pop = worldpop_task("population", base)
        total = fnum(pop.get("total_population"))
        area = fnum(pop.get("area_km2"))
        dens = fnum(pop.get("population_density"))
        if dens is None and total is not None and area:
            dens = total/area
        features[p["grid_id"]]["pop_density"] = dens
        features[p["grid_id"]]["pop_total_cell"] = total
        add(p, 21, "Population density", "2025-07-01", "yearly", dens, "persons/km²",
            "WorldPop", "Global2 2025 population 1km", "https://api.worldpop.org/v2/",
            "non-satellite demographic", "WorldPop v2 zonal population density for a 0.1° x 0.1° cell centered on the grid point.")
        # Whole pyramid allows precise <5 and >=65 shares.
        ag = worldpop_task("agesex", {**base,"age_range":[0,90],"sex":"both"})
        pyr = ag.get("agesex_pyramid", [])
        under5 = old65 = allp = 0.0
        for r in pyr:
            male, female = fnum(r.get("male")) or 0.0, fnum(r.get("female")) or 0.0
            v = male + female
            allp += v
            cl = str(r.get("class",""))
            try: age0 = int(cl)
            except: age0 = 0
            if age0 in (0,1): under5 += v
            if age0 >= 65: old65 += v
        denom = allp if allp > 0 else (fnum(ag.get("total_population")) or total or 0)
        vuln = 100*(under5+old65)/denom if denom else None
        features[p["grid_id"]]["vulnerable_pct"] = vuln
        add(p, 22, "Vulnerable-age population", "2025-07-01", "yearly", vuln, "% population <5 or ≥65",
            "WorldPop", "Global2 2025 age-sex 1km", "https://api.worldpop.org/v2/",
            "non-satellite demographic", "Share of WorldPop age-sex population in classes 0-1, 1-4 and all classes beginning at age 65.")
    except Exception as e:
        print("WORLDPOP_FAIL", p["grid_id"], repr(e), flush=True)

# ---------- OpenStreetMap / Overpass ----------
def elem_coord(e):
    if "lat" in e and "lon" in e: return (e["lat"], e["lon"])
    c = e.get("center")
    if c: return (c.get("lat"), c.get("lon"))
    g = e.get("geometry") or []
    if g:
        return (sum(x["lat"] for x in g)/len(g), sum(x["lon"] for x in g)/len(g))
    return (None,None)

def fetch_osm(p, radius=5000):
    q = f"""[out:json][timeout:90];
(
  way["highway"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["public_transport"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["highway"="bus_stop"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["railway"~"station|halt|tram_stop"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["amenity"~"hospital|clinic"](around:20000,{p["lat"]},{p["lon"]});
  nwr["leisure"~"park|garden|nature_reserve"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["landuse"~"forest|grass|recreation_ground"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["natural"="wood"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["amenity"~"fire_station|police"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["power"](around:{radius},{p["lat"]},{p["lon"]});
  nwr["man_made"~"water_tower|wastewater_plant|water_works|communications_tower"](around:{radius},{p["lat"]},{p["lon"]});
);
out geom center tags;"""
    try:
        js = req("POST", "https://overpass-api.de/api/interpreter", data=q).json()
    except Exception as e:
        print("OSM_FAIL", p["grid_id"], repr(e), flush=True)
        return
    els = js.get("elements", [])
    road_km = 0.0
    stop_coords, hosp_coords, green_coords = [], [], []
    critical_ids = set()
    for e in els:
        t = e.get("tags", {})
        if e.get("type") == "way" and "highway" in t:
            g = e.get("geometry") or []
            for a,b in zip(g, g[1:]):
                ml, mn = (a["lat"]+b["lat"])/2, (a["lon"]+b["lon"])/2
                if hav_km(p["lat"],p["lon"],ml,mn) <= radius/1000:
                    road_km += hav_km(a["lat"],a["lon"],b["lat"],b["lon"])
        la, lo = elem_coord(e)
        if la is None: continue
        if ("public_transport" in t or t.get("highway")=="bus_stop" or t.get("railway") in ("station","halt","tram_stop")):
            stop_coords.append((la,lo))
        if t.get("amenity") in ("hospital","clinic"):
            hosp_coords.append((la,lo))
        if t.get("leisure") in ("park","garden","nature_reserve") or t.get("landuse") in ("forest","grass","recreation_ground") or t.get("natural")=="wood":
            green_coords.append((la,lo))
        if t.get("amenity") in ("fire_station","police") or "power" in t or t.get("man_made") in ("water_tower","wastewater_plant","water_works","communications_tower"):
            critical_ids.add((e.get("type"),e.get("id")))
    area = math.pi*(radius/1000)**2
    road_density = road_km/area
    stop_density = len(stop_coords)/area
    crit_density = len(critical_ids)/area
    nearest_stop = min([hav_km(p["lat"],p["lon"],*c) for c in stop_coords], default=10.0)
    nearest_hosp = min([hav_km(p["lat"],p["lon"],*c) for c in hosp_coords], default=50.0)
    nearest_green = min([hav_km(p["lat"],p["lon"],*c) for c in green_coords], default=10.0)
    transit_score = max(0.0, min(100.0, 55*math.exp(-nearest_stop/1.5) + 45*min(1, stop_density/0.5)))
    green_pct = features[p["grid_id"]].get("green_pct",0.0) or 0.0
    green_score = max(0.0, min(100.0, 65*math.exp(-nearest_green/1.5) + 35*min(1,green_pct/40.0)))
    features[p["grid_id"]].update({
        "road_density":road_density, "transit_score":transit_score, "hospital_km":nearest_hosp,
        "green_access_score":green_score, "critical_density":crit_density
    })
    d = RETRIEVED[:10]
    add(p, 23, "Road density", d, "snapshot", road_density, "km/km²",
        "OpenStreetMap", "OSM highway network via Overpass", "https://overpass-api.de/",
        "non-satellite GIS", f"Road-line length within {radius/1000:.1f} km divided by circular area; current OSM used as closest available snapshot to 2025.", fallback=True, source_date=d)
    add(p, 24, "Public-transport accessibility", d, "snapshot", transit_score, "score_0_100",
        "OpenStreetMap", "OSM transit stops/stations via Overpass", "https://overpass-api.de/",
        "derived GIS/network", "0-100 access score combining nearest stop/station distance and stop density within 5 km; current OSM snapshot.", quality_flag="derived", fallback=True, source_date=d)
    add(p, 25, "Hospital accessibility", d, "snapshot", nearest_hosp, "km to nearest hospital/clinic",
        "OpenStreetMap", "OSM hospitals/clinics via Overpass", "https://overpass-api.de/",
        "non-satellite GIS", "Great-circle distance to nearest mapped hospital or clinic within 20 km; current OSM snapshot.", fallback=True, source_date=d)
    add(p, 26, "Green-space accessibility", d, "snapshot", green_score, "score_0_100",
        "OpenStreetMap + NASA MODIS", "OSM green places + MCD12Q1 vegetation fraction", "https://overpass-api.de/",
        "derived GIS", "0-100 score combining nearest mapped green space and MODIS local green-space percentage.", quality_flag="derived", fallback=True, source_date=d)
    add(p, 27, "Critical-infrastructure density", d, "snapshot", crit_density, "facilities/km²",
        "OpenStreetMap", "OSM emergency/power/water/telecom facilities", "https://overpass-api.de/",
        "non-satellite GIS", "Count of mapped critical facilities within 5 km divided by circular area; current OSM snapshot.", fallback=True, source_date=d)

# ---------- VIIRS nighttime lights via public ArcGIS image service ----------
def fetch_ntl_service_url():
    try:
        j = req("GET","https://www.arcgis.com/sharing/rest/content/items/edabcbb5407547f5bc883018eb6e7986",params={"f":"json"}).json()
        return j.get("url")
    except Exception:
        return None

def fetch_ntl(p, service_url):
    if not service_url: return
    vals = []
    for m in range(1,13):
        start = datetime(2025,m,1,tzinfo=timezone.utc)
        end = datetime(2025,m,monthrange(2025,m)[1],23,59,59,tzinfo=timezone.utc)
        t = f"{int(start.timestamp()*1000)},{int(end.timestamp()*1000)}"
        params = {
            "f":"json","geometry":f'{p["lon"]},{p["lat"]}',"geometryType":"esriGeometryPoint",
            "returnFirstValueOnly":"true","time":t
        }
        v = None
        try:
            js = req("GET", service_url.rstrip("/")+"/getSamples", params=params).json()
            samples = js.get("samples", [])
            if samples:
                s = samples[0]
                v = fnum(s.get("value"))
                if v is None and s.get("values"):
                    v = fnum(str(s.get("values")).split()[0].split(",")[0])
        except Exception:
            pass
        if v is None:
            try:
                js = req("GET", service_url.rstrip("/")+"/identify", params={
                    "f":"json","geometry":f'{p["lon"]},{p["lat"]}',"geometryType":"esriGeometryPoint",
                    "returnGeometry":"false","time":t
                }).json()
                v = fnum(js.get("value"))
            except Exception:
                pass
        if v is not None:
            vals.append(v)
            add(p, 28, "Night-time lights", start, "monthly", v, "nW/cm²/sr",
                "Earth Observation Group / Esri", "VIIRS Nighttime Lights Monthly Cloud-Free Composite",
                service_url, "direct satellite retrieval/product",
                "Monthly VIIRS DNB average radiance sampled from the public ArcGIS ImageServer.",
                source_date=start.date().isoformat())
    if vals: features[p["grid_id"]]["ntl_mean"] = float(np.mean(vals))

# ---------- Elevation / slope ----------
def fetch_elevation_slope(p):
    # 4-point finite difference around center.
    d = 0.01
    coords = [(p["lat"],p["lon"]),(p["lat"]+d,p["lon"]),(p["lat"]-d,p["lon"]),(p["lat"],p["lon"]+d),(p["lat"],p["lon"]-d)]
    try:
        js = req("GET","https://api.open-meteo.com/v1/elevation",params={
            "latitude":",".join(str(x[0]) for x in coords),
            "longitude":",".join(str(x[1]) for x in coords)
        }).json()
        elevs = js.get("elevation",[])
        if len(elevs) >= 5:
            zc, zn, zs, ze, zw = map(float,elevs[:5])
            dy = hav_km(p["lat"]-d,p["lon"],p["lat"]+d,p["lon"])*1000
            dx = hav_km(p["lat"],p["lon"]-d,p["lat"],p["lon"]+d)*1000
            dzdx = (ze-zw)/dx if dx else 0
            dzdy = (zn-zs)/dy if dy else 0
            slope = math.degrees(math.atan(math.sqrt(dzdx**2+dzdy**2)))
            features[p["grid_id"]]["elevation"] = zc
            features[p["grid_id"]]["slope"] = slope
            add(p, 29, "Elevation / slope", "2025-07-01", "static", zc, "m",
                "Open-Meteo Elevation API", "90-m global DEM-backed elevation", "https://open-meteo.com/en/docs/elevation-api",
                "derived from satellite DEM", "Point elevation from global DEM service.", subcomponent="elevation")
            add(p, 29, "Elevation / slope", "2025-07-01", "static", slope, "degrees",
                "Open-Meteo Elevation API", "DEM finite-difference slope", "https://open-meteo.com/en/docs/elevation-api",
                "derived from satellite DEM", "Slope from centered finite differences of four nearby DEM elevations.", quality_flag="derived", subcomponent="slope")
            return
    except Exception:
        pass
    e = features[p["grid_id"]].get("elevation_api")
    if e is not None:
        add(p, 29, "Elevation / slope", "2025-07-01", "static", e, "m",
            "Open-Meteo Historical Weather", "Grid-cell elevation fallback", "https://open-meteo.com/en/docs/historical-weather-api",
            "DEM-backed", "Historical-weather grid-cell elevation used because dedicated elevation endpoint failed.", quality_flag="fallback", fallback=True, subcomponent="elevation")
        add(p, 29, "Elevation / slope", "2025-07-01", "static", 0.0, "degrees",
            "Open-Meteo Historical Weather", "Slope unavailable fallback", "https://open-meteo.com/en/docs/historical-weather-api",
            "fallback", "Slope set to 0 only because surrounding DEM samples were unavailable.", quality_flag="proxy", fallback=True, subcomponent="slope")

# ---------- Finish flood extent after land-water baseline ----------
def add_flood_extent(p):
    gid = p["grid_id"]
    d = features[gid].get("flood_df")
    if d is None: return
    q90 = features[gid].get("flood_q90",0); q99 = features[gid].get("flood_q99",q90+1)
    water = features[gid].get("water_pct",0.0) or 0.0
    denom = max(1e-9, q99-q90)
    for ts, r in d.iterrows():
        q = fnum(r.get("river_discharge"))
        if q is None: continue
        excess = max(0.0,min(1.0,(q-q90)/denom))
        # Keeps permanent water separate: up to an additional 25% inundation at extreme discharge.
        flood_pct = max(0.0,min(100.0, excess*25.0))
        add(p, 19, "Flood extent", ts, "daily", flood_pct, "% area (hydrologic proxy)",
            "Open-Meteo / Copernicus GloFAS + NASA MODIS", "GloFAS discharge + MCD12Q1 water baseline", "https://open-meteo.com/en/docs/flood-api",
            "derived proxy", f"0-25% event inundation proxy from 2025 discharge between q90={q90:.3f} and q99={q99:.3f}; permanent-water baseline={water:.2f}%.",
            quality_flag="proxy")

# ---------- Disaster exposure/readiness composite ----------
def add_disaster_composite(p):
    gid = p["grid_id"]
    f = features[gid]
    flood = f.get("flood_df")
    wd = f.get("weather_daily")
    if flood is None or wd is None: return
    # Reconstruct drought z monthly from weather.
    rollp = wd["precip"].rolling(30,min_periods=20).sum()
    drought = (zseries(rollp.fillna(rollp.median())) + zseries(wd["soil_m"])) / 2
    q = flood["river_discharge"].astype(float)
    qz = zseries(q)
    monthly_f = qz.resample("MS").mean()
    monthly_d = drought.resample("MS").mean()
    pop = f.get("pop_density",0) or 0
    vuln = f.get("vulnerable_pct",0) or 0
    road = f.get("road_density",0) or 0
    transit = f.get("transit_score",0) or 0
    hosp = f.get("hospital_km",50) or 50
    crit = f.get("critical_density",0) or 0
    # Exposure and readiness are deliberately transparent, bounded 0-100.
    pop_exp = min(100, 18*math.log1p(max(0,pop)))
    vuln_exp = min(100, vuln*2.5)
    base_read = max(0,min(100, 20*math.log1p(max(0,road)) + .35*transit + 30*math.exp(-hosp/8) + 15*min(1,crit/0.15)))
    for ts in monthly_f.index:
        fe = max(0,min(100,50+20*(monthly_f.get(ts) if math.isfinite(monthly_f.get(ts,np.nan)) else 0)))
        dz = monthly_d.get(ts)
        de = max(0,min(100,50-20*(dz if math.isfinite(dz) else 0)))
        exposure = max(0,min(100,.30*fe+.25*de+.25*pop_exp+.20*vuln_exp))
        readiness = max(0,min(100,.65*base_read+.35*(100-exposure)))
        add(p, 30, "Disaster exposure / readiness", ts, "monthly", exposure, "score_0_100",
            "Multi-source derived", "GloFAS + weather + WorldPop + OSM", "https://worldview.earthdata.nasa.gov/",
            "composite multi-source", "Exposure score from flood anomaly, drought anomaly, population density and vulnerable-age share.", quality_flag="derived", subcomponent="exposure_score")
        add(p, 30, "Disaster exposure / readiness", ts, "monthly", readiness, "score_0_100",
            "Multi-source derived", "GloFAS + weather + WorldPop + OSM", "https://worldview.earthdata.nasa.gov/",
            "composite multi-source", "Readiness score combines roads, transit, hospital distance, critical infrastructure, and inverse exposure.", quality_flag="derived", subcomponent="readiness_score")

def ensure_component_coverage():
    present = {int(r["component_id"]) for r in rows}
    missing = [i for i in range(1,31) if i not in present]
    if missing:
        raise RuntimeError(f"Missing component IDs after collection: {missing}")

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    service = fetch_ntl_service_url()
    for p in POINTS:
        print("POINT", p, flush=True)
        fetch_openmeteo_point(p)
        fetch_flood(p)
        fetch_modis(p)
        fetch_worldpop(p)
        fetch_osm(p)
        fetch_ntl(p, service)
        fetch_elevation_slope(p)
        add_flood_extent(p)
        add_disaster_composite(p)

    # Sort and write as one training-ready long CSV.
    ensure_component_coverage()
    rows.sort(key=lambda r:(r["component_id"],r["grid_id"],r["timestamp"],r["subcomponent"]))
    cols = [
        "record_id","component_id","component","subcomponent","grid_id","latitude","longitude",
        "bbox_sw_lat","bbox_sw_lon","bbox_ne_lat","bbox_ne_lon","timestamp","cycle","value","unit",
        "data_status","quality_flag","source_name","source_product","source_url","source_date",
        "fallback_closest_date","method","retrieved_at_utc"
    ]
    with open(OUT,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
    # Small manifest for logs.
    bycomp = pd.Series([r["component_id"] for r in rows]).value_counts().sort_index()
    print("ROWS",len(rows), flush=True)
    print("COMPONENT_COUNTS",bycomp.to_dict(), flush=True)
    print("OUTPUT",OUT,os.path.getsize(OUT), flush=True)

if __name__ == "__main__":
    main()
