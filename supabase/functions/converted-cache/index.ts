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
    "Access-Control-Allow-Headers":"Content-Type,X-Cache-Key",
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
    const hits:any[]=[];
    for(let i=0;i<keys.length;i+=50){
      const batch=keys.slice(i,i+50);
      const group=await Promise.all(batch.map(async k=>{
        const {data,error}=await supabase.storage.from(BUCKET).createSignedUrl(k,900);
        return error?null:{key:k,url:data.signedUrl};
      }));
      hits.push(...group.filter(Boolean));
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
    return json(200,{ok:true,key:objectKey,bytes:bytes.byteLength},h);
  }

  return json(405,{error:"Unsupported cache operation"},h);
});
