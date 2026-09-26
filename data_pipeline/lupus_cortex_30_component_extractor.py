from __future__ import annotations

"""
Lupus Cortex 30-Component CSV Data Extractor
=============================================

Google Colab-oriented extractor for the frozen Lupus Cortex 30-component model.

Primary output:
  components_daily_wide.csv      -> 90 daily rows x exactly 30 component columns
  components_daily_long.csv      -> 90 x 30 rows with provenance, lag, status, QA
  components_quality.csv         -> lag / status / availability features
  components_latest.csv          -> newest usable value per component
  component_coverage.csv         -> coverage summary
  provenance.csv                 -> data-source/method record
  extraction_errors.csv          -> failures without fabricated values
  gibs_visual_metadata.csv       -> GIBS imagery date metadata only
  components_15d_wide.csv
  components_30d_wide.csv
  components_45d_wide.csv
  components_60d_wide.csv
  components_75d_wide.csv
  components_90d_wide.csv

Batch mode additionally writes:
  _batch/training_matrix_all_locations.csv
  _batch/components_long_all_locations.csv
  _batch/batch_manifest.csv

Scientific rules:
- Missing data remain NaN. No random/fabricated environmental values.
- NASA GIBS is used only for visual imagery/date provenance, never for numerical
  environmental extraction from RGB pixels.
- Satellite column/profile values are not silently treated as surface exposure.
  Surface atmospheric variables use GEOS-CF surface fields where available.
- Derived/proxy components are explicitly marked is_proxy=True.
"""

import json
import math
import re
import time
import traceback
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests


# -----------------------------------------------------------------------------
# 0. Canonical Lupus Cortex component registry
# -----------------------------------------------------------------------------

COMPONENT_KEYS = [
    "PM2_5", "PM10", "NO2", "O3", "SO2", "CO", "AEROSOL_INDEX",
    "LST", "AIR_TEMP", "REL_HUMIDITY", "NDVI", "GREEN_SPACE_PCT",
    "BUILTUP_PCT", "IMPERVIOUS_PCT", "PRECIPITATION", "EXTREME_RAINFALL",
    "SOIL_MOISTURE", "SURFACE_WATER_EXTENT", "FLOOD_EXTENT", "DROUGHT_SPI",
    "POP_DENSITY", "VULNERABLE_AGE_PCT", "ROAD_DENSITY",
    "TRANSPORT_ACCESS_PCT", "HOSPITAL_ACCESS", "GREEN_ACCESS_PCT",
    "CRIT_INFRA_DENSITY", "NIGHT_LIGHTS", "ELEVATION_SLOPE",
    "DISASTER_READINESS",
]

FRONTEND_META = {
    "PM2_5": ("ug/m3", "Down", "temporal_spatial"),
    "PM10": ("ug/m3", "Down", "temporal_spatial"),
    "NO2": ("ug/m3", "Down", "temporal_spatial"),
    "O3": ("ug/m3", "Down", "temporal_spatial"),
    "SO2": ("ug/m3", "Down", "temporal_spatial"),
    "CO": ("mg/m3", "Down", "temporal_spatial"),
    "AEROSOL_INDEX": ("AOD/index", "Down", "temporal_spatial"),
    "LST": ("deg C", "Down", "temporal_spatial"),
    "AIR_TEMP": ("deg C", "Optimal", "temporal_spatial"),
    "REL_HUMIDITY": ("%", "Optimal", "temporal_spatial"),
    "NDVI": ("-1 to 1", "Up", "temporal_spatial"),
    "GREEN_SPACE_PCT": ("% area", "Up", "spatial"),
    "BUILTUP_PCT": ("% area", "Down", "spatial"),
    "IMPERVIOUS_PCT": ("% cover", "Down", "spatial"),
    "PRECIPITATION": ("mm/day", "Optimal", "temporal_spatial"),
    "EXTREME_RAINFALL": ("percentile", "Down", "temporal_spatial"),
    "SOIL_MOISTURE": ("m3/m3", "Optimal", "temporal_spatial"),
    "SURFACE_WATER_EXTENT": ("% area", "Optimal", "temporal_spatial"),
    "FLOOD_EXTENT": ("% area", "Down", "temporal_spatial"),
    "DROUGHT_SPI": ("standardized anomaly", "Toward 0", "temporal_spatial"),
    "POP_DENSITY": ("people/km2", "Contextual", "spatial"),
    "VULNERABLE_AGE_PCT": ("% population", "Down", "spatial"),
    "ROAD_DENSITY": ("km/km2", "Contextual", "spatial"),
    "TRANSPORT_ACCESS_PCT": ("% within access threshold", "Up", "spatial"),
    "HOSPITAL_ACCESS": ("km to nearest facility", "Down", "spatial"),
    "GREEN_ACCESS_PCT": ("% within access threshold", "Up", "spatial"),
    "CRIT_INFRA_DENSITY": ("facilities/km2", "Up", "spatial"),
    "NIGHT_LIGHTS": ("nW/cm2/sr", "Contextual", "temporal_spatial"),
    "ELEVATION_SLOPE": ("degrees mean slope", "Contextual", "spatial"),
    "DISASTER_READINESS": ("readiness score", "Up", "spatial"),
}

