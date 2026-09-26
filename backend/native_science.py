import io, json, math, re
from pathlib import Path
import numpy as np
import pandas as pd

LAT_NAMES=('latitude','lat','nav_lat','geolat','geolocation_latitude')
LON_NAMES=('longitude','lon','lng','nav_lon','geolon','geolocation_longitude')
TIME_NAMES=('time','timestamp','datetime','date')
def _norm(x): return re.sub(r'[^a-z0-9]','',str(x).lower())
def _pick(names,aliases):
    ns=list(names)
    for a in aliases:
        for n in ns:
            if _norm(n)==_norm(a): return n
    for a in aliases:
        for n in ns:
            if _norm(a) in _norm(n): return n
    return None
def _inside(lat,lon,b):
    w,s,e,n=b
    return np.isfinite(lat)&np.isfinite(lon)&(lon>=w)&(lon<=e)&(lat>=s)&(lat<=n)
def _component_score(name,wants):
    n=_norm(name); score=0
    for w in wants:
        q=_norm(w)
        if not q: continue
        if n==q: score=max(score,1000)
        elif n.endswith(q) or n.startswith(q): score=max(score,500+len(q))
        elif q in n: score=max(score,100+len(q))
    return score
def _rows_from_frame(df,component,bounds,meta):
    if df.empty:return []
    cols=list(df.columns); latc=_pick(cols,LAT_NAMES); lonc=_pick(cols,LON_NAMES); timec=_pick(cols,TIME_NAMES)
    if latc is None or lonc is None: raise ValueError('Tabular data has no identifiable latitude/longitude columns')
    numeric=[c for c in cols if c not in {latc,lonc,timec} and pd.api.types.is_numeric_dtype(df[c])]
    ranked=sorted(numeric,key=lambda c:_component_score(c,[component]),reverse=True)
    if ranked and _component_score(ranked[0],[component])>0:numeric=ranked[:1]
    if not numeric:raise ValueError('Tabular data has no numeric science value column')
    out=[]
    for _,r in df.iterrows():
        try:lat=float(r[latc]);lon=float(r[lonc])
        except Exception:continue
        if not(bounds[1]<=lat<=bounds[3] and bounds[0]<=lon<=bounds[2]):continue
        ts=str(r[timec]) if timec is not None and pd.notna(r[timec]) else meta.get('timestamp','')
        for c in numeric[:4]:
            try:v=float(r[c])
            except Exception:continue
            if math.isfinite(v):out.append({**meta,'latitude':lat,'longitude':lon,'timestamp':ts,'date':ts[:10],'value':v,'variable':str(c),'unit':''})
    return out
def convert_text(path,component,bounds,meta):
    raw=Path(path).read_text(errors='replace')
    for sep in [',','\t',';',r'\s+']:
        try:
            df=pd.read_csv(io.StringIO(raw),sep=sep,engine='python',comment='#')
            if len(df.columns)>1:return _rows_from_frame(df,component,bounds,meta)
        except Exception:pass
    raise ValueError('ASCII/plain-text parser could not identify a delimited table')
def convert_json(path,component,bounds,meta):
    obj=json.loads(Path(path).read_text(errors='replace'))
    if isinstance(obj,dict) and isinstance(obj.get('features'),list):
        rows=[]
        for f in obj['features']:
            g=f.get('geometry') or {};p=f.get('properties') or {};c=g.get('coordinates')
            if g.get('type')=='Point' and isinstance(c,list) and len(c)>=2:rows.append({'longitude':c[0],'latitude':c[1],**p})
        return _rows_from_frame(pd.DataFrame(rows),component,bounds,meta)
    if isinstance(obj,list):return _rows_from_frame(pd.json_normalize(obj),component,bounds,meta)
    if isinstance(obj,dict):
        for k in ('data','results','items','records'):
            if isinstance(obj.get(k),list):return _rows_from_frame(pd.json_normalize(obj[k]),component,bounds,meta)
    raise ValueError('JSON structure has no safely identifiable coordinate/value records')
