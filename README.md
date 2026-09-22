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
- Supported bounding-box collections use NASA Harmony server-side spatial subsetting before browser download, reducing full-swath files to the requested area whenever the collection advertises Harmony bbox support.
- Large time ranges are split into monthly Harmony jobs and up to four jobs are submitted concurrently, avoiding a single enormous transformation request.
- Harmony subset outputs use a higher safe worker ceiling because the returned files are much smaller than raw Level-2 swaths.
- Granules are processed through a bounded reliability-first parallel worker pool instead of unbounded fan-out.
- Worker count adapts to browser CPU and memory hints, with a hard safety ceiling.
- Scientific parsing runs in reusable Web Workers so NetCDF/HDF5/GeoTIFF conversions execute in parallel without creating thousands of workers.
- Transient download/worker failures are retried automatically with exponential backoff and jitter, up to seven attempts.
- Anything still transiently unresolved gets a second reduced-concurrency recovery pass with five additional attempts.
- Authorization-blocked and genuinely non-convertible granules are reported separately from transient failures.
- One granule failure does not cancel the rest of the batch.
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

This is an interactive browser-based scientific extractor. Very large multi-year requests are processed with bounded concurrency to avoid exhausting browser RAM, connection pools, worker slots, or NASA provider limits. Converted rows are still held client-side before CSV export, so extremely large exports can remain browser-memory constrained. The serverless proxies stream files and do not intentionally resample them.

There is no hard one-second-per-granule guarantee; file size, provider latency, authentication redirects, decompression, and device performance determine processing time.

## Authoritative services

- NASA CMR: https://cmr.earthdata.nasa.gov/search/
- NASA CMR GraphQL: https://graphql.earthdata.nasa.gov/api
- Earthdata Login: https://urs.earthdata.nasa.gov/
- OpenAQ v3: https://api.openaq.org/v3


## Alternative internet sources

Alternative providers are queried automatically in parallel with NASA extraction when they support the requested component. Their rows stay explicitly source-labelled and are included in the master CSV without pretending that different models, sensors, resolutions or methodologies are interchangeable.

Current automated routes:

- **Open-Meteo Air Quality** — PM2.5, PM10, NO2, SO2, O3, CO and aerosol optical depth. The app samples a 3×3 coordinate grid across the requested area and fetches hourly values.
- **Open-Meteo Historical Weather** — air temperature, relative humidity, precipitation, surface pressure, wind speed and shallow soil moisture.
- **NASA POWER** — independent hourly point meteorology at the selected area's center for supported variables including temperature, humidity, precipitation, wind and pressure.
- **WorldPop Global 2** — population totals or population density for the selected area and year.

External requests use the allow-listed Supabase Edge Function `alternative-proxy`. It accepts only documented provider hosts used by this application.

Alternative rows use the same normalized CSV columns as NASA and OpenAQ data. The `source`, `collection`, `variable`, `unit` and `source_url` columns identify their origin.

## Speed path

For Harmony-capable bounding-box collections the extractor prefers NASA-side processing over raw full-granule browser conversion:

1. Harmony capabilities are inspected.
2. Bounding-box and temporal subsetting are requested.
3. If variable subsetting is supported, only the requested component variable is sent through the Harmony transformation.
4. One-year requests are split into monthly chunks and up to 12 monthly jobs are submitted concurrently.
5. CSV is preferred when Harmony advertises CSV output; otherwise NetCDF is used.
6. The browser parallel worker pool converts only the reduced outputs.

A hard one-second end-to-end guarantee per remote granule is not possible because provider processing, transfer latency and source-file size are external constraints. The implementation instead minimizes bytes transferred and maximizes safe parallel throughput.


## Direct OPeNDAP fast path

For gridded collections whose Harmony service advertises the `sds/hoss-opendap-url` capability, the extractor does not wait for monthly transformed products to be generated and staged. It first gets the exact CMR granules for the requested time window, then requests a variable-and-bounding-box constrained OPeNDAP URL for each granule. Up to 32 lightweight URL-generation requests run concurrently. The resulting subset URLs are downloaded and parsed with the normal worker pool.

If the collection does not support this service, or if it yields no usable URLs, the application falls back to Harmony server-side transformation.

Harmony transformation requests use the documented `f` output-format query parameter, not `format`.

## Separate source exports

NASA satellite rows are never merged with alternative-provider rows.

- **Download NASA satellite CSV** exports only NASA/Harmony/OPeNDAP satellite rows.
- Each alternative provider card has its own **Download this source CSV** button.
- OpenAQ has its own **Download OpenAQ CSV** button.
- Open-Meteo Air Quality, Open-Meteo Historical Weather, NASA POWER and WorldPop therefore produce distinct files with their own source metadata and units.

This separation avoids treating satellite retrievals, modeled/reanalysis values, population products and ground-station measurements as one homogeneous dataset.


## Raw-source Supabase staging pipeline

The active NASA extraction strategy now stages original source granule bytes before conversion.

Pipeline:

1. CMR returns the original granule URLs for the selected collection/date/geometry.
2. Up to 12 source downloads are staged concurrently through the `stage-granule` Edge Function. Within each granule, 5 MB Storage parts are uploaded four-at-a-time.
3. Each raw granule is copied byte-for-byte into the private `earthdata-staging` Supabase Storage bucket.
4. A source file is split into 5 MB temporary binary parts so files larger than the Free-plan 50 MB single-object limit can still be preserved and reconstructed.
5. Because the organization is currently on Supabase Free with a 1 GB Storage quota, the browser builds quota-aware temporary batches from CMR-reported granule sizes. Each batch targets about 700 MB and is capped at 24 granules, rather than attempting to persist the entire multi-thousand-granule collection at once.
6. Once every source file in the batch is staged, conversion tasks are launched from Supabase Storage. Conversion retries therefore reread the staged copy and do not download the NASA source again.
7. After conversion/recovery completes, staged binary parts and their manifest are deleted before the next batch is staged.

The original source URL, staging attempts, staged byte count, staging duration, conversion attempts and final status are written into the granule manifest.

This design removes repeated source downloads while keeping staging temporary and within the current Storage quota.

### Complexity note

The orchestration has a fixed number of pipeline phases per batch, but remote extraction cannot be mathematically O(1): every source byte must still be transferred at least once. For N granules / B total bytes, network work is lower-bounded by O(B). The implementation minimizes repeated work rather than claiming impossible constant-time remote I/O.
