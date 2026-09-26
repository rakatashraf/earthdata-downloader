import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import h5 from 'h5wasm/node';
await h5.ready;
globalThis.self={};
const wasmUrl=import.meta.resolve('h5wasm/node');
const source=fs.readFileSync(new URL('../granule-worker.js',import.meta.url),'utf8')
 .replace('https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/esm/hdf5_hl.js',wasmUrl);
const parsers=await import('data:text/javascript;base64,'+Buffer.from(source+'\nexport {parseHdf5,l3BinCenters};').toString('base64'));
function fixture(build){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'earthdata-test-'));
 const file=path.join(dir,'science.h5');
 const f=new h5.File(file,'w');
 try{build(f)}finally{f.close()}
 const data=fs.readFileSync(file);fs.rmSync(dir,{recursive:true});
 return data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength);
}
test('real HDF5 compound records convert with correct mean and geolocation',async()=>{
 const bin=parsers.l3BinCenters(180).base[91]+270;
 const data=fixture(f=>{
  const group=f.create_group('level-3_binned_data');
  group.create_dataset({name:'BinList',data:new Map([['bin_num',new Uint32Array([bin])],['nobs',new Uint16Array([1])],['nscenes',new Uint16Array([1])],['weights',new Float32Array([2])]])});
  group.create_dataset({name:'BinIndex',data:new Uint32Array(180)});
  group.create_dataset({name:'ndvi',data:new Map([['sum',new Float32Array([1])],['sum_squared',new Float32Array([1])]])});
 });
 const result=await parsers.parseHdf5(data,{},'ndvi',['ndvi'],{type:'bbox',values:[90,0,91,1]});
 assert.equal(result.rows.length,1);assert.equal(result.rows[0].value,.5);assert.equal(result.rows[0].latitude,.5);assert.equal(result.rows[0].longitude,90.5);
 const empty=await parsers.parseHdf5(data,{},'ndvi',['ndvi'],{type:'bbox',values:[89,22,92,25]});assert.equal(empty.rows.length,0);
});
test('real HDF5 Attribute getters preserve packing and empty intersections',async()=>{
 const data=fixture(f=>{
  f.create_dataset({name:'latitude',data:new Float32Array([23,24])});
  f.create_dataset({name:'longitude',data:new Float32Array([90,91])});
  f.create_dataset({name:'ndvi',data:new Int16Array([5000,-3000,2000,10000]),shape:[2,2]});
  f.get('ndvi').create_attribute('scale_factor',.0001);
  f.get('ndvi').create_attribute('_FillValue',-3000);
 });
 const result=await parsers.parseHdf5(data,{},'ndvi',['ndvi'],{type:'bbox',values:[90,23,91,24]});
 assert.deepEqual(result.rows.map(r=>r.value),[.5,.2,1]);
 const empty=await parsers.parseHdf5(data,{},'ndvi',['ndvi'],{type:'bbox',values:[80,10,81,11]});assert.equal(empty.rows.length,0);
});
