const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
function worker(){const c=vm.createContext({self:{},TextDecoder,TextEncoder,console});vm.runInContext(fs.readFileSync(path.join(root,'granule-worker.js'),'utf8'),c);return c;}
function app(){
 const nodes=new Map(),element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',classList:{add(){},remove(){},toggle(){}},appendChild(){}});return nodes.get(id)};
 const c=vm.createContext({document:{getElementById:element,createElement:()=>({})},sessionStorage:{getItem(){return ''}},console,URL,URLSearchParams,AbortSignal,TextDecoder,TextEncoder,setTimeout,clearTimeout,performance,fetch:async()=>{throw new Error('unexpected network')}});
 vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8').split('E.verifyTokenBtn.onclick=verify;')[0],c);return c;
}
test('HDF5 prototype attributes apply scaling and fill values',()=>{
 const c=worker();const meta={attrs:{scale_factor:{get value(){return .0001}},_FillValue:{get value(){return -3000}}}};
 assert.equal(c.h5Packed(5000,meta),.5);assert.equal(c.h5Packed(-3000,meta),null);
 // Reproduce h5wasm Attribute.value on a prototype, not the instance itself.
 const attr=Object.create({get value(){return .0001}});
 assert.equal(c.h5Packed(5000,{attrs:{scale_factor:attr}}),.5);
});
function bins(c, weights=2, bin=32401){
 return [{path:'level-3_binned_data/BinList',obj:{shape:[1],value:[[bin,1,1,weights]],metadata:{compound_type:{members:['bin_num','nobs','nscenes','weights'].map(name=>({name}))}}}},
 {path:'level-3_binned_data/BinIndex',obj:{shape:[180]}},
 {path:'level-3_binned_data/ndvi',obj:{value:[[1,1]],metadata:{compound_type:{members:[{name:'sum'},{name:'sum_squared'}]}}}}];
}
test('Level-3 bin centers match equatorial bin formula; means use weights',()=>{
 const c=worker(),index=c.l3BinCenters(180),bin=index.base[91]+270,sets=bins(c,2,bin),g={};
 const result=c.h5L3Binned(sets,g,'NDVI',['ndvi'],{type:'bbox',values:[90,0,91,1]});
 assert.equal(result.rows.length,1);assert.equal(result.rows[0].latitude,.5);assert.equal(result.rows[0].longitude,90.5);assert.equal(result.rows[0].value,.5);
 assert.match(g.coordinateBackend,/integerized/);
});
test('No in-area bins is a successful empty result, not a coordinate error',()=>{
 const c=worker(),sets=bins(c,2,c.l3BinCenters(180).base[91]);
 assert.equal(c.h5L3Binned(sets,{},'ndvi',['ndvi'],{type:'bbox',values:[89,22,92,25]}).rows.length,0);
});
test('Zero weights are skipped; malformed records and absent science are errors',()=>{
 const c=worker(),sets=bins(c,0,c.l3BinCenters(180).base[91]);
 assert.equal(c.h5L3Binned(sets,{},'ndvi',['ndvi'],null).rows.length,0);
 assert.throws(()=>c.h5L3Binned(sets,{},'PM2.5',['pm25'],null),/no science/);
 sets[2].obj.value=[];assert.throws(()=>c.h5L3Binned(sets,{},'ndvi',['ndvi'],null),/counts/);
});
test('Compound field positions come from metadata, not a hardcoded offset',()=>{
 const c=worker(),sets=bins(c),bin=c.l3BinCenters(180).base[91];
 sets[0].obj.value=[[2,bin,1,1]];sets[0].obj.metadata.compound_type.members=['weights','bin_num','nobs','nscenes'].map(name=>({name}));
 assert.equal(c.h5L3Binned(sets,{},'ndvi',['ndvi'],null).rows[0].value,.5);
});
test('ORNL wrapped products and bands are accepted and unknown products stay exact',async()=>{
 const c=app();c.payload={products:[{product:'MOD13Q1',description:'NDVI SIN Grid'}]};vm.runInContext("tesvisJson=async()=>payload;S.search={component:'ndvi'}",c);
 assert.equal((await c.loadTesvisProducts()).has('MOD13Q1'),true);
 c.payload={bands:[{band:'250m_16_days_NDVI',scale_factor:'.0001'}]};assert.equal((await c.tesvisBand('MOD13Q1')).band,'250m_16_days_NDVI');
 const product={shortName:'MOD13A2',preview:{url:'https://example.test/data.hdf'}};
 assert.equal(c.setCsvProfile(product,new Map()).csvProfile.ready,false);
 vm.runInContext('NATIVE_CONVERTER_READY=true',c);assert.equal(c.setCsvProfile(product,new Map()).csvProfile.route,'native-hdf4');
});
test('Failed ORNL discovery can be retried',async()=>{
 const c=app();vm.runInContext("tesvisJson=async()=>{throw new Error('offline')}",c);assert.equal((await c.loadTesvisProducts()).size,0);
 vm.runInContext("tesvisJson=async()=>({products:[{product:'MOD13Q1'}]})",c);assert.equal((await c.loadTesvisProducts()).size,1);
});
test('Partial ORNL tile failure cannot become a complete cached request',async()=>{
 const c=app();vm.runInContext("S.search={component:'ndvi',geometry:{type:'bbox',values:[90,23,90.1,23.1]}};tesvisBand=async()=>({band:'NDVI'});tesvisJson=async()=>{throw new Error('HTTP 503')}",c);
 await assert.rejects(c.fetchTesvisCollection({shortName:'MOD13Q1'},[{start:'2025-01-01'}]),/subset incomplete/);
});
test('Coordinates accept whitespace; point clipping retains multiple dates',()=>{
 const c=app();assert.deepEqual(Array.from(c.nums('23.5 90.1')),[23.5,90.1]);
 const rows=['2025-01-01','2025-01-02'].map(date=>({latitude:23,longitude:90,variable:'ndvi',date}));
 assert.equal(c.clipRows(rows,{type:'point',values:[90,23]}).length,2);
});
test('CMR page failure rejects instead of caching a truncated catalog',async()=>{
 const c=app();vm.runInContext("cmr=async(path,p)=>{if(p.get('page_num')==='1')return{items:Array(2000).fill({}),hits:2001};throw new Error('page offline')};ingestGranuleItems=()=>{}",c);
 await assert.rejects(c.granules({id:'C1'},{start:'2025-01-01',end:'2025-01-02',geometry:{key:'bounding_box',value:'90,23,91,24'}},false,false),/CMR page failed/);
});
test('Asset versions match validation and browser entrypoint',()=>{
 const source=fs.readFileSync(path.join(root,'app.js'),'utf8'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
 assert.equal(source.match(/granule-worker.js\?v=(\d+-\d+)/)[1],html.match(/app.js\?v=(\d+-\d+)/)[1]);
});
test('Authentication failure blocks the rest of its collection, not other collections',async()=>{
 const c=app();c.navigator={hardwareConcurrency:4,deviceMemory:4};
 vm.runInContext(`S.granules=Array.from({length:20},(_,i)=>({title:'g'+i,collectionId:'C1'})).concat([{title:'other',collectionId:'C2'}]);S.search={component:'ndvi',geometry:{type:'bbox',values:[90,23,91,24]}};
 hydrateGranuleCache=async items=>({hits:0,misses:items});saveGranuleCache=()=>{};
 var attempted=[];convertDirectGranule=async g=>{attempted.push(g.title);if(g.collectionId==='C1')throw new Error('NASA download HTTP 401');return{rows:[],sourceRows:0}};`,c);
 await c.convertAll();const counts=vm.runInContext('({calls:attempted.length,blocked:S.granules.filter(g=>g.conversionStatus===\"auth_blocked\").length,other:S.granules.at(-1).conversionStatus})',c);
 assert.ok(counts.calls<=6);assert.equal(counts.blocked,20);assert.equal(counts.other,'ok');
});


test('Structural conversion failure blocks the collection after one preflight granule',async()=>{
 const c=app();c.navigator={hardwareConcurrency:4,deviceMemory:4};
 vm.runInContext(`S.granules=Array.from({length:30},(_,i)=>({title:'bad'+i,collectionId:'C1',collectionShortName:'STRUCT'})).concat([{title:'good',collectionId:'C2',collectionShortName:'GOOD'}]);S.search={component:'ndvi',geometry:{type:'bbox',values:[90,23,91,24]}};
 hydrateGranuleCache=async items=>({hits:0,local:0,shared:0,rows:0,misses:items});saveGranuleCache=()=>{};
 var attempted=[];convertDirectGranule=async g=>{attempted.push(g.title);if(g.collectionId==='C1')throw new Error('HDF5 conversion found the requested science data but could not derive in-area coordinates from explicit geolocation arrays or HDF-EOS/grid bounds metadata.');return{rows:[],sourceRows:0}};`,c);
 await c.convertAll();
 const counts=vm.runInContext('({calls:attempted.length,skipped:S.granules.filter(g=>g.collectionId===\"C1\"&&g.conversionStatus===\"skipped_unsupported\").length,good:S.granules.at(-1).conversionStatus})',c);
 assert.ok(counts.calls<=3);assert.equal(counts.skipped,30);assert.equal(counts.good,'ok');
});

test('Large direct collections are guarded after official subset routes are exhausted',()=>{
 const c=app(),items=Array.from({length:241},()=>({sizeBytes:1}));
 assert.equal(c.directCollectionTooLarge(items),true);
 assert.equal(c.directCollectionTooLarge(items.slice(0,240)),false);
});

test('Structural error classifier is distinct from transient and auth failures',()=>{
 const c=app();
 assert.equal(c.classifyConversionError(new Error('could not derive in-area coordinates from HDF-EOS/grid bounds metadata')),'structural');
 assert.equal(c.classifyConversionError(new Error('NASA download HTTP 401')),'auth');
 assert.equal(c.classifyConversionError(new Error('network timeout')),'transient');
});
