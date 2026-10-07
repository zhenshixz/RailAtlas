import L from 'leaflet';

function clip(ring,bounds){
  let points=ring;
  for(const [axis,value,sign] of [[0,bounds.getWest(),1],[0,bounds.getEast(),-1],[1,bounds.getSouth(),1],[1,bounds.getNorth(),-1]]){
    const next=[];
    for(let i=0;i<points.length;i++){
      const a=points[i],b=points[(i+1)%points.length];
      const insideA=(a[axis]-value)*sign>=0,insideB=(b[axis]-value)*sign>=0;
      if(insideA)next.push(a);
      if(insideA!==insideB){const t=(value-a[axis])/(b[axis]-a[axis]);next.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);}
    }
    points=next;if(!points.length)break;
  }
  return points;
}
function inside(point,ring){
  let result=false;
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const a=ring[i],b=ring[j];
    if((a[1]>point[1])!==(b[1]>point[1])&&point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])result=!result;
  }
  return result;
}
function centroid(ring){
  let area=0,x=0,y=0;
  for(let i=0;i<ring.length;i++){
    const a=ring[i],b=ring[(i+1)%ring.length],cross=a[0]*b[1]-b[0]*a[1];
    area+=cross;x+=(a[0]+b[0])*cross;y+=(a[1]+b[1])*cross;
  }
  return Math.abs(area)>1e-10?{area:Math.abs(area),point:[x/(3*area),y/(3*area)]}:null;
}

export function provinceLabels(map,china){
  const group=L.layerGroup().addTo(map);
  const entries=china.features.map(feature=>{
    const geometry=feature.geometry;
    const polygons=geometry.type==='Polygon'?[geometry.coordinates]:geometry.type==='MultiPolygon'?geometry.coordinates:[];
    const marker=L.marker([0,0],{interactive:false,icon:L.divIcon({className:'province-label',html:'',iconSize:[150,26],iconAnchor:[75,13]}),zIndexOffset:-1000});
    return {feature,polygons,marker};
  });
  let frame;
  const draw=()=>{
    frame=null;
    const view=map.getBounds().pad(-.08);
    for(const {feature,polygons,marker} of entries){
      let best=null;
      for(const polygon of polygons){
        const ring=clip(polygon[0],view),candidate=centroid(ring);
        if(!candidate||candidate.area<=(best?.area||0))continue;
        const valid=p=>inside(p,ring)&&!polygon.slice(1).some(hole=>inside(p,hole));
        if(!valid(candidate.point)){
          const xs=ring.map(p=>p[0]),ys=ring.map(p=>p[1]);
          const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
          let point=null,distance=Infinity;
          for(let x=1;x<8;x++)for(let y=1;y<8;y++){
            const p=[minX+(maxX-minX)*x/8,minY+(maxY-minY)*y/8];
            const d=(p[0]-candidate.point[0])**2+(p[1]-candidate.point[1])**2;
            if(valid(p)&&d<distance){point=p;distance=d;}
          }
          if(!point)continue;candidate.point=point;
        }
        best=candidate;
      }
      if(!best){group.removeLayer(marker);continue;}
      const original=feature.properties.centroid||feature.properties.center;
      const point=original&&view.contains([original[1],original[0]])?original:best.point;
      marker.setLatLng([point[1],point[0]]);
      if(!group.hasLayer(marker)){group.addLayer(marker);marker.getElement().textContent=feature.properties.name;}
    }
  };
  const schedule=()=>{if(frame==null)frame=requestAnimationFrame(draw);};
  map.on('moveend zoomend resize',schedule);schedule();
  return {remove(){cancelAnimationFrame(frame);map.off('moveend zoomend resize',schedule);group.remove();}};
}
