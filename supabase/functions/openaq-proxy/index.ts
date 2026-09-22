const OPENAQ = "https://api.openaq.org/v3";

const allowedOrigins = new Set([
  "https://rakatashraf.github.io",
]);

function cors(origin: string | null) {
  const local = !!origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  const allow = origin && (allowedOrigins.has(origin) || local) ? origin : "";
  return {
    ...(allow ? { "Access-Control-Allow-Origin": allow } : {}),
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-OpenAQ-Key",
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

function permitted(path: string) {
  return (
    path === "/parameters" ||
    path === "/locations" ||
    /^\/locations\/\d+\/(sensors|latest)$/.test(path) ||
    /^\/sensors\/\d+\/(measurements|hours|days|years)$/.test(path)
  );
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

  const url = new URL(req.url);
  const marker = "/openaq-proxy/api/openaq";
  const index = url.pathname.indexOf(marker);
  if (index < 0) {
    return json(404, { error: "Route not found" }, headers);
  }

  const openaqPath = url.pathname.slice(index + marker.length) || "/";
  if (!permitted(openaqPath)) {
    return json(404, { error: "OpenAQ route not permitted" }, headers);
  }

  const key = (req.headers.get("x-openaq-key") || "").trim();
  if (!key) {
    return json(401, { error: "OpenAQ API key is required" }, headers);
  }

  const upstream = new URL(OPENAQ + openaqPath);
  url.searchParams.forEach((value, name) => upstream.searchParams.append(name, value));

  try {
    const response = await fetch(upstream, {
      headers: {
        "X-API-Key": key,
        "Accept": "application/json",
      },
    });

    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        ...headers,
        "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8",
        "X-Upstream-Status": String(response.status),
      },
    });
  } catch (error) {
    return json(502, {
      error: "OpenAQ upstream request failed",
      detail: error instanceof Error ? error.message : String(error),
    }, headers);
  }
});