ALIASES = {
    "pm2 5": "PM2_5", "pm 2 5": "PM2_5", "pm25": "PM2_5",
    "pm10": "PM10", "pm 10": "PM10", "no2": "NO2", "o3": "O3",
    "so2": "SO2", "co": "CO", "aerosol index aod": "AEROSOL_INDEX",
    "aerosol index": "AEROSOL_INDEX", "aod": "AEROSOL_INDEX",
    "land surface temperature": "LST", "air temperature": "AIR_TEMP",
    "relative humidity": "REL_HUMIDITY", "ndvi": "NDVI",
    "green space percentage": "GREEN_SPACE_PCT",
    "built up percentage": "BUILTUP_PCT",
    "impervious surface": "IMPERVIOUS_PCT", "precipitation": "PRECIPITATION",
    "extreme rainfall": "EXTREME_RAINFALL", "soil moisture": "SOIL_MOISTURE",
    "surface water extent": "SURFACE_WATER_EXTENT", "flood extent": "FLOOD_EXTENT",
    "drought anomaly": "DROUGHT_SPI", "population density": "POP_DENSITY",
    "vulnerable age population": "VULNERABLE_AGE_PCT", "road density": "ROAD_DENSITY",
    "public transport accessibility": "TRANSPORT_ACCESS_PCT",
    "hospital accessibility": "HOSPITAL_ACCESS",
    "green space accessibility": "GREEN_ACCESS_PCT",
    "critical infrastructure density": "CRIT_INFRA_DENSITY",
    "night time lights": "NIGHT_LIGHTS", "elevation slope": "ELEVATION_SLOPE",
    "disaster exposure readiness": "DISASTER_READINESS",
}


def _norm_name(value: Any) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = s.replace("₂", "2").replace("₁", "1").replace("₀", "0").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def canonical_component(name: Any) -> Optional[str]:
    n = _norm_name(name)
    if n in ALIASES:
        return ALIASES[n]
    for alias, key in ALIASES.items():
        if alias in n or n in alias:
            return key
    return None


def load_indicator_registry(workbook_path: str) -> pd.DataFrame:
    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"Indicator workbook not found: {path}")
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")
    else:
        xls = pd.ExcelFile(path)
        sheet = "Indicators" if "Indicators" in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(path, sheet_name=sheet)
    if "Component" not in df.columns:
        raise ValueError("Workbook must contain a 'Component' column.")
    records = []
    for _, row in df.iterrows():
        key = canonical_component(row.get("Component"))
        if key is None:
            continue
        unit, direction, mode = FRONTEND_META[key]
        rec = row.to_dict()
        rec.update({
            "component_key": key,
            "frontend_unit": unit,
            "direction": direction,
            "model_mode": mode,
        })
        records.append(rec)
    out = pd.DataFrame(records)
    found = set(out.get("component_key", []))
    missing = [k for k in COMPONENT_KEYS if k not in found]
    if missing:
        raise ValueError(f"Workbook did not resolve all 30 core components. Missing: {missing}")
    order = {k: i for i, k in enumerate(COMPONENT_KEYS)}
    out["__order"] = out["component_key"].map(order)
    return out.sort_values("__order").drop(columns="__order").reset_index(drop=True)


# -----------------------------------------------------------------------------
# 1. Configuration + common helpers
# -----------------------------------------------------------------------------

@dataclass
class ExtractorConfig:
    workbook_path: str = "/content/drive/MyDrive/LUPUS CORTEX/environmental_geospatial_indicators.xlsx"
    output_root: str = "/content/drive/MyDrive/LUPUS CORTEX/data_extractor_output"
    lookback_days: int = 90
    baseline_days: int = 365
    analysis_area_km: float = 5.0
    hls_search_days: int = 120
    max_lag_lst_days: int = 5
    max_lag_ndvi_days: int = 20
    max_lag_hls_days: int = 30
    transit_access_m: float = 500.0
    green_access_m: float = 300.0
    overpass_timeout_s: int = 120
    request_timeout_s: int = 90
    use_earthdata_optional: bool = False
    strict_no_proxy: bool = False

    def output_dir(self, location_id: str) -> Path:
        p = Path(self.output_root) / location_id
        p.mkdir(parents=True, exist_ok=True)
        return p


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def requested_date_or_today(value=None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    ts = pd.Timestamp(value)
    if ts.tzinfo:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def date_range_ending(end_date, days: int) -> pd.DatetimeIndex:
    end = pd.Timestamp(end_date).normalize()
    return pd.date_range(end - pd.Timedelta(days=days - 1), end, freq="D")


def analysis_bbox(lat: float, lon: float, area_km: float) -> Tuple[float, float, float, float]:
    half = area_km / 2.0
    dlat = half / 111.32
    dlon = half / max(1e-6, 111.32 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def file_safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value))[:100]


def make_location_id(name: str, lat: float, lon: float) -> str:
    return file_safe_name(f"{name or 'location'}_{lat:.5f}_{lon:.5f}")


