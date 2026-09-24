#!/usr/bin/env bash
set -euxo pipefail

node --check app.js
node --check granule-worker.js

# UI contract: bounding box must be exactly SW and NE coordinate fields.
grep -q 'id="swCoord"' index.html
grep -q 'id="neCoord"' index.html
! grep -q 'id="swLat"' index.html
! grep -q 'id="swLon"' index.html
! grep -q 'id="neLat"' index.html
! grep -q 'id="neLon"' index.html

# Architecture contract: authenticated data downloads must use proxies.
grep -q "const NASA_PROXY_BASE=" app.js
grep -q "const OPENAQ_PROXY_BASE=" app.js
grep -q "const ALT_PROXY_BASE=" app.js
grep -q "const STAGE_PROXY_BASE=" app.js
! grep -q "fetch(g.url" app.js

# No silent browser conversion cap and requested-area clipping must exist.
! grep -q "slice(0,50)" app.js
grep -q "function clipRows" app.js
grep -q "conversion_status" app.js
grep -q "new Worker" app.js
grep -q "class GranuleWorkerPool" app.js
grep -q "function conversionConcurrency" app.js
grep -q "runReliablePool" app.js
grep -q "STAGING_BATCH_MAX=24" app.js
grep -q "STAGING_TARGET_BYTES=700" app.js
grep -q "stagingBatches" app.js
grep -q "STAGING_CONCURRENCY=12" app.js
grep -q "stageOne" app.js
grep -q "maxAttempts=Math.max(5" app.js
grep -q "sourceUrls" app.js
grep -q "stagedBuffer" app.js
grep -q "cleanupStage" app.js
grep -q "convertOneReliable(g,start+i,total,progress,pool,3)" app.js
grep -q "Promise.allSettled(ready.map" app.js
grep -q "original source granule(s) queued for Supabase staging" app.js
test -f supabase/functions/stage-granule/index.ts
grep -q "fetchAlternatives" app.js
grep -q "Open-Meteo Air Quality" app.js
grep -q "NASA POWER" app.js
grep -q "WorldPop" app.js
grep -q "downloadAlternativeProvider" app.js
grep -q "nasa_satellite_" app.js
grep -q "openaq_" app.js
test -f supabase/functions/alternative-proxy/index.ts
! grep -q "q.map((g,i)=>convertOneGranule" app.js
grep -q "granule-worker.js" app.js

# Scientific hygiene.
grep -q "scale_factor" app.js
grep -q "_FillValue" app.js
grep -q "Projected GeoTIFF EPSG" app.js

# Proxy must reject arbitrary initial URLs and handle signed NASA storage/CDN redirects.
grep -q "isProviderHost" supabase/functions/nasa-proxy/index.ts
grep -q "isSignedCloudFront" supabase/functions/nasa-proxy/index.ts
grep -q "isSignedS3" supabase/functions/nasa-proxy/index.ts
grep -q "d2b3c3wh8s6en5.cloudfront.net" supabase/functions/nasa-proxy/index.ts

# Reject obvious credential-shaped literals.
if grep -REn --exclude-dir=.git --exclude='validate.sh' '(Bearer[[:space:]]+eyJ[A-Za-z0-9_-]{20,}|[0-9a-fA-F]{64})' .; then
  echo 'Credential-shaped literal detected. Refusing deployment.'
  exit 1
fi

grep -q "source_format==='hdf4'" app.js

grep -q "convertHdf4ViaPublicCog" app.js

grep -q "filterModisGranulesWithStac" app.js

grep -q "planetarycomputer.microsoft.com" app.js

grep -q "catalog.data.gov" app.js

grep -q "stac.dataspace.copernicus.eu" app.js

grep -q "earth-search.aws.element84.com" app.js

grep -q "rankGranuleUrls" app.js

grep -q "sourceUrls:ranked.map" app.js

grep -q "modis_sinusoidal" granule-worker.js

grep -q "source_format" supabase/functions/stage-granule/index.ts

grep -q "blob.core.windows.net" supabase/functions/alternative-proxy/index.ts

grep -q "const STAC_REGISTRY=" app.js

grep -q "STAC Index Registry" app.js

grep -q "source_format:g.sourceFormat" app.js

grep -q "Every visible source will have a CSV download" app.js

grep -q "status==='ok'&&Number(p.rows)>0" app.js

grep -q "Download CSV" app.js

grep -q "materializeDiscoveredDataset" app.js

grep -q "fetchPublicTabularResource" app.js

! grep -q "Download source metadata" app.js

! grep -q "downloadProviderMetadata" app.js

grep -q "identityTokens" app.js

grep -q "findCoordVar" app.js

grep -q "h5PickCoord" app.js

grep -q "findCoordVar" granule-worker.js

grep -q "h5PickCoord" granule-worker.js


! grep -q "HDF5/NetCDF4 file has no identifiable latitude/longitude datasets" app.js

! grep -q "HDF5/NetCDF4 file has no identifiable latitude/longitude datasets" granule-worker.js

! grep -q "ProducerGranuleId||dg.DayNightFlag" app.js

grep -q "granule-worker.js?v=20260924-2216" app.js

grep -Fq "'value' in obj" app.js

grep -Fq "'value' in obj" granule-worker.js

grep -q "return'permanent'" app.js

grep -q "if(!g.url||!g.sourceUrls.length)continue" app.js

echo "Static product validation passed."
