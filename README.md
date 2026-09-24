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

The number of discovered datasets depends on the component and catalog responses rather than a fixed provider count. Catalog discoveries appear separately with downloadable source metadata. Directly fetched providers expose their own CSV download.

A deployed web app cannot truthfully crawl the entire unrestricted internet and automatically ingest arbitrary websites: many sources require authentication, have incompatible formats/licenses, block automated access, or expose no API. The architecture therefore uses open data catalogs and documented APIs instead of an unsafe arbitrary-URL proxy. Additional catalog adapters can be added without changing the NASA pipeline.

## Separate exports

- **NASA satellite CSV**: NASA satellite rows only.
- **OpenAQ CSV**: OpenAQ ground measurements only.
- **Alternative provider CSV**: one separate CSV per direct alternative provider.
- **Catalog metadata JSON**: one metadata export per dynamically discovered catalog source.
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
