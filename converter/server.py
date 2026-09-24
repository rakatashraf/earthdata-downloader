import json, math, os, re, subprocess, tempfile, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:
    import numpy as np
    from osgeo import gdal, osr
except Exception as exc:
    raise RuntimeError("GDAL Python bindings are required: %s" % exc)

gdal.UseExceptions()

ALLOWED_ORIGINS = {"https://rakatashraf.github.io"}
BAD = re.compile(r"quality|flag|qa|uncert|precision|error|cloud|angle|pressure|terrain|rowanomaly|weight|corner|bounds?", re.I)

ALIASES = {
    "lst": ["lst", "landsurfacetemperature", "surfacetemperature"],
    "landsurfacetemperature": ["lst", "landsurfacetemperature", "surfacetemperature"],
    "temperature": ["temperature", "airtemperature", "t2m", "temperature2m"],
    "ndvi": ["ndvi", "normalizeddifferencevegetationindex"],
    "aod": ["aod", "aerosolopticaldepth", "aerosolopticalthickness"],
    "pm25": ["pm25", "pm2.5", "pm2_5", "particulatematter25"],
    "pm2.5": ["pm25", "pm2.5", "pm2_5", "particulatematter25"],
    "pm10": ["pm10", "particulatematter10"],
    "no2": ["no2", "nitrogendioxide", "troposphericno2", "nitrogendioxidecolumn"],
    "so2": ["so2", "sulfurdioxide", "sulphurdioxide"],
    "o3": ["o3", "ozone"],
    "co": ["co", "carbonmonoxide"],
    "precipitation": ["precipitation", "rainfall", "rainrate", "precip"],
    "rainfall": ["precipitation", "rainfall", "rainrate", "precip"],
    "soilmoisture": ["soilmoisture", "soilwater", "sm"],
    "water": ["water", "surfacewater", "waterextent"],
    "elevation": ["elevation", "dem", "altitude", "height"],
    "slope": ["slope"],
}

def norm(s):
    return re.sub(r"[^a-z0-9.]", "", str(s or "").lower())

def aliases(component):
    n = norm(component)
    return [norm(x) for x in ALIASES.get(n, [n]) if x]

def cors(origin):
    local = bool(origin and re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin))
    h = {
        "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store",
        "Vary": "Origin",
    }
    if origin in ALLOWED_ORIGINS or local:
        h["Access-Control-Allow-Origin"] = origin
    return h

