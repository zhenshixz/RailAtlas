"""Supplement missing coordinates using exact Chinese Wikidata railway-station names."""
import datetime,json,re,urllib.parse,urllib.request
from pathlib import Path
from sync_data import fetch
ROOT=Path(__file__).resolve().parents[1]
query='''SELECT ?station ?stationLabel ?coord WHERE {
  ?station wdt:P17 wd:Q148; wdt:P625 ?coord; wdt:P31/wdt:P279* wd:Q55488.
  MINUS { ?station wdt:P31/wdt:P279* wd:Q928830. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "zh-hans,zh". }
}'''
url='https://query.wikidata.org/sparql?'+urllib.parse.urlencode({'query':query,'format':'json'})
obj=json.loads(fetch(url,timeout=65))
rows={}
for row in obj['results']['bindings']:
    name=re.sub(r'\s+','',row['stationLabel']['value']).removesuffix('站')
    match=re.fullmatch(r'Point\(([-0-9.]+) ([-0-9.]+)\)',row['coord']['value'])
    if not match:continue
    lng,lat=map(float,match.groups())
    if not (73<lng<136 and 18<lat<54):continue
    point={'lng':lng,'lat':lat,'coordinateSource':'Wikidata（铁路车站中文名称精确匹配）','coordinateUrl':row['station']['value'].replace('http:','https:'),'coordinateDatasetDate':datetime.date.today().isoformat()}
    rows.setdefault(name,[]).append(point)
result={name:values[0] for name,values in rows.items() if len(values)==1}
(ROOT/'data'/'wikidata-stations.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print(json.dumps({'uniqueStations':len(result),'source':'Wikidata CC0'}))