def _dataset_rows(ds,component,bounds,meta):
    names=list(ds.variables);latn=_pick(names,LAT_NAMES);lonn=_pick(names,LON_NAMES)
    if latn is None or lonn is None:raise ValueError('Dataset has no identifiable latitude/longitude variables')
    lat=ds[latn];lon=ds[lonn];bad=re.compile(r'quality|flag|qa|uncert|precision|error|cloud|angle|pressure|terrain|weight|bounds?',re.I)
    vars=[n for n in ds.data_vars if not bad.search(n)];vars=sorted(vars,key=lambda n:_component_score(n,[component]),reverse=True)
    if vars and _component_score(vars[0],[component])>0:vars=vars[:1]
    elif vars:vars=vars[:4]
    out=[]
    for vn in vars:
        da=ds[vn];unit=str(da.attrs.get('units',''))
        try:
            if lat.ndim==1 and lon.ndim==1 and lat.dims[0] in da.dims and lon.dims[0] in da.dims:
                sub=da.sel({lat.dims[0]:slice(bounds[1],bounds[3]),lon.dims[0]:slice(bounds[0],bounds[2])})
                yy=ds[latn].sel({lat.dims[0]:sub[lat.dims[0]]}).values;xx=ds[lonn].sel({lon.dims[0]:sub[lon.dims[0]]}).values;arr=np.asarray(sub.values)
                while arr.ndim>2:arr=arr[0]
                if arr.ndim!=2:continue
                for i,la in enumerate(np.asarray(yy)):
                    for j,lo in enumerate(np.asarray(xx)):
                        try:v=float(arr[i,j]);la=float(la);lo=float(lo)
                        except Exception:continue
                        if math.isfinite(v) and bounds[1]<=la<=bounds[3] and bounds[0]<=lo<=bounds[2]:out.append({**meta,'latitude':la,'longitude':lo,'timestamp':meta.get('timestamp',''),'date':meta.get('timestamp','')[:10],'value':v,'variable':vn,'unit':unit})
            else:
                la=np.asarray(lat.values);lo=np.asarray(lon.values);val=np.asarray(da.values);la,lo=np.broadcast_arrays(la,lo)
                while val.ndim>la.ndim:val=val[0]
                if val.shape!=la.shape:continue
                mask=_inside(la.astype(float),lo.astype(float),bounds)
                for a,b,v in zip(la[mask].ravel(),lo[mask].ravel(),val[mask].ravel()):
                    try:v=float(v)
                    except Exception:continue
                    if math.isfinite(v):out.append({**meta,'latitude':float(a),'longitude':float(b),'timestamp':meta.get('timestamp',''),'date':meta.get('timestamp','')[:10],'value':v,'variable':vn,'unit':unit})
        except Exception:continue
    if not out:raise ValueError('No coordinate-aligned numeric science values survived the requested spatial subset')
    return out
def convert_xarray(path,component,bounds,meta):
    import xarray as xr
    errors=[]
    for engine in (None,'h5netcdf','netcdf4'):
        try:
            kw={} if engine is None else {'engine':engine}
            with xr.open_dataset(path,decode_cf=True,mask_and_scale=True,**kw) as ds:return _dataset_rows(ds,component,bounds,meta)
        except Exception as e:errors.append(str(e))
    raise ValueError('NetCDF/HDF5/HDF-EOS5 native conversion failed: '+errors[-1][:400])
def convert_geotiff(path,component,bounds,meta):
    import rasterio
    from rasterio.windows import from_bounds
    out=[]
    with rasterio.open(path) as src:
        if src.crs is None:raise ValueError('GeoTIFF has no CRS')
        win=from_bounds(*bounds,transform=src.transform).round_offsets().round_lengths();arr=src.read(window=win,masked=True,boundless=True);tr=src.window_transform(win)
        for b in range(arr.shape[0]):
            ys,xs=np.where(~np.ma.getmaskarray(arr[b]))
            for y,x in zip(ys,xs):
                lon,lat=rasterio.transform.xy(tr,int(y),int(x),offset='center')
                if src.crs.to_epsg()!=4326:
                    from rasterio.warp import transform
                    lon,lat=transform(src.crs,'EPSG:4326',[lon],[lat]);lon,lat=lon[0],lat[0]
                v=float(arr[b][y,x])
                if math.isfinite(v) and bounds[1]<=lat<=bounds[3] and bounds[0]<=lon<=bounds[2]:out.append({**meta,'latitude':lat,'longitude':lon,'timestamp':meta.get('timestamp',''),'date':meta.get('timestamp','')[:10],'value':v,'variable':component if arr.shape[0]==1 else f'{component}_band_{b+1}','unit':''})
    if not out:raise ValueError('GeoTIFF contains no numeric pixels inside requested area')
    return out
def convert_file(path,fmt,component,bounds,meta):
    fmt=(fmt or '').lower()
    if fmt in ('txt','text','ascii','csv','tsv','plain','plain-text'):return {'rows':convert_text(path,component,bounds,meta)}
    if fmt in ('json','geojson'):return {'rows':convert_json(path,component,bounds,meta)}
    if fmt in ('geotiff','tif','tiff'):return {'rows':convert_geotiff(path,component,bounds,meta)}
    if fmt in ('netcdf','hdf5','hdfeos5','hdf-eos5','he5','hdf'):return {'rows':convert_xarray(path,component,bounds,meta)}
    raise ValueError('Native converter does not recognize format '+fmt)
def convert_zarr(url,component,bounds,meta,token=''):
    import fsspec,xarray as xr
    opts={}
    if token:opts['headers']={'Authorization':'Bearer '+token}
    mapper=fsspec.get_mapper(url,**opts);ds=xr.open_zarr(mapper,consolidated=None,decode_cf=True,mask_and_scale=True)
    try:return {'rows':_dataset_rows(ds,component,bounds,meta)}
    finally:ds.close()