def gas_mixing_ratio_to_mass(value_mol_mol, molar_mass_g_mol, pressure_pa, temp_k, out="ug_m3"):
    # Ideal gas relation: mol/m3 = mole_fraction * P / (R*T)
    R = 8.314462618
    mol_m3 = np.asarray(value_mol_mol, dtype=float) * np.asarray(pressure_pa, dtype=float) / (
        R * np.asarray(temp_k, dtype=float)
    )
    g_m3 = mol_m3 * float(molar_mass_g_mol)
    return g_m3 * (1000.0 if out == "mg_m3" else 1_000_000.0)


def align_sparse_to_daily(values: pd.Series, daily_index: pd.DatetimeIndex, max_lag_days: int):
    values = pd.Series(values).dropna().copy()
    values.index = pd.to_datetime(values.index).normalize()
    values = values.groupby(level=0).mean().sort_index()
    aligned = pd.Series(index=daily_index, dtype=float)
    obs_date = pd.Series(index=daily_index, dtype="datetime64[ns]")
    for d in daily_index:
        candidates = values.loc[:d]
        if candidates.empty:
            continue
        md = candidates.index[-1]
        lag = (d - md).days
        if lag <= max_lag_days:
            aligned.loc[d] = candidates.iloc[-1]
            obs_date.loc[d] = md
    lag_days = (pd.Series(daily_index, index=daily_index) - obs_date).dt.days
    return aligned, obs_date, lag_days


def rolling_percentile_rank(series: pd.Series, baseline_days=365, min_periods=30):
    s = pd.Series(series, dtype=float)
    out = []
    for i, x in enumerate(s):
        start = max(0, i - baseline_days + 1)
        window = s.iloc[start:i + 1].dropna()
        if pd.isna(x) or len(window) < min_periods:
            out.append(np.nan)
        else:
            out.append(100.0 * float((window <= x).mean()))
    return pd.Series(out, index=s.index)


def rolling_zscore(series: pd.Series, baseline_days=365, min_periods=30):
    s = pd.Series(series, dtype=float)
    mean = s.rolling(baseline_days, min_periods=min_periods).mean()
    std = s.rolling(baseline_days, min_periods=min_periods).std().replace(0, np.nan)
    return (s - mean) / std


# -----------------------------------------------------------------------------
# 2. NASA GEOS-CF v2 OPeNDAP provider
# -----------------------------------------------------------------------------

GEOS_BASE = "https://opendap.nccs.nasa.gov/dods/gmao/geos-cf/v2/ana"
GEOS_AQC = f"{GEOS_BASE}/aqc_tavg_1hr_glo_L1440x721_slv"
GEOS_MET = f"{GEOS_BASE}/met_tavg_1hr_glo_L1440x721_slv"
GEOS_XGC = f"{GEOS_BASE}/xgc_tavg_1hr_glo_L1440x721_slv"

GEOS_GASES = {
    "NO2": ("no2", 46.0055, "ug_m3"),
    "O3": ("o3", 47.9982, "ug_m3"),
    "SO2": ("so2", 64.066, "ug_m3"),
    "CO": ("co", 28.0101, "mg_m3"),
}


def _open_xarray(url: str):
    import xarray as xr
    last = None
    for engine in ("pydap", None):
        try:
            kwargs = {"decode_times": True}
            if engine:
                kwargs["engine"] = engine
            return xr.open_dataset(url, **kwargs)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Could not open OPeNDAP dataset {url}: {last}")


def _normalize_lon_for_ds(ds, lon: float) -> float:
    vals = np.asarray(ds["lon"].values)
    if np.nanmax(vals) > 180:
        return lon % 360
    return ((lon + 180) % 360) - 180


def _point_frame(ds, variables: List[str], lat: float, lon: float, start, end) -> pd.DataFrame:
    variables = [v for v in variables if v in ds.data_vars]
    if not variables:
        return pd.DataFrame()
    qlon = _normalize_lon_for_ds(ds, lon)
    sub = ds[variables].sel(lat=float(lat), lon=float(qlon), method="nearest")
    if "lev" in sub.dims:
        sub = sub.isel(lev=0)
    try:
        sub = sub.sel(time=slice(str(pd.Timestamp(start)), str(pd.Timestamp(end) + pd.Timedelta(days=1))))
    except Exception:
        pass
    frame = sub.to_dataframe().reset_index()
    if "time" not in frame:
        return pd.DataFrame()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    frame = frame[frame["time"].notna()]
    st = pd.Timestamp(start)
    en = pd.Timestamp(end) + pd.Timedelta(days=1)
    return frame[(frame.time >= st) & (frame.time < en)].copy()


