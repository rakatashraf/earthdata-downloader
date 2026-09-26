from pathlib import Path
import pandas as pd

src=Path('lc_output/Dhaka_23_81030_90_41250/components_daily_long.csv')
out=Path('lc_output/LUPUS_CORTEX_2025_DYNAMIC_MASTER.csv')
manifest=pd.read_csv('tools/lc_collection_manifest.csv')
cycle={
'PM2_5':'hourly','PM10':'hourly','NO2':'daily','O3':'daily','SO2':'daily','CO':'daily','AEROSOL_INDEX':'daily','LST':'daily','AIR_TEMP':'hourly','REL_HUMIDITY':'hourly','NDVI':'16-day composite','GREEN_SPACE_PCT':'scene-based','BUILTUP_PCT':'scene-based','IMPERVIOUS_PCT':'scene/annual composite','PRECIPITATION':'30 minutes','EXTREME_RAINFALL':'daily/event derived','SOIL_MOISTURE':'daily','SURFACE_WATER_EXTENT':'~3-12 days/observation','FLOOD_EXTENT':'event/observation','DROUGHT_SPI':'monthly + daily','POP_DENSITY':'reference snapshot','VULNERABLE_AGE_PCT':'reference snapshot','ROAD_DENSITY':'snapshot','TRANSPORT_ACCESS_PCT':'schedule/snapshot','HOSPITAL_ACCESS':'snapshot','GREEN_ACCESS_PCT':'annual/scene composite','CRIT_INFRA_DENSITY':'snapshot','NIGHT_LIGHTS':'daily','ELEVATION_SLOPE':'static','DISASTER_READINESS':'daily/monthly/event derived'}
urls={
'PM2_5':'https://worldview.earthdata.nasa.gov/?p=geographic&l=GEOS-CF_Surface_PM25_Day%2Cv1.0','PM10':'https://worldview.earthdata.nasa.gov/?p=geographic&l=GEOS-CF_Surface_PM10_Day%2Cv1.0','NO2':'https://aura.gsfc.nasa.gov/omi.html','O3':'https://aura.gsfc.nasa.gov/omi.html','SO2':'https://aura.gsfc.nasa.gov/omi.html','CO':'https://airs.jpl.nasa.gov/','AEROSOL_INDEX':'https://worldview.earthdata.nasa.gov/','LST':'https://worldview.earthdata.nasa.gov/','AIR_TEMP':'https://search.earthdata.nasa.gov/','REL_HUMIDITY':'https://search.earthdata.nasa.gov/','NDVI':'https://worldview.earthdata.nasa.gov/','GREEN_SPACE_PCT':'https://search.earthdata.nasa.gov/search?q=HLS','BUILTUP_PCT':'https://science.nasa.gov/mission/landsat/data-overview/','IMPERVIOUS_PCT':'https://search.earthdata.nasa.gov/','PRECIPITATION':'https://gpm.nasa.gov/data/imerg','EXTREME_RAINFALL':'https://gpm.nasa.gov/data/directory','SOIL_MOISTURE':'https://science.nasa.gov/mission/smap/','SURFACE_WATER_EXTENT':'https://worldview.earthdata.nasa.gov/','FLOOD_EXTENT':'https://worldview.earthdata.nasa.gov/','DROUGHT_SPI':'https://grace.jpl.nasa.gov/data/get-data/','POP_DENSITY':'https://sedac.ciesin.columbia.edu/data/collection/gpw-v4','VULNERABLE_AGE_PCT':'https://search.earthdata.nasa.gov/search?q=SEDAC','ROAD_DENSITY':'https://search.earthdata.nasa.gov/','TRANSPORT_ACCESS_PCT':'https://search.earthdata.nasa.gov/','HOSPITAL_ACCESS':'https://www.earthdata.nasa.gov/centers/lp-daac','GREEN_ACCESS_PCT':'https://search.earthdata.nasa.gov/search?q=HLS','CRIT_INFRA_DENSITY':'https://search.earthdata.nasa.gov/','NIGHT_LIGHTS':'https://www.earthdata.nasa.gov/data/projects/black-marble','ELEVATION_SLOPE':'https://www.earthdata.nasa.gov/centers/lp-daac','DISASTER_READINESS':'https://worldview.earthdata.nasa.gov/'}
preferred={r.component:r.preferred_source for _,r in manifest.iterrows()}
product={r.component:r.product_short_name for _,r in manifest.iterrows()}
# component names in manifest differ from keys; map by id/order
keys=['PM2_5','PM10','NO2','O3','SO2','CO','AEROSOL_INDEX','LST','AIR_TEMP','REL_HUMIDITY','NDVI','GREEN_SPACE_PCT','BUILTUP_PCT','IMPERVIOUS_PCT','PRECIPITATION','EXTREME_RAINFALL','SOIL_MOISTURE','SURFACE_WATER_EXTENT','FLOOD_EXTENT','DROUGHT_SPI','POP_DENSITY','VULNERABLE_AGE_PCT','ROAD_DENSITY','TRANSPORT_ACCESS_PCT','HOSPITAL_ACCESS','GREEN_ACCESS_PCT','CRIT_INFRA_DENSITY','NIGHT_LIGHTS','ELEVATION_SLOPE','DISASTER_READINESS']
manifest=manifest.sort_values('id').reset_index(drop=True)
pref_by_key=dict(zip(keys,manifest['preferred_source']))
prod_by_key=dict(zip(keys,manifest['product_short_name']))
spatial_by_key=dict(zip(keys,manifest['native_spatial_resolution']))

x=pd.read_csv(src)
x['date']=pd.to_datetime(x['date'],errors='coerce').dt.strftime('%Y-%m-%d')
x['source_url']=x['component'].map(urls)
x['native_cycle']=x['component'].map(cycle)
x['preferred_source']=x['component'].map(pref_by_key)
x['preferred_product']=x['component'].map(prod_by_key)
x['native_spatial_resolution']=x['component'].map(spatial_by_key)
x['bbox_west']=89.24;x['bbox_south']=22.80;x['bbox_east']=91.31;x['bbox_north']=24.80
x['requested_period_start']='2025-01-01';x['requested_period_end']='2025-12-31'
cols=['date','location_id','location_name','lat','lon','component','value','unit','status','source','dataset','variable','method','measurement_date','lag_days','qa_score','is_proxy','native_cycle','native_spatial_resolution','preferred_source','preferred_product','source_url','bbox_west','bbox_south','bbox_east','bbox_north','requested_period_start','requested_period_end','metadata_json','error','retrieved_at']
for c in cols:
    if c not in x: x[c]=''
x=x[cols]
x.to_csv(out,index=False,encoding='utf-8-sig')
print(out)
print('rows',len(x),'nonnull',int(x['value'].notna().sum()),'components',x['component'].nunique())