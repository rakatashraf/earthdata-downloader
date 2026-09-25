import { createClient } from "npm:@supabase/supabase-js@2";

const BUCKET = "earthdata-staging";
const PART_BYTES = 5 * 1024 * 1024;
const allowedOrigins = new Set(["https://rakatashraf.github.io"]);

function cors(origin:string|null){
  const local=!!origin&&/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  const allow=origin&&(allowedOrigins.has(origin)||local)?origin:"";
  return {
    ...(allow?{"Access-Control-Allow-Origin":allow}:{}),
    "Access-Control-Allow-Methods":"GET,POST,OPTIONS",
    "Access-Control-Allow-Headers":"Content-Type,X-Earthdata-Token",
    "Access-Control-Max-Age":"86400",
    "Cache-Control":"no-store",
    "Vary":"Origin",
  };
}
function json(status:number,body:unknown,headers:Record<string,string>){
  return new Response(JSON.stringify(body),{status,headers:{...headers,"Content-Type":"application/json; charset=utf-8"}});
}
function safe(s:string){return s.replace(/[^A-Za-z0-9._-]+/g,"_").slice(0,180)||"granule";}
function sourceFormatFromMagic(head:Uint8Array,filename:string,contentType:string){
  if(head.length>=4&&head[0]===0x0e&&head[1]===0x03&&head[2]===0x13&&head[3]===0x01)return "hdf4";
  if(head.length>=8&&head[0]===0x89&&head[1]===0x48&&head[2]===0x44&&head[3]===0x46&&head[4]===0x0d&&head[5]===0x0a&&head[6]===0x1a&&head[7]===0x0a)return "hdf5";
  if(head.length>=4&&head[0]===0x43&&head[1]===0x44&&head[2]===0x46&&(head[3]===0x01||head[3]===0x02||head[3]===0x05))return "netcdf";
  if(head.length>=4&&((head[0]===0x49&&head[1]===0x49&&head[2]===0x2a&&head[3]===0x00)||(head[0]===0x4d&&head[1]===0x4d&&head[2]===0x00&&head[3]===0x2a)||(head[0]===0x49&&head[1]===0x49&&head[2]===0x2b&&head[3]===0x00)||(head[0]===0x4d&&head[1]===0x4d&&head[2]===0x00&&head[3]===0x2b)))return "geotiff";
  if(head.length>=2&&head[0]===0x1f&&head[1]===0x8b)return "gzip";
  if(head.length>=4&&head[0]===0x50&&head[1]===0x4b&&(head[2]===0x03||head[2]===0x05||head[2]===0x07))return "zip";
  const n=filename.toLowerCase(),ct=contentType.toLowerCase();
  if(n.endsWith(".tif")||n.endsWith(".tiff")||ct.includes("tiff"))return "geotiff";
  if(n.endsWith(".csv")||ct.includes("text/csv"))return "csv";
  if(n.endsWith(".json")||n.endsWith(".geojson")||ct.includes("json"))return "json";
  if(n.endsWith(".nc")||n.endsWith(".cdf")||ct.includes("netcdf"))return "netcdf";
  if(n.endsWith(".gz")||ct.includes("gzip"))return "gzip";
  if(n.endsWith(".zip")||ct.includes("zip"))return "zip";
  if(n.endsWith(".hdf")||n.endsWith(".h4"))return "hdf4";
  if(n.endsWith(".h5")||n.endsWith(".hdf5")||n.endsWith(".he5")||n.endsWith(".nc4"))return "hdf5";
  return "unknown";
}
function secretKey(){
  const modern=Deno.env.get("SUPABASE_SECRET_KEYS");
  if(modern){try{return JSON.parse(modern).default||Object.values(JSON.parse(modern))[0] as string}catch{}}
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
}
async function ensureBucket(supabase:any){
  const {data}=await supabase.storage.getBucket(BUCKET);
  if(data)return;
  const {error}=await supabase.storage.createBucket(BUCKET,{public:false,fileSizeLimit:50*1024*1024});
  if(error&&!/already exists/i.test(error.message||""))throw error;
}
async function signParts(supabase:any,paths:string[]){
  const out=[];
  for(const path of paths){
    const {data,error}=await supabase.storage.from(BUCKET).createSignedUrl(path,3600);
    if(error)throw error;
    out.push({path,url:data.signedUrl});
  }
  return out;
}
async function removePaths(supabase:any,paths:string[]){
  for(let i=0;i<paths.length;i+=100){
    const batch=paths.slice(i,i+100);
    const {error}=await supabase.storage.from(BUCKET).remove(batch);
    if(error)throw error;
  }
}

