const allowedOrigins = new Set([
  "https://rakatashraf.github.io",
]);

const allowedHosts = new Set([
  "air-quality-api.open-meteo.com",
  "archive-api.open-meteo.com",
  "api.open-meteo.com",
  "api.worldpop.org",
  "power.larc.nasa.gov",
]);

function cors(origin: string | null) {
  const local = !!origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  const allow = origin && (allowedOrigins.has(origin) || local) ? origin : "";
  return {
    ...(allow ? { "Access-Control-Allow-Origin": allow } : {}),
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Expose-Headers": "Content-Type, X-Upstream-Status",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
}

function json(status:number, body:unknown, headers:Record<string,string>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
  });
}

Deno.serve(async req => {
  const origin=req.headers.get("origin");
  const headers=cors(origin);

  if(req.method==="OPTIONS") return new Response(null,{status:204,headers});

  const local=!!origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if(origin && !allowedOrigins.has(origin) && !local) return json(403,{error:"Origin not allowed"},headers);

  const requestUrl=new URL(req.url);
  if(requestUrl.searchParams.get("health")==="1") return json(200,{ok:true,service:"alternative-proxy"},headers);

  const targetRaw=requestUrl.searchParams.get("url");
  if(!targetRaw) return json(400,{error:"Missing target URL"},headers);

  let target:URL;
  try{target=new URL(targetRaw)}catch{return json(400,{error:"Invalid target URL"},headers)}
  if(target.protocol!=="https:" || !allowedHosts.has(target.hostname.toLowerCase())) {
    return json(403,{error:"External provider host is not allow-listed",host:target.hostname},headers);
  }

  if(!["GET","POST"].includes(req.method)) return json(405,{error:"Method not allowed"},headers);

  let body:BodyInit|undefined;
  if(req.method==="POST"){
    const raw=await req.text();
    if(raw.length>100000) return json(413,{error:"Request body too large"},headers);
    body=raw;
  }

  try{
    const upstream=await fetch(target.toString(),{
      method:req.method,
      headers:{
        "Accept":"application/json",
        ...(req.method==="POST"?{"Content-Type":req.headers.get("content-type")||"application/json"}:{})
      },
      body,
      redirect:"follow",
    });
    const text=await upstream.text();
    return new Response(text,{
      status:upstream.status,
      headers:{
        ...headers,
        "Content-Type":upstream.headers.get("content-type")||"application/json; charset=utf-8",
        "X-Upstream-Status":String(upstream.status),
      }
    });
  }catch(error){
    return json(502,{error:"External provider request failed",detail:error instanceof Error?error.message:String(error)},headers);
  }
});
