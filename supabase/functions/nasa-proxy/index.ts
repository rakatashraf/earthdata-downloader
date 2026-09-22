const allowedOrigins = new Set([
  "https://rakatashraf.github.io",
]);

const allowedHosts = [
  "nasa.gov",
  "earthdata.nasa.gov",
  "nsidc.org",
  "usgs.gov",
  "ornl.gov",
  "alaska.edu",
];

function isGesdiscS3(url: URL) {
  const h = url.hostname.toLowerCase();
  const virtualHosted =
    h === "gesdisc-cumulus-prod-protected.s3.us-west-2.amazonaws.com" ||
    h === "gesdisc-cumulus-prod-protected.s3.amazonaws.com" ||
    h === "gesdisc-cumulus-prod-protected.s3-us-west-2.amazonaws.com";
  const pathStyle =
    (h === "s3.us-west-2.amazonaws.com" ||
     h === "s3.amazonaws.com" ||
     h === "s3-us-west-2.amazonaws.com") &&
    url.pathname.startsWith("/gesdisc-cumulus-prod-protected/");
  return virtualHosted || pathStyle;
}

function urlAllowed(url: URL) {
  const h = url.hostname.toLowerCase();
  if (allowedHosts.some((suffix) => h === suffix || h.endsWith("." + suffix))) return true;

  return isGesdiscS3(url);
}

function cors(origin: string | null) {
  const local = !!origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  const allow = origin && (allowedOrigins.has(origin) || local) ? origin : "";
  return {
    ...(allow ? { "Access-Control-Allow-Origin": allow } : {}),
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Earthdata-Token",
    "Access-Control-Expose-Headers": "Content-Type, Content-Length, Content-Disposition, X-Final-URL, X-Upstream-Status",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
}

function json(status: number, body: unknown, headers: Record<string, string>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
  });
}

function cookiePair(raw: string) {
  return raw.split(";")[0]?.trim() || "";
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  const headers = cors(origin);

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers });
  }

  const local = !!origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if (origin && !allowedOrigins.has(origin) && !local) {
    return json(403, { error: "Origin not allowed" }, headers);
  }

  if (req.method !== "GET") {
    return json(405, { error: "Only GET is allowed" }, headers);
  }

  const requestUrl = new URL(req.url);
  const targetRaw = requestUrl.searchParams.get("url");
  const token = (req.headers.get("x-earthdata-token") || "").trim();

  if (!targetRaw) return json(400, { error: "Missing target URL" }, headers);
  if (!token) return json(401, { error: "Earthdata bearer token is required" }, headers);

  let current: URL;
  try {
    current = new URL(targetRaw);
  } catch {
    return json(400, { error: "Invalid target URL" }, headers);
  }

  if (current.protocol !== "https:" || !urlAllowed(current)) {
    return json(403, {
      error: "Target host is not an approved Earthdata/DAAC host",
      host: current.hostname,
    }, headers);
  }

  const cookies = new Map<string, string>();
  let upstream: Response | null = null;

  try {
    for (let hop = 0; hop < 10; hop++) {
      if (current.protocol !== "https:" || !urlAllowed(current)) {
        return json(403, {
          error: "Redirected to an unapproved host: " + current.hostname,
          host: current.hostname,
          url: current.toString(),
        }, headers);
      }

      const cookieHeader = [...cookies.values()].filter(Boolean).join("; ");
      const s3Hop = isGesdiscS3(current);
      upstream = await fetch(current.toString(), {
        method: "GET",
        redirect: "manual",
        headers: {
          "Accept": "*/*",
          "User-Agent": "earthdata-downloader/1.0",
          ...(!s3Hop ? { "Authorization": "Bearer " + token } : {}),
          ...(!s3Hop && cookieHeader ? { "Cookie": cookieHeader } : {}),
        },
      });

      const getSetCookie = (upstream.headers as any).getSetCookie;
      const setCookies: string[] = typeof getSetCookie === "function"
        ? getSetCookie.call(upstream.headers)
        : (upstream.headers.get("set-cookie") ? [upstream.headers.get("set-cookie") as string] : []);

      for (const raw of setCookies) {
        const pair = cookiePair(raw);
        const eq = pair.indexOf("=");
        if (eq > 0) cookies.set(pair.slice(0, eq), pair);
      }

      if (![301,302,303,307,308].includes(upstream.status)) break;

      const location = upstream.headers.get("location");
      if (!location) break;
      current = new URL(location, current);
    }

    if (!upstream) {
      return json(502, { error: "No response from Earthdata host" }, headers);
    }

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return json(upstream.status, {
        error: "NASA/DAAC download failed",
        status: upstream.status,
        final_url: current.toString(),
        detail: text.slice(0, 1500),
      }, {
        ...headers,
        "X-Final-URL": current.toString(),
        "X-Upstream-Status": String(upstream.status),
      });
    }

    const contentType = upstream.headers.get("content-type") || "application/octet-stream";
    const contentLength = upstream.headers.get("content-length");
    const disposition = upstream.headers.get("content-disposition");

    if (!upstream.body) {
      return json(502, { error: "Earthdata response has no body" }, headers);
    }

    const { readable, writable } = new TransformStream();
    EdgeRuntime.waitUntil(upstream.body.pipeTo(writable));

    return new Response(readable, {
      status: 200,
      headers: {
        ...headers,
        "Content-Type": contentType,
        ...(contentLength ? { "Content-Length": contentLength } : {}),
        ...(disposition ? { "Content-Disposition": disposition } : {}),
        "X-Final-URL": current.toString(),
        "X-Upstream-Status": String(upstream.status),
      },
    });
  } catch (error) {
    return json(502, {
      error: "Earthdata proxy request failed",
      detail: error instanceof Error ? error.message : String(error),
      final_url: current.toString(),
    }, headers);
  }
});
