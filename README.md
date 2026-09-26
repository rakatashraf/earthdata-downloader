# Earthdata Extractor

A browser-based NASA Earth Observation extractor with authenticated source retrieval, temporary raw-file staging, scientific conversion, spatial clipping, ground observations, and dynamic alternative-source discovery.

## Live app

https://rakatashraf.github.io/earthdata-downloader/

## Active architecture

### NASA source path

1. Search NASA CMR for collections and granules inside the requested date/spatial scope.
2. Retain and rank all useful CMR Related URLs for each granule.
3. Fail over across alternate CMR data/service endpoints when the preferred source URL fails.
4. Download the original NASA file once through the authenticated `nasa-proxy`.
5. Stage the original bytes temporarily in the private Supabase Storage bucket `earthdata-staging`.
6. Detect the scientific format from file magic bytes before conversion.
7. Convert staged files in parallel Web Workers where the format is browser-compatible.
8. Clip normalized rows to the requested geometry.
9. Delete temporary staged parts after the batch has been processed.

The staging bucket is private. Large source files are split into 5 MB binary parts so the source can be preserved byte-for-byte even though the current Supabase Free project has a 50 MB per-object limit.

Batches are quota-aware: CMR-reported file sizes are used to target roughly 700 MB of temporary staged data, with at most 24 granules per batch and up to 12 source downloads in parallel.

### HDF4 / MODIS handling

HDF4 and HDF5 are different formats. HDF4 files are detected from their magic bytes and are never sent to `h5wasm`.

For MODIS HDF-EOS2 products with a matching public Microsoft Planetary Computer representation:

1. The original NASA HDF4 granule is staged first.
2. A spatial STAC search identifies only public mirror items intersecting the requested area/date.
3. CMR results are cross-checked against those item signatures, which prevents global MODIS tiles from being staged when only a small area was requested.
4. Matching Cloud-Optimized GeoTIFF science assets are selected by component name.
5. A dataset SAS token is cached and used to read the public COG.
6. Native MODIS sinusoidal coordinates are converted to WGS84 without interpolating the source pixel values.
7. Raster scale/offset/no-data metadata are applied.
8. The output remains in the NASA satellite CSV and records the conversion backend/mirror collection in the manifest.

### Browser-native formats

The current browser workers support:

- GeoTIFF / COG
- NetCDF classic
- HDF5
- HE5
- NetCDF4 encoded as HDF5
- CSV
- JSON / GeoJSON

Scientific safeguards include `_FillValue`, `missing_value`, `valid_min`, `valid_max`, `scale_factor`, `add_offset`, native-grid preservation, and requested-geometry clipping.

## NASA failure recovery

A granule is not tied to a single URL. CMR Related URLs are ranked and alternate direct/service endpoints are retained. Staging rotates through those endpoints with retry/backoff before marking a source as unavailable.

Deterministic programming/format errors such as `ReferenceError`, `name not defined`, an HDF4/HDF5 mismatch, or an unsupported scientific alignment are not pointlessly retried as if the sixth identical exception might become philosophical and change its mind.

The manifest records:

- canonical source URL
- source URL candidate count
- source URL that actually staged successfully
- staging status/attempts/bytes/duration/error
- detected source format
- conversion status/backend/attempts/duration/error
- mirror collection when used
- source-grid row count
- final in-area row count

## Dynamic alternative-source discovery

Alternative data is never merged into the NASA satellite CSV.

The application has two alternative-source layers:

### Direct adapters

When a compatible documented API exists, values are fetched immediately. Current adapters include Open-Meteo air quality/weather, NASA POWER, WorldPop, and OpenAQ ground observations.

These adapters are not the discovery ceiling.

### Dynamic catalogs

For every component query, the application also searches public catalogs dynamically, including:

- Data.gov CKAN
- Microsoft Planetary Computer STAC
- Copernicus Data Space STAC
- Element 84 Earth Search STAC
- the daily-updated public STAC Index registry, which broadens discovery beyond the built-in catalog adapters

The number of discovered datasets depends on the component and catalog responses rather than a fixed provider count. Catalog hits are not exposed as alternative sources merely because metadata exists. A discovered dataset is promoted into the Alternative Sources section only after a compatible public CSV/JSON/GeoJSON resource has been fetched, normalized, spatially clipped, and produced usable rows. Every visible alternative source therefore has its own CSV download.

A deployed web app cannot truthfully crawl the entire unrestricted internet and automatically ingest arbitrary websites: many sources require authentication, have incompatible formats/licenses, block automated access, or expose no API. The architecture therefore uses open data catalogs and documented APIs instead of an unsafe arbitrary-URL proxy. Additional catalog adapters can be added without changing the NASA pipeline.

## Separate exports

