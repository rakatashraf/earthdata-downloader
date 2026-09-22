# Earthdata Extractor

Browser-first NASA Earth Observation data discovery, scoped granule retrieval, conversion, and ground-observation enrichment.

## Core features

- Earthdata bearer-token validation before downloads
- NASA CMR collection discovery by component, geometry, and date range
- Geometry modes: bounding box, polygon, circle, point, and line
- Exact-date availability first, then nearest prior data when no exact-period granules exist
- Multi-collection selection and collection-name filtering
- Granule crawling strictly within the selected temporal and spatial window
- Client-side conversion for CSV/JSON/GeoJSON/GeoTIFF/NetCDF-classic sources
- CSV normalization with latitude, longitude, timestamp, date, satellite/platform, collection, granule and cycle metadata
- OpenAQ v3 ground-observation enrichment
- GitHub Pages deployment workflow

## Security

Earthdata and OpenAQ credentials are entered in the browser and kept in memory/session storage. No API key is committed to this public repository.

## Deployment

Pushes to `main` trigger the GitHub Pages workflow in `.github/workflows/pages.yml`.

For GitHub Pages, set **Settings → Pages → Source** to **GitHub Actions** if it is not already enabled.

## Important technical note

A public GitHub Pages site cannot run a persistent Python/Node backend. This implementation therefore performs discovery and supported conversions in the browser. NASA granule formats vary widely; supported browser-side conversion paths are surfaced in the UI and unsupported binary formats are downloaded as source files instead of silently corrupting data.

The application never resamples the satellite grid unless a source service itself returns a transformed product. GeoTIFF and NetCDF-classic readers preserve source-grid values.

## Sources

- NASA CMR: https://cmr.earthdata.nasa.gov/search/
- NASA CMR GraphQL: https://graphql.earthdata.nasa.gov/api
- OpenAQ v3: https://api.openaq.org/v3
