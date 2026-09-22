import http from 'node:http';

const PORT = Number(process.env.PORT || 3000);
const OPENAQ = 'https://api.openaq.org/v3';
const ALLOWED_ORIGINS = new Set([
  'https://rakatashraf.github.io'
]);

function cors(req, res) {
  const origin = req.headers.origin || '';
  const local = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if (ALLOWED_ORIGINS.has(origin) || local) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-OpenAQ-Key');
  res.setHeader('Access-Control-Max-Age', '86400');
  res.setHeader('Cache-Control', 'no-store');
}

function json(res, status, payload) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(payload));
}

function allowedPath(pathname) {
  return (
    pathname === '/api/openaq/parameters' ||
    pathname === '/api/openaq/locations' ||
    /^\/api\/openaq\/locations\/\d+\/(sensors|latest)$/.test(pathname) ||
    /^\/api\/openaq\/sensors\/\d+\/(measurements|hours|days|years)$/.test(pathname)
  );
}

const server = http.createServer(async (req, res) => {
  cors(req, res);

  if (req.method === 'OPTIONS') {
    res.statusCode = 204;
    return res.end();
  }

  const origin = req.headers.origin || '';
  const local = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if (origin && !ALLOWED_ORIGINS.has(origin) && !local) {
    return json(res, 403, { error: 'Origin not allowed' });
  }

  const url = new URL(req.url || '/', 'http://localhost');

  if (req.method === 'GET' && url.pathname === '/health') {
    return json(res, 200, { ok: true, service: 'earthdata-openaq-proxy' });
  }

  if (req.method !== 'GET' || !allowedPath(url.pathname)) {
    return json(res, 404, { error: 'Route not found' });
  }

  const key = String(req.headers['x-openaq-key'] || '').trim();
  if (!key) {
    return json(res, 401, { error: 'OpenAQ API key is required' });
  }

  const relativePath = url.pathname.replace('/api/openaq', '');
  const upstream = new URL(OPENAQ + relativePath);
  url.searchParams.forEach((value, name) => upstream.searchParams.append(name, value));

  try {
    const response = await fetch(upstream, {
      method: 'GET',
      headers: {
        'X-API-Key': key,
        'Accept': 'application/json',
        'User-Agent': 'earthdata-downloader/1.0'
      },
      signal: AbortSignal.timeout(30000)
    });

    const body = await response.text();
    res.statusCode = response.status;
    res.setHeader('Content-Type', response.headers.get('content-type') || 'application/json; charset=utf-8');
    res.setHeader('X-Upstream-Status', String(response.status));
    res.end(body);
  } catch (error) {
    const timeout = error?.name === 'TimeoutError' || error?.name === 'AbortError';
    json(res, timeout ? 504 : 502, {
      error: timeout ? 'OpenAQ request timed out' : 'OpenAQ request failed',
      detail: error?.message || String(error)
    });
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`OpenAQ proxy listening on port ${PORT}`);
});
