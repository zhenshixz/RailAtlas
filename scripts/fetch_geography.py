"""Fetch/caches geography; preserves source IDs and TLS verification."""
import json, time, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
def get(name,url,query=None):
    path=DATA/name
    if path.exists():
        print('Cached '+name,flush=True)
        return json.loads(path.read_text(encoding='utf-8')) if name.endswith('.json') else None
    if query:url+='?'+urllib.parse.urlencode({'data':query})
    req=urllib.request.Request(url,headers={'User-Agent':'RailAtlas/1.0 public-data local viewer'})
    with urllib.request.urlopen(req,timeout=95) as response:raw=response.read()
    if name.endswith('.json'):
        obj=json.loads(raw)
        if obj.get('remark'):raise ValueError(obj['remark'])
        path.write_bytes(raw)
        print(f'{name}: {len(obj.get("elements",[]))} elements',flush=True)
        return obj
    path.write_bytes(raw)
    print(f'{name}: {len(raw)} bytes',flush=True)

if __name__=='__main__':
    for name,url in [('coordinate-stations.csv','https://raw.githubusercontent.com/listenzcc/China-rail-way-stations-data/main/src/station.csv'),('china.geojson','https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json')]:
        try:get(name,url)
        except Exception as exc:print(name+': '+str(exc),flush=True)
    endpoint='https://overpass.private.coffee/api/interpreter'
    queries=[('osm-stations.json','[out:json][timeout:75];nwr(18,73,54,135)[railway=station][station!=subway][station!=light_rail][subway!=yes];out center tags;'),('osm-highspeed.json','[out:json][timeout:75];way(18,73,54,135)[railway=rail][highspeed=yes];out geom;')]
    for name,query in queries:
        try:get(name,endpoint,query)
        except Exception as exc:print(name+': '+str(exc),flush=True)
        time.sleep(1)
    path=DATA/'osm-highspeed.json'
    if path.exists():
        raw=json.loads(path.read_text(encoding='utf-8'));features=[]
        for way in raw.get('elements',[]):
            points=way.get('geometry',[])
            if len(points)<2:continue
            features.append({'type':'Feature','properties':{'osmId':way['id'],'name':way.get('tags',{}).get('name:zh',way.get('tags',{}).get('name','')),'source':'OpenStreetMap','highspeed':True},'geometry':{'type':'LineString','coordinates':[[p['lon'],p['lat']] for p in points]}})
        (DATA/'rails.geojson').write_text(json.dumps({'type':'FeatureCollection','source':'OpenStreetMap highspeed=yes ways','timestamp':raw.get('osm3s',{}).get('timestamp_osm_base'),'features':features},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        print(f'Prepared {len(features)} actual railway ways',flush=True)