def read_parts(parts, path):
    with open(path, "wb") as out:
        for part in parts:
            url = str(part.get("url", ""))
            if not url.startswith("https://"):
                raise ValueError("Invalid staged part URL")
            host = (urlparse(url).hostname or "").lower()
            if not host.endswith(".supabase.co") and not host.endswith(".supabase.in"):
                raise ValueError("Staged part host is not Supabase")
            req = urllib.request.Request(url, headers={"User-Agent": "EarthdataExtractor/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)

def hdf4_magic(path):
    with open(path, "rb") as f:
        head = f.read(8)
    return head.startswith(b"\x0e\x03\x13\x01")

def hdf5_magic(path):
    with open(path, "rb") as f:
        head = f.read(8)
    return head == b"\x89HDF\r\n\x1a\n"

def subdatasets(ds):
    items = ds.GetSubDatasets() or []
    return [{"name": a, "desc": b} for a, b in items]

def pick_subdatasets(items, component):
    wants = aliases(component)
    scored = []
    for item in items:
        text = norm(item["name"] + " " + item["desc"])
        if BAD.search(item["name"] + " " + item["desc"]):
            continue
        score = max([len(w) for w in wants if w and w in text] or [0])
        if score:
            scored.append((score, item))
    if scored:
        best = max(x[0] for x in scored)
        return [x[1] for x in scored if x[0] == best]
    return []

def transform_window(ds, bbox):
    gt = ds.GetGeoTransform(can_return_null=True)
    if not gt:
        return (0, 0, ds.RasterXSize, ds.RasterYSize)
    proj = ds.GetProjection()
    if not proj:
        return (0, 0, ds.RasterXSize, ds.RasterYSize)
    src = osr.SpatialReference()
    src.ImportFromWkt(proj)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    try:
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    to_src = osr.CoordinateTransformation(dst, src)
    west, south, east, north = bbox
    pts = to_src.TransformPoints([(west,south),(west,north),(east,south),(east,north)])
    xs = [p[0] for p in pts if math.isfinite(p[0])]
    ys = [p[1] for p in pts if math.isfinite(p[1])]
    if not xs or not ys:
        return (0, 0, ds.RasterXSize, ds.RasterYSize)
    inv_ok, inv_gt = gdal.InvGeoTransform(gt)
    if not inv_ok:
        return (0, 0, ds.RasterXSize, ds.RasterYSize)
    pixels = []
    lines = []
    for x in (min(xs), max(xs)):
        for y in (min(ys), max(ys)):
            px, py = gdal.ApplyGeoTransform(inv_gt, x, y)
            pixels.append(px); lines.append(py)
    x0 = max(0, int(math.floor(min(pixels))) - 2)
    y0 = max(0, int(math.floor(min(lines))) - 2)
    x1 = min(ds.RasterXSize, int(math.ceil(max(pixels))) + 3)
    y1 = min(ds.RasterYSize, int(math.ceil(max(lines))) + 3)
    if x1 <= x0 or y1 <= y0:
        return (0,0,0,0)
    return (x0, y0, x1-x0, y1-y0)

def value_meta(band):
    nodata = band.GetNoDataValue()
    scale = band.GetScale()
    offset = band.GetOffset()
    if scale is None:
        scale = 1.0
    if offset is None:
        offset = 0.0
    md = band.GetMetadata() or {}
    if "_FillValue" in md:
        try: nodata = float(str(md["_FillValue"]).split(",")[0])
        except Exception: pass
    if "scale_factor" in md:
        try: scale = float(str(md["scale_factor"]).split(",")[0])
        except Exception: pass
    if "add_offset" in md:
        try: offset = float(str(md["add_offset"]).split(",")[0])
        except Exception: pass
    valid_min = None
    valid_max = None
    for key in ("valid_min", "valid_range"):
        if key in md:
            try:
                vals = [float(x) for x in re.split(r"[, ]+", str(md[key]).strip("{}[] ")) if x]
                if vals:
                    valid_min = vals[0]
                    if len(vals) > 1: valid_max = vals[1]
            except Exception: pass
    if "valid_max" in md:
        try: valid_max = float(str(md["valid_max"]).split(",")[0])
        except Exception: pass
    return nodata, float(scale), float(offset), valid_min, valid_max, md

def rows_for_dataset(ds, variable, component, bbox, granule):
    if ds.RasterCount < 1:
        return []
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform(can_return_null=True)
    proj = ds.GetProjection()
    if not gt or not proj:
        raise ValueError("HDF4 subdataset has no usable georeferencing")
    src = osr.SpatialReference(); src.ImportFromWkt(proj)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    try:
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    to_geo = osr.CoordinateTransformation(src, dst)
    x0,y0,w,h = transform_window(ds,bbox)
    if w <= 0 or h <= 0:
        return []
    nodata, scale, offset, valid_min, valid_max, md = value_meta(band)
    unit = band.GetUnitType() or md.get("units","")
    out = []
    west,south,east,north = bbox
    ts = str(granule.get("start") or granule.get("end") or "")
    date = ts[:10] if ts else ""
    block = 96
    for yy in range(y0, y0+h, block):
        hh = min(block, y0+h-yy)
        arr = band.ReadAsArray(x0, yy, w, hh)
        if arr is None:
            continue
        arr = np.asarray(arr)
        for r in range(hh):
            points = []
            indexes = []
            py = yy + r + 0.5
            for col in range(w):
                px = x0 + col + 0.5
                x = gt[0] + px*gt[1] + py*gt[2]
                y = gt[3] + px*gt[4] + py*gt[5]
                points.append((x,y))
                indexes.append(col)
            geo = to_geo.TransformPoints(points)
            for col, p in zip(indexes, geo):
                lon, lat = p[0], p[1]
                if not (math.isfinite(lon) and math.isfinite(lat)):
                    continue
                if lon < west or lon > east or lat < south or lat > north:
                    continue
                raw = float(arr[r,col])
                if not math.isfinite(raw):
                    continue
                if nodata is not None and raw == float(nodata):
                    continue
                if valid_min is not None and raw < valid_min:
                    continue
                if valid_max is not None and raw > valid_max:
                    continue
                val = raw * scale + offset
                if not math.isfinite(val):
                    continue
                out.append({
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": ts,
                    "date": date,
                    "value": val,
                    "variable": variable,
                    "unit": unit,
                    "satellite": granule.get("platform","NASA"),
                    "collection": granule.get("collectionShortName",""),
                    "granule": granule.get("title",""),
                    "data_cycle": granule.get("dataCycle","granule-based"),
                    "source": "NASA Earthdata",
                    "source_url": granule.get("url",""),
                })
    return out

def convert_hdf4(path, component, bbox, granule):
    root = gdal.Open(path, gdal.GA_ReadOnly)
    if root is None:
        raise ValueError("GDAL could not open the HDF4/HDF-EOS file")
    subs = subdatasets(root)
    if not subs:
        # Some HDF4 files may expose a raster directly.
        return rows_for_dataset(root, component, component, bbox, granule)
    chosen = pick_subdatasets(subs, component)
    if not chosen:
        available = [x["desc"] for x in subs[:30]]
        raise ValueError("No HDF4 subdataset matched component %r. Available: %s" % (component, " | ".join(available)))
    rows = []
    for item in chosen:
        ds = gdal.Open(item["name"], gdal.GA_ReadOnly)
        if ds is None:
            continue
        variable = item["desc"] or item["name"].split(":")[-1]
        rows.extend(rows_for_dataset(ds, variable, component, bbox, granule))
    if not rows:
        raise ValueError("Matching HDF4 subdataset(s) contained no valid pixels inside the requested bbox")
    return rows

class Handler(BaseHTTPRequestHandler):
    server_version = "EarthdataGDAL/1.0"

    def send_json(self, status, body):
        raw = json.dumps(body, separators=(",",":")).encode()
        self.send_response(status)
        for k,v in cors(self.headers.get("Origin")).items():
            self.send_header(k,v)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        for k,v in cors(self.headers.get("Origin")).items():
            self.send_header(k,v)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            hdf4 = gdal.GetDriverByName("HDF4") is not None
            self.send_json(200 if hdf4 else 500, {"ok":hdf4,"service":"earthdata-gdal-converter","gdal":gdal.VersionInfo(),"hdf4":hdf4})
        else:
            self.send_json(404,{"error":"not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/convert":
            return self.send_json(404,{"error":"not found"})
        try:
            length = int(self.headers.get("Content-Length","0"))
            if length <= 0 or length > 2_000_000:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            parts = body.get("parts") or []
            bbox = [float(x) for x in body.get("bbox",[])]
            if len(parts) == 0:
                raise ValueError("No staged Supabase parts provided")
            if len(bbox) != 4:
                raise ValueError("bbox must be [west,south,east,north]")
            component = str(body.get("component") or "").strip()
            if not component:
                raise ValueError("component is required")
            granule = body.get("granule") or {}
            suffix = os.path.splitext(str(granule.get("url","")))[1] or ".hdf"
            with tempfile.TemporaryDirectory() as td:
                path = os.path.join(td,"source"+suffix)
                read_parts(parts,path)
                if not hdf4_magic(path):
                    if hdf5_magic(path):
                        raise ValueError("File is HDF5/NetCDF4; route it to the HDF5 parser")
                    raise ValueError("File is not recognized as HDF4/HDF-EOS2")
                rows = convert_hdf4(path,component,bbox,granule)
            self.send_json(200,{"ok":True,"format":"hdf4","sourceRows":len(rows),"rows":rows})
        except Exception as exc:
            self.send_json(422,{"ok":False,"error":str(exc)})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt%args), flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT","8080"))
    if gdal.GetDriverByName("HDF4") is None:
        raise RuntimeError("GDAL HDF4 driver is missing")
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