def fetch_geos_cf(lat: float, lon: float, start, end):
    out = pd.DataFrame(index=pd.date_range(start, end, freq="D"))
    provenance = {}
    errors = []

    try:
        ds_aqc = _open_xarray(GEOS_AQC)
        aq_vars = ["pm25_rh35", "pm10_rh35"] + [v[0] for v in GEOS_GASES.values()]
        aq = _point_frame(ds_aqc, aq_vars, lat, lon, start, end)
    except Exception as exc:
        aq = pd.DataFrame()
        errors.append(f"GEOS-CF AQC: {exc}")

    try:
        ds_met = _open_xarray(GEOS_MET)
        met = _point_frame(ds_met, ["t", "rh", "ps", "tprec", "ts"], lat, lon, start, end)
    except Exception as exc:
        met = pd.DataFrame()
        errors.append(f"GEOS-CF MET: {exc}")

    if not aq.empty:
        aq = aq.set_index("time")
        if "pm25_rh35" in aq:
            out["PM2_5"] = aq.pm25_rh35.resample("D").mean().reindex(out.index)
            provenance["PM2_5"] = {
                "source": "NASA GEOS-CF v2", "dataset": "aqc_tavg_1hr_glo_L1440x721_slv",
                "variable": "pm25_rh35", "method": "surface pollution model field"
            }
        if "pm10_rh35" in aq:
            out["PM10"] = aq.pm10_rh35.resample("D").mean().reindex(out.index)
            provenance["PM10"] = {
                "source": "NASA GEOS-CF v2", "dataset": "aqc_tavg_1hr_glo_L1440x721_slv",
                "variable": "pm10_rh35", "method": "surface pollution model field"
            }

        if not met.empty:
            meti = met.set_index("time")
            common = aq.index.intersection(meti.index)
            if len(common):
                pressure = meti.loc[common, "ps"].values if "ps" in meti else np.full(len(common), 101325.0)
                temp = meti.loc[common, "t"].values if "t" in meti else np.full(len(common), 298.15)
                for key, (var, mw, unit) in GEOS_GASES.items():
                    if var not in aq:
                        continue
                    vals = gas_mixing_ratio_to_mass(aq.loc[common, var].values, mw, pressure, temp, unit)
                    out[key] = pd.Series(vals, index=common).resample("D").mean().reindex(out.index)
                    provenance[key] = {
                        "source": "NASA GEOS-CF v2", "dataset": "aqc_tavg_1hr_glo_L1440x721_slv",
                        "variable": var, "method": "surface mole fraction converted to mass concentration using GEOS-CF pressure and temperature"
                    }

    if not met.empty:
        m = met.set_index("time")
        if "t" in m:
            out["AIR_TEMP"] = (m.t - 273.15).resample("D").mean().reindex(out.index)
            provenance["AIR_TEMP"] = {
                "source": "NASA GEOS-CF v2", "dataset": "met_tavg_1hr_glo_L1440x721_slv",
                "variable": "t", "method": "surface air temperature, K to C"
            }
        if "rh" in m:
            rh = m.rh.astype(float)
            if rh.dropna().max() <= 1.5:
                rh = rh * 100.0
            out["REL_HUMIDITY"] = rh.resample("D").mean().reindex(out.index)
            provenance["REL_HUMIDITY"] = {
                "source": "NASA GEOS-CF v2", "dataset": "met_tavg_1hr_glo_L1440x721_slv",
                "variable": "rh", "method": "surface relative humidity; fraction converted to percent where required"
            }
        if "tprec" in m:
            # kg/m2/s == mm/s. For an hourly-average rate, multiply by 3600 and sum daily.
            out["PRECIPITATION"] = (m.tprec * 3600.0).resample("D").sum(min_count=1).reindex(out.index)
            provenance["PRECIPITATION"] = {
                "source": "NASA GEOS-CF v2", "dataset": "met_tavg_1hr_glo_L1440x721_slv",
                "variable": "tprec", "method": "hourly-average precipitation rate integrated to mm/day"
            }
        if "ts" in m:
            out["LST_GEOS_PROXY"] = (m.ts - 273.15).resample("D").mean().reindex(out.index)

    try:
        ds_xgc = _open_xarray(GEOS_XGC)
        aod_vars = [str(v) for v in ds_xgc.data_vars if str(v).startswith("aod550_")]
        xg = _point_frame(ds_xgc, aod_vars, lat, lon, start, end)
        if not xg.empty and aod_vars:
            xg = xg.set_index("time")
            out["AEROSOL_INDEX"] = xg[aod_vars].sum(axis=1, min_count=1).resample("D").mean().reindex(out.index)
            provenance["AEROSOL_INDEX"] = {
                "source": "NASA GEOS-CF v2", "dataset": "xgc_tavg_1hr_glo_L1440x721_slv",
                "variable": "+".join(aod_vars), "method": "sum of GEOS-CF 550-nm AOD components"
            }
    except Exception as exc:
        errors.append(f"GEOS-CF AOD: {exc}")

    return out, provenance, errors


# -----------------------------------------------------------------------------
# 3. Microsoft Planetary Computer public STAC mirror for NASA MODIS/HLS
# -----------------------------------------------------------------------------

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _pc_client():
    from pystac_client import Client
    import planetary_computer
    return Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)


def _sample_cog(item, asset_key: str, lon: float, lat: float) -> float:
    import rasterio
    asset = item.assets.get(asset_key)
    if not asset:
        return np.nan
    with rasterio.open(asset.href) as ds:
        val = next(ds.sample([(lon, lat)]))[0]
        if ds.nodata is not None and val == ds.nodata:
            return np.nan
        return float(val)