- **NASA satellite CSV**: NASA satellite rows only.
- **OpenAQ CSV**: OpenAQ ground measurements only.
- **Alternative provider CSV**: one separate CSV per verified alternative provider, including dynamically discovered providers that successfully yield normalized data.
- **Granule manifest JSON**: NASA staging/conversion provenance and diagnostics.

Normalized scientific rows use:

`latitude, longitude, timestamp, date, value, variable, unit, satellite, collection, granule, data_cycle, source, source_url`

## Geometry

Bounding boxes use exactly two inputs:

- SW: `latitude, longitude`
- NE: `latitude, longitude`

Polygon, circle, point, and line requests are also supported. Returned source-grid rows are clipped again after conversion.

## Complexity and throughput

No remote data system can have literal O(1) runtime with respect to file count or total bytes. Every source byte must be transferred at least once. The extractor minimizes repeated work by staging each original once, using parallel I/O/worker conversion, spatially filtering MODIS tiles before staging, caching public STAC mappings/tokens, and avoiding retries for deterministic parser errors.

## Deployment

GitHub Pages deploys only after `scripts/validate.sh` passes. The validation gate covers the SW/NE UI contract, source proxies, staging, worker conversion, scientific metadata handling, HDF4 routing, MODIS public-COG conversion, NASA URL failover, dynamic catalog discovery, separate source exports, and credential-shaped literals.


## Exact-granule direct mode

The active NASA path now resolves the complete CMR granule set for the selected collection, geometry and exact requested date range **before any data file is downloaded**.

Pipeline:

1. Query CMR with the selected collection ID, exact temporal range and geometry.
2. Keep only downloadable, deduplicated granules whose temporal extent intersects the requested range.
3. Freeze and sort that exact NASA granule list. No nearest-prior fallback is used in this mode.
4. Download those exact granules directly through the authenticated NASA proxy with failover across CMR Related URLs.
5. Send each downloaded buffer directly to the conversion worker. Supabase staging is not on the normal critical path anymore.
6. If a genuine temporary transfer failure survives direct retries, only that failed granule is sent through the Supabase staging recovery path.
7. Convert to normalized CSV rows and record concept ID, native ID, source URL, actual download endpoint, detected format, bytes, timing, backend and error state in the manifest.

### HDF5 geolocation fallback

HDF5/NetCDF4 conversion now supports three geolocation strategies:

- explicit latitude/longitude arrays, including common NASA names such as `cell_lat` / `cell_lon`;
- HDF-EOS `StructMetadata` regular grids, including geographic and sinusoidal grid definitions;
- regular-grid geospatial bound attributes such as geospatial min/max latitude/longitude.

A valid HDF-EOS grid therefore does not need a literal `Latitude` or `Longitude` dataset to be converted.


## Fast Collection Mode

The active extractor targets a 60-second wall-clock completion time for a selected collection when NASA service capabilities and network conditions make that feasible.

After the exact CMR granule list is frozen:

1. Small collections skip service-orchestration overhead and use aggressive parallel direct download/conversion.
2. Larger collections query the NASA Harmony capabilities endpoint.
3. When the collection supports bounding-box reduction, Harmony is asked to process only the selected SW/NE area, exact time window and matching component variable when available.
4. Concatenation is requested when the collection supports it, reducing many input granules to one or a few outputs.
5. CSV output is preferred when Harmony advertises it; otherwise reduced NetCDF/GeoTIFF/HDF outputs are downloaded and converted locally.
6. Harmony fast processing has a strict time budget. If it does not complete quickly enough, the browser falls back to the exact-granule direct path instead of waiting indefinitely.
7. Direct fallback parallelism scales with file size, CPU and available browser memory.

For smaller exact sets, CMR granule concept IDs are included directly in the Harmony request. Very large sets use the frozen exact temporal/spatial constraints plus the frozen granule count as the processing limit.

A literal universal one-minute guarantee is not technically possible for arbitrary collections because NASA processing time, remote object size and internet throughput are external constraints. Fast Collection Mode minimizes transferred bytes and service overhead so the application has the best practical chance of meeting the one-minute target.


## Immediate NASA Download Mode

The normal NASA path no longer waits for Harmony or another server-side preparation job.

Active sequence:

1. CMR searches the exact requested date range and geometry.
2. Granule metadata pages are fetched in parallel when CMR reports more than one page.
3. Selected collections are resolved concurrently.
4. The exact downloadable granule list is deduplicated.
5. Downloads start immediately.
6. For each NASA host, the browser briefly attempts a direct authenticated fetch. If that host does not support browser CORS, the result is cached and subsequent granules use the streaming NASA proxy immediately.
7. Conversion begins as soon as each individual file finishes downloading; there is no requirement for the rest of the collection to become ready first.
8. Supabase staging is used only for genuine transfer recovery.
9. Alternative-source fetching is deferred until the NASA extraction has completed so it cannot steal bandwidth or CPU from the main satellite job.

Harmony helper code may remain available for future optional modes, but it is not called by the normal extraction path.
