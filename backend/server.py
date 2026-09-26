"""Local compatibility converter for NASA Earth science formats."""
import asyncio, json, os, tempfile
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from native_hdf4 import convert as convert_hdf4
from native_science import convert_file, convert_zarr
from pyhdf.error import HDF4Error

app=FastAPI(title='Earthdata native converter')
ORIGINS=['https://rakatashraf.github.io','http://localhost:8001','http://127.0.0.1:8001']
app.add_middleware(CORSMiddleware,allow_origins=ORIGINS,allow_methods=['GET','POST'],allow_headers=['Content-Type','X-Earthdata-Token','X-Satellite','X-Collection','X-Granule','X-Data-Cycle','X-Source-Url','X-Timestamp'])
conversion_lock=asyncio.Lock(); upload_slots=asyncio.Semaphore(2); MAX_BYTES=1024*1024*1024
FORMATS=['hdf4','hdf5','hdf-eos5','netcdf','geotiff','ascii','plain-text','csv','json','geojson','zarr']

def _params(component,bbox):
    try:
        b=json.loads(bbox); w,s,e,n=[float(v) for v in b]
        if len(b)!=4 or not(-180<=w<e<=180 and -90<=s<n<=90) or not component.strip(): raise ValueError()
        return [w,s,e,n]
    except Exception: raise HTTPException(400,'A component and valid [west,south,east,north] bbox are required')
def _origin(req):
    if req.headers.get('origin') not in (None,*ORIGINS): raise HTTPException(403,'Origin is not allowed')
def _meta(request):
    return {'satellite':request.headers.get('x-satellite',''),'collection':request.headers.get('x-collection',''),'granule':request.headers.get('x-granule',''),'data_cycle':request.headers.get('x-data-cycle',''),'source':'NASA Earthdata','source_url':request.headers.get('x-source-url',''),'timestamp':request.headers.get('x-timestamp','')}

@app.get('/health')
def health(): return {'ok':True,'formats':FORMATS,'version':2,'max_bytes':MAX_BYTES}

@app.post('/convert')
async def convert(request:Request,component:str,bbox:str,format:str=''):
    bounds=_params(component,bbox); _origin(request)
    async with upload_slots:
        suffix='.'+(format or 'bin').replace('/','_'); fd,path=tempfile.mkstemp(suffix=suffix); size=0
        try:
            with os.fdopen(fd,'wb') as h:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>MAX_BYTES: raise HTTPException(413,'Granule exceeds native converter limit')
                    h.write(chunk)
            with open(path,'rb') as h: sig=h.read(8)
            if sig[:4]==b'\x0e\x03\x13\x01' or format.lower()=='hdf4':
                async with conversion_lock:
                    result=await run_in_threadpool(convert_hdf4,path,[component.strip()],bounds)
                for row in result.get('rows',[]): row.update({k:v for k,v in _meta(request).items() if k not in row})
                return result
            if not format.strip():
                raise HTTPException(415,'Scientific format was not identified')
            result=await run_in_threadpool(convert_file,path,format,component.strip(),bounds,_meta(request))
            result['sourceRows']=len(result.get('rows',[])); result['coordinateBackend']='native-python'
            return result
        except HTTPException: raise
        except (ValueError,RuntimeError,HDF4Error) as exc: raise HTTPException(422,str(exc)) from exc
        finally: Path(path).unlink(missing_ok=True)

@app.post('/convert-zarr')
async def zarr(request:Request):
    _origin(request)
    try: body=await request.json(); url=str(body['url']); component=str(body['component']); bounds=[float(v) for v in body['bbox']]
    except Exception: raise HTTPException(400,'url, component and bbox are required')
    u=urlparse(url)
    if u.scheme not in ('https','http','s3') or u.username or u.password: raise HTTPException(400,'Zarr URL must use http(s) or s3')
    token=request.headers.get('x-earthdata-token','').strip()
    try:
        result=await run_in_threadpool(convert_zarr,url,component,bounds,{'satellite':body.get('satellite',''),'collection':body.get('collection',''),'granule':body.get('granule',''),'data_cycle':body.get('dataCycle',''),'source':'NASA Earthdata / Zarr','source_url':url,'timestamp':body.get('timestamp','')},token)
        result['sourceRows']=len(result.get('rows',[])); result['coordinateBackend']='xarray-zarr'
        return result
    except Exception as exc: raise HTTPException(422,'Zarr conversion failed: '+str(exc)) from exc