def fetch_modis_lst(lat, lon, start, end) -> pd.Series:
    c = _pc_client()
    search = c.search(
        collections=["modis-11A1-061"],
        intersects={"type": "Point", "coordinates": [lon, lat]},
        datetime=f"{pd.Timestamp(start).date()}/{pd.Timestamp(end).date()}"
    )
    rows = []
    for item in search.items():
        try:
            d = pd.Timestamp(item.datetime).normalize().tz_localize(None)
            raw = _sample_cog(item, "LST_Day_1km", lon, lat)
            qc = _sample_cog(item, "QC_Day", lon, lat)
            if not np.isfinite(raw):
                continue
            if np.isfinite(qc) and (int(qc) & 0b11) > 1:
                continue
            value = raw * 0.02 - 273.15
            if -100 <= value <= 100:
                rows.append((d, value))
        except Exception:
            continue
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["date", "value"])
    return df.groupby("date").value.mean().sort_index()


def fetch_modis_ndvi(lat, lon, start, end) -> pd.Series:
    c = _pc_client()
    search = c.search(
        collections=["modis-13A1-061"],
        intersects={"type": "Point", "coordinates": [lon, lat]},
        datetime=f"{pd.Timestamp(start).date()}/{pd.Timestamp(end).date()}"
    )
    rows = []
    for item in search.items():
        try:
            d = pd.Timestamp(item.datetime).normalize().tz_localize(None)
            raw = _sample_cog(item, "500m_16_days_NDVI", lon, lat)
            reliability = _sample_cog(item, "500m_16_days_pixel_reliability", lon, lat)
            if not np.isfinite(raw):
                continue
            if np.isfinite(reliability) and int(reliability) not in (0, 1):
                continue
            value = raw * 0.0001
            if -1 <= value <= 1:
                rows.append((d, value))
        except Exception:
            continue
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["date", "value"])
    return df.groupby("date").value.mean().sort_index()


