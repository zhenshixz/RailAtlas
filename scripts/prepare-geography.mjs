import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8').replace(/^\uFEFF/,''));
const china=read('data/china.geojson');
const polygons=[];
for(const f of china.features){const shape=f.geometry.type==='Polygon'?[f.geometry.coordinates]:f.geometry.coordinates;for(const rings of shape){const ring=rings[0];if(!ring?.length)continue;polygons.push({rings,province:f.properties.name.replace(/(?:壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区|省|市)$/u,''),bounds:[Math.min(...ring.map(p=>p[0])),Math.min(...ring.map(p=>p[1])),Math.max(...ring.map(p=>p[0])),Math.max(...ring.map(p=>p[1]))]});}}
function inRing([x,y],ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const [ax,ay]=ring[i],[bx,by]=ring[j];if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;}return inside;}
function province(p){for(const poly of polygons){const [x,y]=p,[a,b,c,d]=poly.bounds;if(x<a||y<b||x>c||y>d)continue;if(inRing(p,poly.rings[0])&&!poly.rings.slice(1).some(r=>inRing(p,r)))return poly.province;}return null;}
const network=read('node_modules/@railroute-ts/china/dist/data/network.json');
const features=[];
for(const f of network.features){let part=[];const push=()=>{if(part.length>1)features.push({type:'Feature',properties:{source:'OpenStreetMap',sourcePackage:'@railroute-ts/china 2026.9.1',name:'OSM 铁路轨道（含普速与高铁）'},geometry:{type:'LineString',coordinates:part}});part=[];};for(const p of f.geometry.coordinates){if(province(p))part.push(p);else push();}push();}
fs.writeFileSync(path.join(root,'data/rails.geojson'),JSON.stringify({type:'FeatureCollection',metadata:{...network.metadata,scope:'位于DataV中国省级边界内的OSM铁路轨道；包含普速，未按高铁分类',sourceUrl:'https://github.com/mayurrawte/railroutes/tree/main/packages/china',featureCount:features.length},features}));
const stationText=fs.readFileSync(path.join(root,'data/raw/station_name.js'),'utf8');
const dictionary=stationText.split('@').slice(1).map(s=>s.split('|')).filter(f=>/^[A-Z]{3}$/.test(f[2]||''));
function normalize(s){return s.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/\s*(?:railway|railroad|train|rail)?\s*station$/,'').replace(/\b(harbin|hohhot|lhasa|ordos|airport)\b/g,m=>({harbin:'haerbin',hohhot:'huhehaote',lhasa:'lasa',ordos:'eerduosi',airport:'jichang'}[m])).replace(/\b(south|north|east|west)\b/g,m=>({south:'nan',north:'bei',east:'dong',west:'xi'}[m])).replace(/[^a-z0-9]/g,'');}
const index=new Map();
for(const s of read('node_modules/@railroute-ts/china/dist/data/stations.json')){const prov=province(s.coord);if(!prov)continue;const key=normalize(s.name);if(!index.has(key))index.set(key,[]);index.get(key).push({...s,province:prov});}
const matched={};
for(const f of dictionary){const key=f[1]==='香港西九龙'?normalize('Hong Kong West Kowloon'):normalize(f[3]);const candidates=index.get(key)||[];const unique=candidates.filter((c,i)=>!candidates.slice(0,i).some(p=>Math.abs(p.coord[0]-c.coord[0])<.008&&Math.abs(p.coord[1]-c.coord[1])<.008));if(unique.length!==1)continue;const s=unique[0];matched[f[1]]={lng:s.coord[0],lat:s.coord[1],province:s.province,coordinateSource:'OpenStreetMap（车站名称/规范译名精确匹配）',coordinateUrl:'https://github.com/mayurrawte/railroutes/tree/main/packages/china',coordinateDatasetDate:network.metadata.builtAt,matchedOsmName:s.name};}
fs.writeFileSync(path.join(root,'data/osm-matched-stations.json'),JSON.stringify(matched));
if(fs.existsSync(path.join(root,'data/wikidata-stations.json'))){const wikidata=read('data/wikidata-stations.json');for(const point of Object.values(wikidata)){const prov=province([point.lng,point.lat]);if(prov)point.province=prov;}fs.writeFileSync(path.join(root,'data/wikidata-stations.json'),JSON.stringify(wikidata));}
console.log(JSON.stringify({railFeatures:features.length,matchedStations:Object.keys(matched).length,sourceDate:network.metadata.builtAt}));