Deno.serve(async(req)=>{
  const origin=req.headers.get("origin"),headers=cors(origin);
  if(req.method==="OPTIONS")return new Response(null,{status:204,headers});
  const local=!!origin&&/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  if(origin&&!allowedOrigins.has(origin)&&!local)return json(403,{error:"Origin not allowed"},headers);

  const key=secretKey();
  if(!key)return json(500,{error:"Supabase server secret is unavailable"},headers);
  const supabase=createClient(Deno.env.get("SUPABASE_URL")!,key,{auth:{persistSession:false}});
  try{await ensureBucket(supabase)}catch(e){return json(500,{error:"Could not initialize staging bucket",detail:e instanceof Error?e.message:String(e)},headers)}

  if(req.method==="GET"){
    const url=new URL(req.url);
    if(url.searchParams.get("health")==="1")return json(200,{ok:true,service:"earthdata-staging",bucket:BUCKET,part_bytes:PART_BYTES},headers);
    return json(405,{error:"GET is only available for health checks"},headers);
  }
  if(req.method!=="POST")return json(405,{error:"Method not allowed"},headers);

  let body:any;
  try{body=await req.json()}catch{return json(400,{error:"Invalid JSON body"},headers)}
  const action=String(body.action||"stage");

  if(action==="cleanup"){
    const paths=Array.isArray(body.paths)?body.paths.filter((x:any)=>typeof x==="string"&&x.startsWith(String(body.extraction_id||"")+"/")):[];
    if(paths.length){try{await removePaths(supabase,paths)}catch(e){return json(500,{error:"Cleanup failed",detail:e instanceof Error?e.message:String(e)},headers)}}
    return json(200,{ok:true,removed:paths.length},headers);
  }

  if(action==="resign"){
    const paths=Array.isArray(body.paths)?body.paths.filter((x:any)=>typeof x==="string"):[];
    try{return json(200,{ok:true,parts:await signParts(supabase,paths)},headers)}catch(e){return json(500,{error:"Could not sign staged parts",detail:e instanceof Error?e.message:String(e)},headers)}
  }

  if(action!=="stage")return json(400,{error:"Unknown action"},headers);

  const target=String(body.url||""),token=String(req.headers.get("x-earthdata-token")||"").trim(),extractionId=safe(String(body.extraction_id||"session")),filename=safe(String(body.filename||"granule.bin"));
  if(!target||!token)return json(400,{error:"NASA source URL and Earthdata token are required"},headers);

  const nasaProxy=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"")+"/functions/v1/nasa-proxy?url="+encodeURIComponent(target);
  let upstream:Response;
  try{upstream=await fetch(nasaProxy,{headers:{"X-Earthdata-Token":token}})}catch(e){return json(502,{error:"NASA staging download failed",detail:e instanceof Error?e.message:String(e)},headers)}
  if(!upstream.ok){
    const text=await upstream.text().catch(()=>"");
    return json(upstream.status,{error:"NASA staging download failed",detail:text.slice(0,1000)},headers);
  }
  if(!upstream.body)return json(502,{error:"NASA returned no file body"},headers);

  const contentType=upstream.headers.get("content-type")||"application/octet-stream",reader=upstream.body.getReader(),paths:string[]=[];
  let pending=new Uint8Array(0),head=new Uint8Array(0),part=0,total=0,uploads:Promise<void>[]=[];
  const queuePart=(bytes:Uint8Array)=>{
    const index=part++,path=extractionId+"/"+filename+"/part-"+String(index).padStart(5,"0")+".bin";
    paths.push(path);total+=bytes.byteLength;
    uploads.push((async()=>{const {error}=await supabase.storage.from(BUCKET).upload(path,bytes,{contentType:"application/octet-stream",upsert:true,cacheControl:"0"});if(error)throw error})());
  };
  const flushUploads=async()=>{if(uploads.length){const batch=uploads;uploads=[];await Promise.all(batch)}};

  try{
    while(true){
      const {done,value}=await reader.read();
      if(done)break;
      if(head.byteLength<8){const take=Math.min(8-head.byteLength,value.byteLength),nextHead=new Uint8Array(head.byteLength+take);nextHead.set(head);nextHead.set(value.slice(0,take),head.byteLength);head=nextHead}
      const next=new Uint8Array(pending.byteLength+value.byteLength);
      next.set(pending);next.set(value,pending.byteLength);pending=next;
      while(pending.byteLength>=PART_BYTES){
        queuePart(pending.slice(0,PART_BYTES));
        pending=pending.slice(PART_BYTES);
        if(uploads.length>=4)await flushUploads();
      }
    }
    if(pending.byteLength)queuePart(pending);
    await flushUploads();
    const metaPath=extractionId+"/"+filename+"/manifest.json";
    const sourceFormat=sourceFormatFromMagic(head,filename,contentType);
    const meta={original_url:target,filename,content_type:contentType,source_format:sourceFormat,total_bytes:total,parts:paths,created_at:new Date().toISOString()};
    const {error:me}=await supabase.storage.from(BUCKET).upload(metaPath,new Blob([JSON.stringify(meta)],{type:"application/json"}),{contentType:"application/json",upsert:true,cacheControl:"0"});
    if(me)throw me;
    const signed=await signParts(supabase,paths);
    return json(200,{ok:true,filename,content_type:contentType,source_format:sourceFormat,total_bytes:total,paths,parts:signed,manifest_path:metaPath},headers);
  }catch(e){
    try{if(paths.length)await removePaths(supabase,paths)}catch{}
    return json(500,{error:"Staging failed",detail:e instanceof Error?e.message:String(e),staged_parts:paths.length},headers);
  }
});