def _read_aoi_band(item, band_key: str, bbox4326):
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import transform_bounds
    asset = item.assets.get(band_key)
    if not asset:
        return None, None
    with rasterio.open(asset.href) as ds:
        b = transform_bounds("EPSG:4326", ds.crs, *bbox4326, densify_pts=11)
        win = from_bounds(*b, transform=ds.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
        arr = ds.read(1, window=win, masked=True).astype("float32")
        tr = ds.window_transform(win)
    # HLS surface reflectance stored as scaled integer; STAC may expose the scale.
    scale = 0.0001
    bands_meta = asset.extra_fields.get("raster:bands") if asset.extra_fields else None
    if bands_meta and isinstance(bands_meta, list) and bands_meta[0].get("scale") is not None:
        scale = float(bands_meta[0]["scale"])
    return arr * scale, tr


def _read_hls_fmask(item, bbox4326):
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import transform_bounds
    asset = item.assets.get("Fmask")
    if not asset:
        return None
    with rasterio.open(asset.href) as ds:
        b = transform_bounds("EPSG:4326", ds.crs, *bbox4326, densify_pts=11)
        win = from_bounds(*b, transform=ds.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
        return ds.read(1, window=win, masked=True)


def _hls_metrics_for_item(item, bbox4326, green_access_m=300.0):
    from scipy.ndimage import distance_transform_edt
    coll = item.collection_id.lower()
    if "s30" in coll:
        keys = {"green": "B03", "red": "B04", "nir": "B08", "swir1": "B11"}
    else:
        keys = {"green": "B03", "red": "B04", "nir": "B05", "swir1": "B06"}

    bands = {}
    tr = None
    for name, key in keys.items():
        arr, transform = _read_aoi_band(item, key, bbox4326)
        if arr is None:
            return None
        bands[name] = arr
        if tr is None:
            tr = transform
    shape = bands["red"].shape
    if any(a.shape != shape for a in bands.values()):
        return None

    mask = np.ones(shape, dtype=bool)
    data = {}
    for name, arr in bands.items():
        a = np.asarray(arr.filled(np.nan) if np.ma.isMaskedArray(arr) else arr, dtype=float)
        data[name] = a
        mask &= np.isfinite(a) & (a > -0.2) & (a < 1.6)

    fmask = _read_hls_fmask(item, bbox4326)
    if fmask is not None and fmask.shape == shape:
        fm = np.asarray(fmask.filled(255) if np.ma.isMaskedArray(fmask) else fmask, dtype=np.uint8)
        # HLS Fmask bits 0..4 represent cirrus/cloud/adjacent-cloud/shadow/snow.
        # Water bit is intentionally not removed because water is a target feature.
        mask &= (fm & 0b00011111) == 0

    if mask.sum() < 20:
        return None

    eps = 1e-6
    green_b = data["green"]
    red = data["red"]
    nir = data["nir"]
    swir = data["swir1"]
    ndvi = (nir - red) / (nir + red + eps)
    mndwi = (green_b - swir) / (green_b + swir + eps)
    ndbi = (swir - nir) / (swir + nir + eps)

    water = mask & (mndwi > 0.10) & (ndvi < 0.25)
    green = mask & (ndvi >= 0.30) & ~water
    built = mask & (ndbi > 0.05) & (ndvi < 0.30) & (mndwi < 0)
    impervious_proxy = mask & (ndbi > 0.15) & (ndvi < 0.20) & (mndwi < 0)
    valid_n = float(mask.sum())

    pixel_size = max(abs(tr.a), abs(tr.e)) if tr is not None else 30.0
    distance = distance_transform_edt(~green, sampling=(pixel_size, pixel_size))
    green_access = mask & (distance <= float(green_access_m))

    return {
        "NDVI_HLS": float(np.nanmean(np.where(mask, ndvi, np.nan))),
        "GREEN_SPACE_PCT": float(100 * green.sum() / valid_n),
        "BUILTUP_PCT": float(100 * built.sum() / valid_n),
        "IMPERVIOUS_PCT": float(100 * impervious_proxy.sum() / valid_n),
        "SURFACE_WATER_EXTENT": float(100 * water.sum() / valid_n),
        "GREEN_ACCESS_PCT": float(100 * green_access.sum() / valid_n),
        "valid_pixels": int(valid_n),
    }


def fetch_hls_metrics(lat, lon, start, end, area_km=5.0, green_access_m=300.0, max_items=100):
    c = _pc_client()
    bbox = analysis_bbox(lat, lon, area_km)
    items = []
    for coll in ("hls2-l30", "hls2-s30"):
        try:
            items.extend(list(c.search(
                collections=[coll], bbox=list(bbox),
                datetime=f"{pd.Timestamp(start).date()}/{pd.Timestamp(end).date()}",
                max_items=max_items
            ).items()))
        except Exception:
            pass
    rows = []
    for item in sorted(items, key=lambda x: x.datetime or datetime.min.replace(tzinfo=timezone.utc)):
        try:
            metrics = _hls_metrics_for_item(item, bbox, green_access_m)
            if metrics:
                metrics["date"] = pd.Timestamp(item.datetime).normalize().tz_localize(None)
                rows.append(metrics)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    numeric = [c for c in df.columns if c != "date"]
    return df.groupby("date")[numeric].mean().sort_index()


def fetch_worldcover_static(lat, lon, area_km=5.0, green_access_m=300.0):
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import transform_bounds
    from scipy.ndimage import distance_transform_edt

    c = _pc_client()
    bbox = analysis_bbox(lat, lon, area_km)
    items = list(c.search(collections=["esa-worldcover"], bbox=list(bbox)).items())
    if not items:
        return {}
    item = sorted(items, key=lambda x: str(x.datetime or x.properties.get("start_datetime", "")), reverse=True)[0]
    asset = item.assets.get("map")
    if not asset:
        return {}
    with rasterio.open(asset.href) as ds:
        b = transform_bounds("EPSG:4326", ds.crs, *bbox, densify_pts=11)
        win = from_bounds(*b, transform=ds.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
        arr = ds.read(1, window=win, masked=True)
        tr = ds.window_transform(win)
    a = np.asarray(arr.filled(0) if np.ma.isMaskedArray(arr) else arr)
    valid = a > 0
    if valid.sum() < 20:
        return {}
    # WorldCover: 10 trees,20 shrub,30 grass,50 built,80 water,90 wetland,95 mangroves.
    green = valid & np.isin(a, [10, 20, 30, 90, 95])
    built = valid & (a == 50)
    water = valid & (a == 80)
    pixel_size = max(abs(tr.a), abs(tr.e))
    distance = distance_transform_edt(~green, sampling=(pixel_size, pixel_size))
    access = valid & (distance <= float(green_access_m))
    n = float(valid.sum())
    return {
        "GREEN_SPACE_PCT": 100 * green.sum() / n,
        "BUILTUP_PCT": 100 * built.sum() / n,
        "IMPERVIOUS_PCT": 100 * built.sum() / n,  # explicit static land-cover proxy
        "SURFACE_WATER_EXTENT": 100 * water.sum() / n,
        "GREEN_ACCESS_PCT": 100 * access.sum() / n,
        "_method": "ESA WorldCover static land-cover fallback",
        "_year": item.datetime.year if item.datetime else item.properties.get("start_datetime"),
    }


# -----------------------------------------------------------------------------
# 4. Open-Meteo fallback: soil moisture and elevation/slope
# -----------------------------------------------------------------------------

OPENMETEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPENMETEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"


def fetch_soil_moisture_fallback(lat, lon, start, end, timeout=90) -> pd.Series:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": str(pd.Timestamp(start).date()),
        "end_date": str(pd.Timestamp(end).date()),
        "hourly": "soil_moisture_0_to_7cm",
        "timezone": "UTC",
    }
    r = requests.get(OPENMETEO_ARCHIVE, params=params, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    times = pd.to_datetime(j.get("hourly", {}).get("time", []))
    vals = pd.to_numeric(j.get("hourly", {}).get("soil_moisture_0_to_7cm", []), errors="coerce")
    if len(times) != len(vals):
        return pd.Series(dtype=float)
    return pd.Series(vals, index=times).resample("D").mean()


def fetch_elevation_slope_fallback(lat, lon, area_km=5.0, n=9, timeout=90):
    half_lat = (area_km / 2) / 111.32
    half_lon = (area_km / 2) / max(1e-6, 111.32 * math.cos(math.radians(lat)))
    lats = np.linspace(lat - half_lat, lat + half_lat, n)
    lons = np.linspace(lon - half_lon, lon + half_lon, n)
    points = [(la, lo) for la in lats for lo in lons]
    values = []
    for i in range(0, len(points), 100):
        block = points[i:i + 100]
        params = {
            "latitude": ",".join(str(x[0]) for x in block),
            "longitude": ",".join(str(x[1]) for x in block),
        }
        r = requests.get(OPENMETEO_ELEVATION, params=params, timeout=timeout)
        r.raise_for_status()
        values.extend(r.json().get("elevation", []))
    arr = np.asarray(values, dtype=float).reshape(n, n)
    dx = dy = area_km * 1000 / (n - 1)
    gy, gx = np.gradient(arr, dy, dx)
    slope = np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2)))
    return {
        "value": float(np.nanmean(slope)),
        "elevation_mean_m": float(np.nanmean(arr)),
        "elevation_min_m": float(np.nanmin(arr)),
        "elevation_max_m": float(np.nanmax(arr)),
        "slope_mean_deg": float(np.nanmean(slope)),
        "slope_max_deg": float(np.nanmax(slope)),
    }


