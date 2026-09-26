import { createClient } from "npm:@supabase/supabase-js@2";

const BUCKET="earthdata-converted-cache";
const MAX_WRITE=6*1024*1024;
const origins=new Set(["https://rakatashraf.github.io"]);

function cors(origin:string|null){
  const local=!!origin&&/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  const allow=origin&&(origins.has(origin)||local)?origin:"";
  return {
    ...(allow?{"Access-Control-Allow-Origin":allow}:{}),
    "Access-Control-Allow-Methods":"GET,POST,OPTIONS",
    "Access-Control-Allow-Headers":"Content-Type,X-Cache-Key,X-Cache-Rows,X-Cache-Component,X-Cache-Collection,X-Cache-Granule",
    "Access-Control-Max-Age":"86400",
    "Cache-Control":"no-store",
    "Vary":"Origin"
  };
}
function json(status:number,body:unknown,h:Record<string,string>){
  return new Response(JSON.stringify(body),{status,headers:{...h,"Content-Type":"application/json; charset=utf-8"}});
}
function serverKey(){
  const modern=Deno.env.get("SUPABASE_SECRET_KEYS");
  if(modern){try{const parsed=JSON.parse(modern);return parsed.default||Object.values(parsed)[0] as string}catch{}}
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
}
function validKey(k:string){return /^[a-f0-9]{64}\.json\.gz$/.test(k)}

Deno.serve(async req=>{
  const origin=req.headers.get("origin"),h=cors(origin);
  if(req.method==="OPTIONS")return new Response(null,{status:204,headers:h});
  const local=!!origin&&/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if(origin&&!origins.has(origin)&&!local)return json(403,{error:"Origin not allowed"},h);
  const key=serverKey();
  if(!key)return json(500,{error:"Server key unavailable"},h);
  const supabase=createClient(Deno.env.get("SUPABASE_URL")!,key,{auth:{persistSession:false}});
  const url=new URL(req.url);
  if(req.method==="GET"&&url.searchParams.get("health")==="1")return json(200,{ok:true,service:"converted-cache",bucket:BUCKET,max_write_bytes:MAX_WRITE},h);

  if(req.method==="POST"&&url.searchParams.get("action")==="lookup"){
    let body:any;try{body=await req.json()}catch{return json(400,{error:"Invalid JSON"},h)}
    const keys=Array.isArray(body.keys)?body.keys.filter((x:any)=>typeof x==="string"&&validKey(x)).slice(0,500):[];
    if(!keys.length)return json(200,{ok:true,items:[]},h);
    const {data:indexRows,error:indexError}=await supabase
      .from("converted_cache_index")
      .select("cache_key,byte_size,row_count")
      .in("cache_key",keys);
    if(indexError)return json(500,{error:indexError.message},h);
    const hits:any[]=[];
    for(const row of indexRows||[]){
      const {data,error}=await supabase.storage.from(BUCKET).createSignedUrl(row.cache_key,900);
      if(!error&&data?.signedUrl)hits.push({key:row.cache_key,url:data.signedUrl,bytes:row.byte_size,rows:row.row_count});
    }
    if(hits.length){
      supabase.from("converted_cache_index")
        .update({last_accessed_at:new Date().toISOString()})
        .in("cache_key",hits.map(x=>x.key))
        .then(()=>{}).catch(()=>{});
    }
    return json(200,{ok:true,items:hits},h);
  }

  if(req.method==="POST"&&url.searchParams.get("action")==="put"){
    const objectKey=String(req.headers.get("x-cache-key")||"");
    if(!validKey(objectKey))return json(400,{error:"Invalid cache key"},h);
    const len=Number(req.headers.get("content-length")||0);
    if(len>MAX_WRITE)return json(413,{error:"Cache object exceeds shared-cache limit"},h);
    const bytes=new Uint8Array(await req.arrayBuffer());
    if(!bytes.byteLength||bytes.byteLength>MAX_WRITE)return json(413,{error:"Cache object exceeds shared-cache limit"},h);
    const {error}=await supabase.storage.from(BUCKET).upload(objectKey,bytes,{contentType:"application/gzip",cacheControl:"31536000",upsert:true});
    if(error)return json(500,{error:error.message},h);
    const rowCount=Math.max(0,Number(req.headers.get("x-cache-rows")||0)||0);
    const component=String(req.headers.get("x-cache-component")||"").slice(0,160);
    const collectionId=String(req.headers.get("x-cache-collection")||"").slice(0,200);
    const granuleId=String(req.headers.get("x-cache-granule")||"").slice(0,300);
    const {error:indexError}=await supabase.from("converted_cache_index").upsert({
      cache_key:objectKey,
      byte_size:bytes.byteLength,
      row_count:rowCount,
      component,
      collection_id:collectionId,
      granule_id:granuleId,
      last_accessed_at:new Date().toISOString()
    });
    if(indexError)return json(500,{error:indexError.message},h);
    return json(200,{ok:true,key:objectKey,bytes:bytes.byteLength,rows:rowCount},h);
  }

  return json(405,{error:"Unsupported cache operation"},h);
});
