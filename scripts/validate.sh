#!/usr/bin/env bash
set -euo pipefail

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
! grep -q "fetch(g.url" app.js

# No silent browser conversion cap and requested-area clipping must exist.
! grep -q "slice(0,50)" app.js
grep -q "function clipRows" app.js
grep -q "conversion_status" app.js
grep -q "new Worker" app.js
grep -q "class GranuleWorkerPool" app.js
grep -q "function conversionConcurrency" app.js
grep -q "maxAttempts=7" app.js
grep -q "runReliablePool" app.js
grep -q "Recovery pass:" app.js
grep -q "harmonySubsetCollection" app.js
grep -q "harmonySubmitChunk" app.js
grep -q "skipPreview" app.js
grep -q "monthChunks" app.js
grep -q "harmonyVariable" app.js
grep -q "harmonyOpendapForGranule" app.js
grep -q "harmonyOpendapCollection" app.js
grep -q "application/x-netcdf4;profile=opendap_url" app.js
grep -q "p.set(\x27f\x27,fmt)" app.js
grep -q "concatenate" app.js
grep -q "Math.min(12,chunks.length)" app.js
grep -q "fetchAlternatives" app.js
grep -q "Open-Meteo Air Quality" app.js
grep -q "NASA POWER" app.js
grep -q "WorldPop" app.js
grep -q "downloadAlternativeProvider" app.js
grep -q "Download this source CSV" app.js
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

echo "Static product validation passed."
