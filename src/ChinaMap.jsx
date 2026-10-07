import React,{useEffect,useRef} from 'react';
import L from 'leaflet';
import {stationLayer} from './station-layer';
import {provinceLabels} from './province-labels';
const COLORS={G:'#147c65',D:'#4385bd',C:'#d48c35',unknown:'#a1aaa6'};

function ChinaMap({stations,allStations,china,rails,segments,origin,selected,activeRoute,showConnections,showRails,onSelect,mapRef}){
  const element=useRef(null),points=useRef(null),labels=useRef(null),network=useRef(null),track=useRef(null),highlight=useRef(null),stationsRef=useRef(stations),selectRef=useRef(onSelect);
  stationsRef.current=stations;selectRef.current=onSelect;
  useEffect(()=>{
    if(!element.current||!china)return;
    const map=L.map(element.current,{zoomControl:false,attributionControl:false,minZoom:3,maxZoom:17,preferCanvas:true,zoomSnap:.25}).setView([35,105],4.5);
    mapRef.current=map;
    L.control.attribution({position:'bottomright',prefix:false}).addAttribution('边界 © <a href="https://datav.aliyun.com/portal/school/atlas/area_selector" target="_blank" rel="noopener">DataV</a> · 轨道 © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a> · 坐标：OSM / Wikidata / 社区').addTo(map);
    L.geoJSON(china,{style:{color:'#a2b292',weight:1.4,dashArray:'5 4',fillColor:'#f4f6eb',fillOpacity:1},interactive:false}).addTo(map);
    labels.current=provinceLabels(map,china);
    network.current=L.layerGroup().addTo(map);track.current=L.layerGroup().addTo(map);highlight.current=L.layerGroup().addTo(map);
    map.createPane('stations');map.getPane('stations').style.zIndex=450;
    map.createPane('selected');map.getPane('selected').style.zIndex=500;
    points.current=stationLayer(stationsRef.current,station=>selectRef.current(station)).addTo(map);
    map.fitBounds([[18,73.5],[53.6,135]],{padding:[35,30]});
    const observer=new ResizeObserver(()=>map.invalidateSize());observer.observe(element.current);
    map._atlasDraw=()=>points.current?.setStations(stationsRef.current,station=>selectRef.current(station));
    return()=>{observer.disconnect();labels.current?.remove();map.remove();mapRef.current=null;};
  },[china]);
  useEffect(()=>mapRef.current?._atlasDraw?.(),[stations]);
  useEffect(()=>{
    if(!network.current)return;network.current.clearLayers();if(!showConnections)return;
    const visible=new Set(stations.map(s=>s.name));
    for(const edge of segments||[]){if(!visible.has(edge.from)||!visible.has(edge.to))continue;L.polyline(edge.coordinates,{color:COLORS[edge.kinds[0]],weight:1.3,opacity:.28,dashArray:'3 5',interactive:false}).addTo(network.current);}
  },[segments,showConnections,stations,china]);
  useEffect(()=>{
    if(!track.current)return;track.current.clearLayers();if(showRails&&rails)L.geoJSON(rails,{style:{color:'#789b88',weight:1.3,opacity:.38},onEachFeature:(f,l)=>l.bindTooltip(f.properties.name||'OSM 铁路轨道（含普速与高铁）')}).addTo(track.current);
  },[rails,showRails,china]);
  useEffect(()=>{
    if(!highlight.current)return;highlight.current.clearLayers();
    if(origin?.lng!=null)L.circleMarker([origin.lat,origin.lng],{pane:'selected',radius:10,color:'#125b4c',weight:3,fillColor:'#fff',fillOpacity:.85}).addTo(highlight.current).bindTooltip(`${origin.name}站 · 出发`,{permanent:true,direction:'top',className:'selected-label'});
    if(selected?.lng!=null)L.circleMarker([selected.lat,selected.lng],{pane:'selected',radius:12,color:'#175f4e',weight:2,fillColor:'#fff',fillOpacity:.7}).addTo(highlight.current).bindTooltip(`${selected.name}站`,{permanent:true,direction:'top',className:'selected-label'});
    if(activeRoute){const byName=new Map(allStations.map(s=>[s.name,s]));
      activeRoute.stops.forEach((stop,i)=>{const a=byName.get(stop.name),b=byName.get(activeRoute.stops[i+1]?.name);if(a?.lng!=null)L.circleMarker([a.lat,a.lng],{pane:'selected',radius:7,color:'#fff',weight:2,fillColor:COLORS[activeRoute.kind],fillOpacity:1}).addTo(highlight.current).bindTooltip(`${i+1}. ${a.name}站`).on('click',()=>selectRef.current(a));if(a?.lng!=null&&b?.lng!=null)L.polyline([[a.lat,a.lng],[b.lat,b.lng]],{pane:'selected',color:COLORS[activeRoute.kind],weight:3,opacity:.9,dashArray:'6 7',interactive:false}).addTo(highlight.current);});
    }
  },[origin,selected,activeRoute,allStations,china]);
  return <div className="china-map" ref={element} aria-label="中国铁路交互地图"/>;
}

export default ChinaMap;
