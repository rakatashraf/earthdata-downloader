const allowedOrigins = new Set([
  "https://rakatashraf.github.io",
]);

const providerSuffixes = [
  "nasa.gov",
  "earthdata.nasa.gov",
  "nsidc.org",
  "usgs.gov",
  "ornl.gov",
  "alaska.edu",
];

const providerExactHosts = new Set([
  "sedac.ciesin.columbia.edu",
]);

const knownNasaCloudFrontHosts = new Set([
  "d2b3c3wh8s6en5.cloudfront.net",
]);

const redirectStatuses = new Set([301, 302, 303, 307, 308]);

function isProviderHost(url: URL) {
  const h = url.hostname.toLowerCase();
  return providerExactHosts.has(h) ||
    providerSuffixes.some((suffix) => h === suffix || h.endsWith("." + suffix));
}

function isSignedCloudFront(url: URL) {
  const h = url.hostname.toLowerCase();
  if (!h.endsWith(".cloudfront.net")) return false;
  if (knownNasaCloudFrontHosts.has(h)) return true;
  const q = url.searchParams;
  return (
    (q.has("Signature") && (q.has("Key-Pair-Id") || q.has("Policy"))) ||
    q.has("X-Amz-Signature")
  );
}

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

function isSignedS3(url: URL) {
  const h = url.hostname.toLowerCase();
  const looksLikeS3 =
    h === "s3.amazonaws.com" ||
    /^s3[.-][a-z0-9-]+\.amazonaws\.com$/.test(h) ||
    /\.s3[.-][a-z0-9-]+\.amazonaws\.com$/.test(h) ||
    /\.s3\.amazonaws\.com$/.test(h);
  if (!looksLikeS3) return false;
  const q = url.searchParams;
  return isGesdiscS3(url) ||
    q.has("X-Amz-Signature") ||
    q.has("X-Amz-Credential") ||
    q.has("AWSAccessKeyId");
}

function isStorageRedirect(url: URL) {
  return isGesdiscS3(url) || isSignedS3(url) || isSignedCloudFront(url);
}

function redirectAllowed(url: URL) {
  return url.protocol === "https:" && (isProviderHost(url) || isStorageRedirect(url));
}

function cors(origin: string | null) {
  const local = !!origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  const allow = origin && (allowedOrigins.has(origin) || local) ? origin : "";
  return {
    ...(allow ? { "Access-Control-Allow-Origin": allow } : {}),
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Earthdata-Token",
    "Access-Control-Expose-Headers":
      "Content-Type, Content-Length, Content-Disposition, X-Final-URL, X-Upstream-Status",
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

function looksLikeLoginPage(url: URL, contentType: string) {
  const h = url.hostname.toLowerCase();
  return contentType.toLowerCase().includes("text/html") &&
    (h === "urs.earthdata.nasa.gov" || h.endsWith(".earthdata.nasa.gov"));
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
  if (requestUrl.searchParams.get("health") === "1") {
    return json(200, { ok: true, service: "nasa-proxy", version: 4 }, headers);
  }
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

  // The caller may only start at a known NASA/DAAC provider host.
  // CloudFront/S3 are accepted only after a trusted provider redirect.
  if (current.protocol !== "https:" || !isProviderHost(current)) {
    return json(403, {
      error: "Initial target is not an approved Earthdata/DAAC host",
      host: current.hostname,
    }, headers);
  }

  const cookies = new Map<string, string>();
  let upstream: Response | null = null;
  const chain: string[] = [];

  try {
    for (let hop = 0; hop < 12; hop++) {
      chain.push(current.hostname);

      if (!redirectAllowed(current)) {
        return json(403, {
          error: "Redirected to an unapproved host: " + current.hostname,
          host: current.hostname,
          url: current.toString(),
          redirect_chain: chain,
        }, headers);
      }

      const storageHop = isStorageRedirect(current);
      const cookieHeader = [...cookies.values()].filter(Boolean).join("; ");

      upstream = await fetch(current.toString(), {
        method: "GET",
        redirect: "manual",
        headers: {
          "Accept": "*/*",
          "User-Agent": "earthdata-downloader/1.0",
          ...(!storageHop ? { "Authorization": "Bearer " + token } : {}),
          ...(!storageHop && cookieHeader ? { "Cookie": cookieHeader } : {}),
        },
      });

      const getSetCookie = (upstream.headers as any).getSetCookie;
      const setCookies: string[] = typeof getSetCookie === "function"
        ? getSetCookie.call(upstream.headers)
        : (upstream.headers.get("set-cookie")
          ? [upstream.headers.get("set-cookie") as string]
          : []);

      // Only retain cookies from trusted application/auth hosts.
      if (!storageHop) {
        for (const raw of setCookies) {
          const pair = cookiePair(raw);
          const eq = pair.indexOf("=");
          if (eq > 0) cookies.set(pair.slice(0, eq), pair);
        }
      }

      if (!redirectStatuses.has(upstream.status)) break;

      const location = upstream.headers.get("location");
      if (!location) {
        return json(502, {
          error: "Earthdata returned a redirect without a Location header",
          status: upstream.status,
          redirect_chain: chain,
        }, headers);
      }

      current = new URL(location, current);
    }

    if (!upstream) {
      return json(502, { error: "No response from Earthdata host" }, headers);
    }

    if (redirectStatuses.has(upstream.status)) {
      return json(508, {
        error: "Too many Earthdata redirects",
        final_url: current.toString(),
        redirect_chain: chain,
      }, headers);
    }

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return json(upstream.status, {
        error: "NASA/DAAC download failed",
        status: upstream.status,
        final_url: current.toString(),
        redirect_chain: chain,
        detail: text.slice(0, 1500),
      }, {
        ...headers,
        "X-Final-URL": current.toString(),
        "X-Upstream-Status": String(upstream.status),
      });
    }

    const contentType = upstream.headers.get("content-type") || "application/octet-stream";
    if (looksLikeLoginPage(current, contentType)) {
      return json(401, {
        error: "Earthdata returned a login page instead of the data file",
        detail:
          "The token may be expired, or the required DAAC application may not be authorized in Earthdata Login.",
        final_url: current.toString(),
        redirect_chain: chain,
      }, headers);
    }

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
      redirect_chain: chain,
    }, headers);
  }
});
