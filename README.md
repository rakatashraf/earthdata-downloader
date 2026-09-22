# Earthdata Extractor

End-to-end NASA Earth Observation discovery, authenticated granule retrieval, source-grid conversion, spatial clipping, and ground-observation enrichment.

## Live application

https://rakatashraf.github.io/earthdata-downloader/

## Architecture

- **Frontend:** GitHub Pages
- **NASA metadata:** NASA CMR + CMR GraphQL
- **NASA authenticated downloads:** Supabase Edge Function `nasa-proxy`
- **Ground observations:** OpenAQ v3 through Supabase Edge Function `openaq-proxy`
- **Scientific conversion:** browser-side GeoTIFF, NetCDF classic, HDF5/HE5 and NetCDF4-compatible HDF5 readers

Credentials are entered at runtime. Earthdata and OpenAQ credentials are not committed to this repository.

## Extraction behavior

- Earthdata token verification before searches.
- Component/variable search.
- Bounding box input uses exactly two fields:
  - SW: `latitude, longitude`
  - NE: `latitude, longitude`
- Polygon, circle, point and line queries are also supported.
- CMR searches use the requested geometry and date range.
- Collections are shown only after granule availability is verified.
- If no exact-period NASA granules exist, the nearest prior granule is used.
- Multiple collections can be selected.
- All granules in the selected scope are attempted; there is no artificial 50-granule conversion cap.
- Transient NASA download failures are retried.
- NASA authentication redirects are followed server-side.
- Signed S3 and trusted CloudFront storage redirects are handled without forwarding the Earthdata bearer token to storage/CDN hosts.
- Returned source-grid rows are clipped again to the requested geometry after conversion.
- No interpolation or silent spatial resampling is performed.

## Scientific-data safeguards

### HDF5 / HE5 / NetCDF4

- Latitude and longitude datasets must be identifiable.
- Component-related variables are preferred.
- `_FillValue` and `missing_value` values are excluded.
- `valid_min` and `valid_max` are honored when present.
- `scale_factor` and `add_offset` are applied when present.
- Values are emitted only when their dimensions can be aligned safely to the source geolocation grid.

### NetCDF classic

- Latitude/longitude variables are required.
- Packed-value metadata is applied.
- Component matching avoids common QA/error/uncertainty arrays unless they are the requested variable.

### GeoTIFF

- Native geographic grids are preserved.
- EPSG:3857 coordinates are converted to latitude/longitude without resampling the raster values.
- Unsupported projected CRS files are rejected rather than incorrectly treating projected X/Y coordinates as longitude/latitude.

## Normalized CSV columns

`latitude, longitude, timestamp, date, value, variable, unit, satellite, collection, granule, data_cycle, source, source_url`

Every value row retains its source granule and collection metadata.

## Granule manifest

The manifest includes discovery metadata plus conversion diagnostics:

- collection
- granule
- start/end timestamps
- satellite/platform
- data cycle
- source URL
- conversion status
- source row count
- in-area row count
- conversion error

## Ground observations

For OpenAQ-supported air-quality components, the application:

1. finds the matching OpenAQ parameter,
2. finds stations and sensors inside the requested area,
3. checks sensor date coverage,
4. requests the exact date range,
5. falls back to the nearest prior reading when the exact range is empty.

## Backend security

The NASA proxy accepts initial download targets only from approved NASA/DAAC domains. Storage/CDN domains are accepted only as redirects from that trusted chain. Arbitrary proxy targets are rejected.

The current GES DISC CloudFront distribution used by OMI MINDS is explicitly trusted, while other CloudFront/S3 hosts must present recognizable signed-storage URL parameters.

## Deployment validation

Every push to `main` runs `scripts/validate.sh` before GitHub Pages deployment. The deployment is rejected if key product contracts regress, including:

- four-field bounding boxes returning,
- direct browser NASA granule downloads,
- the old 50-granule conversion cap,
- missing spatial clipping,
- missing scientific packing/fill handling,
- missing proxy redirect protections,
- credential-shaped literals appearing in the repository.

## Operational limits

This is an interactive browser-based scientific extractor. Very large multi-year requests can still be constrained by browser RAM and the user's network because converted rows are held client-side before CSV export. The serverless proxies stream files and do not intentionally resample them.

There is no hard one-second-per-granule guarantee; file size, provider latency, authentication redirects, decompression, and device performance determine processing time.

## Authoritative services

- NASA CMR: https://cmr.earthdata.nasa.gov/search/
- NASA CMR GraphQL: https://graphql.earthdata.nasa.gov/api
- Earthdata Login: https://urs.earthdata.nasa.gov/
- OpenAQ v3: https://api.openaq.org/v3
