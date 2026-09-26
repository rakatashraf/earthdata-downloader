import xarray as xr, fsspec
url = "abfs://imerg/gpm-imerg-hhr.zarr"
opts = {"account_name":"ai4edataeuwest","anon":True}
try:
    ds = xr.open_zarr(url, storage_options=opts, consolidated=True, decode_times=True)
except Exception as e:
    print("OPEN1", repr(e))
    fs = fsspec.filesystem("abfs", **opts)
    mapper = fs.get_mapper("imerg/gpm-imerg-hhr.zarr")
    ds = xr.open_zarr(mapper, consolidated=True, decode_times=True)
print(ds)
print("vars", list(ds.data_vars))
for v in ds.data_vars:
    print(v, ds[v].dims, ds[v].shape, dict(ds[v].attrs))
for c in ds.coords:
    if ds[c].ndim == 1:
        print("coord", c, ds[c].shape, str(ds[c].values[0]), str(ds[c].values[-1]))