# -----------------------------------------------------------------------------
# 5. Geometry helpers, OSM accessibility, WorldPop demographics
# -----------------------------------------------------------------------------


def _bbox_polygon(lat, lon, area_km):
    from shapely.geometry import box
    w, s, e, n = analysis_bbox(lat, lon, area_km)
    return box(w, s, e, n)


def _utm_crs(lat, lon):
    from pyproj import CRS
    zone = int((lon + 180) / 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def _project_geom(geom, lat, lon):
    from pyproj import Transformer
    from shapely.ops import transform
    tr = Transformer.from_crs("EPSG:4326", _utm_crs(lat, lon), always_xy=True)
    return transform(tr.transform, geom)


OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]


def _overpass(query: str, timeout=120):
    last = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(endpoint, data={"data": query}, timeout=timeout)
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Overpass failed: {last}")


def _element_point(el):
    if "lat" in el and "lon" in el:
        return float(el["lon"]), float(el["lat"])
    c = el.get("center") or {}
    if "lat" in c and "lon" in c:
        return float(c["lon"]), float(c["lat"])
    return None


def fetch_osm_metrics(lat, lon, area_km=5.0, transit_access_m=500.0, timeout=120):
    from shapely.geometry import Point, LineString
    from shapely.ops import unary_union
    from pyproj import Transformer

    w, s, e, n = analysis_bbox(lat, lon, area_km)
    bbox = f"({s},{w},{n},{e})"
    query = f"""
    [out:json][timeout:{min(timeout, 180)}];
    (
      way["highway"]{bbox};
      node["public_transport"]{bbox}; way["public_transport"]{bbox}; relation["public_transport"]{bbox};
      node["highway"="bus_stop"]{bbox};
      node["railway"~"station|halt|tram_stop"]{bbox}; way["railway"~"station|halt|tram_stop"]{bbox};
      node["amenity"~"hospital|clinic"]{bbox}; way["amenity"~"hospital|clinic"]{bbox}; relation["amenity"~"hospital|clinic"]{bbox};
      node["amenity"~"fire_station|police"]{bbox}; way["amenity"~"fire_station|police"]{bbox};
      node["power"~"substation|plant"]{bbox}; way["power"~"substation|plant"]{bbox};
      node["man_made"="water_works"]{bbox}; way["man_made"="water_works"]{bbox};
      node["emergency"]{bbox}; way["emergency"]{bbox};
    );
    out center geom tags;
    """
    elements = _overpass(query, timeout)
    tr = Transformer.from_crs("EPSG:4326", _utm_crs(lat, lon), always_xy=True)
    center = Point(*tr.transform(lon, lat))
    aoi = _project_geom(_bbox_polygon(lat, lon, area_km), lat, lon)
    area_km2 = aoi.area / 1e6

    road_classes = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "unclassified", "service", "living_street"}
    road_length_m = 0.0
    transit_points = []
    hospitals = []
    critical = set()

    for el in elements:
        tags = el.get("tags") or {}
        eid = f"{el.get('type')}:{el.get('id')}"
        if el.get("type") == "way" and tags.get("highway") in road_classes and el.get("geometry"):
            xy = [tr.transform(float(p["lon"]), float(p["lat"])) for p in el["geometry"]]
            if len(xy) >= 2:
                road_length_m += LineString(xy).intersection(aoi).length
        p = _element_point(el)
        if p is not None:
            pp = Point(*tr.transform(*p))
            if tags.get("public_transport") or tags.get("highway") == "bus_stop" or tags.get("railway") in {"station", "halt", "tram_stop"}:
                transit_points.append(pp)
            if tags.get("amenity") in {"hospital", "clinic"}:
                hospitals.append(pp)
            if (tags.get("amenity") in {"hospital", "clinic", "fire_station", "police"}
                    or tags.get("power") in {"substation", "plant"}
                    or tags.get("man_made") == "water_works"
                    or "emergency" in tags):
                critical.add(eid)

    road_density = (road_length_m / 1000) / area_km2 if area_km2 else np.nan
    if transit_points:
        access_union = unary_union([p.buffer(float(transit_access_m)) for p in transit_points])
        transit_pct = 100 * access_union.intersection(aoi).area / aoi.area
    else:
        transit_pct = 0.0
    hospital_km = min((center.distance(p) / 1000 for p in hospitals), default=np.nan)
    critical_density = len(critical) / area_km2 if area_km2 else np.nan

    return {
        "ROAD_DENSITY": float(road_density) if np.isfinite(road_density) else np.nan,
        "TRANSPORT_ACCESS_PCT": float(min(100.0, transit_pct)),
        "HOSPITAL_ACCESS": float(hospital_km) if np.isfinite(hospital_km) else np.nan,
        "CRIT_INFRA_DENSITY": float(critical_density) if np.isfinite(critical_density) else np.nan,
        "_counts": {"transit": len(transit_points), "hospitals": len(hospitals), "critical": len(critical)},
        "_area_km2": area_km2,
    }


