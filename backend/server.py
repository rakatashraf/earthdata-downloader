"""Local, bounded HDF4 conversion service. It never receives Earthdata credentials."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from native_hdf4 import convert
from pyhdf.error import HDF4Error

app = FastAPI(title='Earthdata native converter')
app.add_middleware(CORSMiddleware, allow_origins=[
    'https://rakatashraf.github.io', 'http://localhost:8001', 'http://127.0.0.1:8001',
], allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
# libhdf4 is not thread safe; serialize conversion, stream uploads to disk.
conversion_lock = asyncio.Lock()
upload_slots = asyncio.Semaphore(2)
MAX_BYTES = 512 * 1024 * 1024


@app.get('/health')
def health():
    return {'ok': True, 'formats': ['hdf4'], 'version': 1}


@app.post('/convert')
async def convert_hdf4(request: Request, component: str, bbox: str):
    try:
        bounds = json.loads(bbox)
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError()
        w, s, e, n = [float(v) for v in bounds]
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ValueError()
        wants = [component.strip()]
        if not wants[0]:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(400, 'A component and valid [west,south,east,north] bbox are required')
    if request.headers.get('origin') not in (None, 'https://rakatashraf.github.io', 'http://localhost:8001', 'http://127.0.0.1:8001'):
        raise HTTPException(403, 'Origin is not allowed')
    async with upload_slots:
        fd, path = tempfile.mkstemp(suffix='.hdf')
        size = 0
        try:
            with os.fdopen(fd, 'wb') as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, 'Granule exceeds the 512 MB native converter limit')
                    handle.write(chunk)
            with open(path, 'rb') as handle:
                if handle.read(4) != b'\x0e\x03\x13\x01':
                    raise HTTPException(415, 'Expected an original HDF4 file')
            async with conversion_lock:
                return await run_in_threadpool(convert, path, wants, [w,s,e,n])
        except (ValueError, RuntimeError, HDF4Error) as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            Path(path).unlink(missing_ok=True)
