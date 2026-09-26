# Earthdata Extractor

[Open the app](https://rakatashraf.github.io/earthdata-downloader/).

Search exact NASA CMR collections and granules for a component, date range and
geometry, convert supported science data, and export NASA and alternative sources
separately. The browser uses the existing authenticated NASA proxy. Tokens stay
in session storage and are sent only to NASA and the configured NASA proxy.

## September 26 reliability fixes

- Fixed the GitHub Pages validation failure and synchronized app/worker asset
  versions. Old worker code must not survive a parser release.
- Fixed ORNL `/products` and `/bands` JSON envelopes. Failed discovery can retry.
  Only supported sinusoidal products use this adapter; EASE grids are not
  incorrectly treated as MODIS sinusoidal grids.
- Added an original HDF4 converter for two-dimensional HDF-EOS geographic and
  sinusoidal science grids, including the layouts of MOD13A2 and MOD13C1.
  There is no requirement for a public COG mirror or silent product substitution.
- Fixed HDF5 attributes exposed through prototype getters, preserving packing,
  fill values and units. Level-3 compound fields are resolved by metadata;
  bin numbers yield native coordinates and science means use `sum / weights`.
- Valid empty spatial intersections are accepted for Level-3 bins and aligned
  HDF5 grids. Missing variables, malformed records and unknown layouts remain
  explicit failures; arbitrary variables are not substituted for the component.
- ORNL request failures and missing dates cannot be reported as a complete cached
  result. A failed subset collection does not discard other resolved collections.
- CMR pagination errors no longer silently truncate the result list.
- Search selects one compatible collection by default. Users can select more or
  use Select All. Selecting every NDVI collection can queue thousands of files.
- Download concurrency is bounded at five. Authorization errors block remaining
  work for that collection while other collections continue. A global raw-transfer
  guard also prevents many individually-small collections from accumulating into
  thousands of fallback downloads. Optional remote cache lookups time out; successful
  local cache writes are awaited before completion.
- Point extraction retains each timestamp rather than collapsing an entire time
  series to one nearest pixel.

## Run original HDF4 conversion

GitHub Pages serves static JavaScript. It cannot execute Python or HDF4 native
libraries. Run this companion service on your computer before searching for
MOD13A2/MOD13C1. It receives the downloaded file bytes, **not your Earthdata token**.

From a checkout of this repository with Docker running:

```sh
docker build -t earthdata-native backend
docker run --rm -p 127.0.0.1:8000:8000 earthdata-native
```

Open the app, expand **Original HDF4 conversion**, leave the URL at
`http://localhost:8000`, and search again. Your browser may request local-network
access. The service must remain running during extraction.

Without Docker:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn server:app --app-dir backend --host 127.0.0.1 --port 8000
```

The converter verifies the HDF4 signature, reads grid metadata, extracts the
requested bounding window, applies fill/range/scale rules, and returns original
pixel centers. The browser applies the final polygon/circle/point/line clipping.
Uploads are streamed to temporary files and deleted after conversion. HDF4 reads
are serialized because the native library is not thread safe. Limits: 512 MB per
file and two million source pixels per subset. Other HDF4 layouts require their
own validated adapter and are reported as unsupported.

The supplied service is intended for loopback use. A shared deployment needs
operator-managed authentication, request quotas, TLS and an explicit origin list.
Do not expose this local service directly to the public internet.

## Supported browser paths

- GeoTIFF, NetCDF classic, HDF5/NetCDF4/HE5, CSV and JSON through Web Workers.
- HDF5 explicit coordinates, supported HDF-EOS grids, regular bound attributes,
  and NASA OB.DAAC integerized-sinusoidal Level-3 bins.
- Official ORNL TESViS subsets when the exact product is advertised and uses the
  adapter's supported sinusoidal projection. The current ORNL product list does
  **not** advertise MOD13A2 or MOD13C1; MOD13Q1 is a different product.

A matching extension is only a format hint, not a guarantee that every NASA
science layout is supported. Unsupported projection, dimensions or science
variables are diagnosed without fabricating data. Authentication, DAAC EULAs,
service outages and transfer bandwidth still affect completion.

## Queue, cache and provenance

The app resolves the exact CMR date/geometry selection, deduplicates granules,
checks normalized caches, then starts bounded direct download/conversion jobs.
Supabase staging is retained for temporary transfer recovery. A cache miss is
normal on a first run or after a parser schema change. It does not mean an error.
No universal zero-wait or fixed-minute guarantee is possible for large archives.

The manifest records source identifiers and URLs, route, format, bytes,
coordinate backend, conversion status, row count, timing and errors. ORNL
coverage is date-level subset coverage, not proof that each original CMR tile
was downloaded. CSV rows retain ORNL filenames and source provenance.

NASA satellite CSV, OpenAQ CSV and each alternative provider CSV remain
separate. No synthetic observations or metadata-only rows are exported as data.

## Validation and deployment

```sh
npm ci
npm test
pip install -r backend/requirements.txt httpx
python -m unittest discover -s tests -p 'test_*.py' -v
bash scripts/validate.sh
```

Tests include real synthetic HDF4 and HDF5 binary fixtures with expected native
coordinates, scale factors, fill values, compound records and empty subsets;
ORNL envelopes/partial failures; CMR pagination; auth queue blocking; and asset
version synchronization. These fixtures validate parser behavior but do not
replace an authenticated test of every NASA collection.

GitHub Actions runs the regression suite and static checks for pull requests
and main pushes. Main deploys only the browser assets to Pages. The native
converter is a separate runtime and is not deployed by Pages.

## NASA reference implementation

Reviewed [NASA Earthdata Download](https://github.com/nasa/earthdata-download),
including its queue scheduler, download verification, authentication/EULA states,
and integration documentation. Its Electron app downloads original files with
bounded concurrency and persistent state; it is not a universal CSV converter.
The browser app follows the bounded-queue and auth-blocking approach; it does
not claim feature parity with the desktop downloader's resumable transfers.

Other implementation references:

- [ORNL REST API](https://modis.ornl.gov/data/modis_webservice.html)
- [ORNL live product list](https://modis.ornl.gov/rst/api/v1/products)
- [NASA Level-3 binned format](https://oceancolor.gsfc.nasa.gov/files/resources/docs/technical/ocean_level-3_binned_data_products.pdf)
- [h5wasm](https://github.com/usnistgov/h5wasm)