WORLDPOP_BASE = "https://api.worldpop.org/v2"


def _worldpop_geometry(lat, lon, area_km):
    return _bbox_polygon(lat, lon, area_km).__geo_interface__


def _worldpop_request(endpoint: str, payload: dict, timeout=90):
    url = f"{WORLDPOP_BASE}/{endpoint.lstrip('/')}"
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code in (404, 405):
            raise RuntimeError("POST not supported")
    except Exception:
        r = requests.get(url, params=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _worldpop_poll(response: dict, timeout=180):
    if not isinstance(response, dict):
        return response
    if "result" in response:
        return response["result"]
    if "total_population" in response or "population_density" in response:
        return response
    task_id = response.get("taskid") or response.get("task_id") or response.get("id")
    if not task_id:
        return response
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{WORLDPOP_BASE}/tasks/{task_id}", timeout=60)
        if r.ok:
            j = r.json()
            status = str(j.get("status", "")).lower()
            if status in {"finished", "complete", "completed", "success"}:
                return j.get("result", j)
            if status in {"failed", "error"}:
                raise RuntimeError(str(j))
        time.sleep(2)
    raise TimeoutError(f"WorldPop task {task_id} timed out")


def fetch_worldpop_population(lat, lon, year, area_km=5.0, resolution="100m"):
    year = max(2015, min(2030, int(year)))
    payload = {"geojson": _worldpop_geometry(lat, lon, area_km), "year": year, "resolution": resolution}
    result = _worldpop_poll(_worldpop_request("population", payload))
    result = result if isinstance(result, dict) else {"raw": result}
    total = result.get("total_population") or result.get("population")
    density = result.get("population_density")
    area = result.get("area_km2")
    if density is None and total is not None and area:
        density = float(total) / float(area)
    return {
        "total_population": float(total) if total is not None else np.nan,
        "population_density": float(density) if density is not None else np.nan,
        "area_km2": float(area) if area is not None else np.nan,
        "year": year,
        "raw": result,
    }


def _recursive_population_total(obj: Any) -> float:
    if isinstance(obj, (int, float, np.integer, np.floating)):
        return float(obj)
    if isinstance(obj, list):
        return sum(_recursive_population_total(x) for x in obj)
    if isinstance(obj, dict):
        preferred = []
        for k, v in obj.items():
            lk = str(k).lower()
            if any(token in lk for token in ("population", "count", "total")) and isinstance(v, (int, float)):
                preferred.append(float(v))
        if preferred:
            return max(preferred)
        return sum(_recursive_population_total(v) for v in obj.values())
    return 0.0


def fetch_worldpop_vulnerable_age(lat, lon, year, total_population, area_km=5.0, resolution="100m"):
    year = max(2015, min(2030, int(year)))
    vulnerable = 0.0
    raw = []
    for lo, hi in ((0, 4), (65, 100)):
        payload = {
            "geojson": _worldpop_geometry(lat, lon, area_km),
            "year": year, "resolution": resolution,
            "age_range": [lo, hi], "sex": "both"
        }
        try:
            result = _worldpop_poll(_worldpop_request("agesex", payload))
            raw.append(result)
            pyramid = result.get("agesex_pyramid", []) if isinstance(result, dict) else []
            if pyramid:
                vulnerable += sum(
                    float(r.get("male", 0) or 0) + float(r.get("female", 0) or 0)
                    for r in pyramid if isinstance(r, dict)
                )
            else:
                vulnerable += _recursive_population_total(result)
        except Exception as exc:
            raw.append({"error": str(exc)})
    if total_population and np.isfinite(total_population) and total_population > 0:
        return {"value": float(min(100.0, 100 * vulnerable / total_population)), "year": year, "raw": raw}
    return {"value": np.nan, "year": year, "raw": raw}


# -----------------------------------------------------------------------------
# 6. NASA GIBS current-date -> closest recent date, VISUAL ONLY
# -----------------------------------------------------------------------------

GIBS_BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
GIBS_LAYER = "MODIS_Terra_CorrectedReflectance_TrueColor"
GIBS_MATRIX = "GoogleMapsCompatible_Level9"


def _mercator_tile(lon, lat, z=9):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    lat = max(-85.05112878, min(85.05112878, lat))
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def resolve_latest_gibs_date(lat, lon, requested_date, max_back_days=10, timeout=30):
    d = pd.Timestamp(requested_date).normalize()