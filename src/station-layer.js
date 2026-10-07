import L from 'leaflet';

const COLORS={G:'#147c65',D:'#4385bd',C:'#d48c35',unknown:'#a1aaa6'};
const HIT_CELL=32,LABEL_CELL=40,PADDING=80;

// One canvas replaces thousands of Leaflet markers, tooltips and DOM labels.
// Only the visible area is painted; panning reuses the canvas until moveend.
const StationLayer=L.Layer.extend({
  initialize(stations,onSelect){
    this._stations=stations;
    this._onSelect=onSelect;
    this._widths=new Map();
    this._hits=new Map();
    this._labelHits=new Map();
  },
  onAdd(map){
    this._canvas=L.DomUtil.create('canvas','leaflet-zoom-animated rail-station-canvas',map.getPane('stations'));
    this._canvas.setAttribute('aria-hidden','true');
    this._context=this._canvas.getContext('2d');
    this.redraw();
  },
  onRemove(map){
    cancelAnimationFrame(this._frame);
    this._frame=null;
    this._canvas.remove();
    map.getContainer().style.cursor='';
    this._hits.clear();
    this._labelHits.clear();
  },
  getEvents(){
    return {moveend:this.redraw,zoomend:this.redraw,resize:this.redraw,viewreset:this.redraw,
      zoom:this._syncTransform,move:this._syncTransform,
      zoomanim:this._animateZoom,click:this._click,mousemove:this._hover};
  },
  setStations(stations,onSelect){
    this._stations=stations;
    this._onSelect=onSelect;
    this.redraw();
  },
  redraw(){
    if(!this._map||this._frame!=null)return;
    this._frame=requestAnimationFrame(()=>{
      this._frame=null;
      if(this._map&&!this._map._animatingZoom)this._draw();
    });
  },
  _animateZoom(event){
    if(!this._origin)return;
    const scale=this._map.getZoomScale(event.zoom,this._zoom);
    const offset=this._map._latLngToNewLayerPoint(this._origin,event.zoom,event.center);
    L.DomUtil.setTransform(this._canvas,offset,scale);
  },
  _syncTransform(){
    // flyTo and pinch gestures fire zoom/move, rather than zoomanim. Reuse the
    // painted world origin each frame so stations stay aligned with rail paths.
    if(this._origin)this._animateZoom({zoom:this._map.getZoom(),center:this._map.getCenter()});
  },
  _find(point,minimumRadius=0){
    if(!point||this._zoom!==this._map.getZoom())return;
    const x=Math.floor(point.x/HIT_CELL),y=Math.floor(point.y/HIT_CELL);
    let nearest,distance=Infinity;
    for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
      for(const item of this._hits.get(`${x+dx},${y+dy}`)||[]){
        const d=(point.x-item.layerPoint.x)**2+(point.y-item.layerPoint.y)**2;
        if(d<=Math.max(item.radius+5,minimumRadius)**2&&d<distance){nearest=item;distance=d;}
      }
    }
    if(nearest)return nearest;
    for(const item of this._labelHits.get(`${x},${y}`)||[]){
      const box=item.box;
      if(point.x>=box.x&&point.x<=box.x+box.w&&point.y>=box.y&&point.y<=box.y+box.h)return item.hit;
    }
  },
  _click(event){
    const touch=window.matchMedia('(max-width:800px) and (pointer:coarse)').matches;
    const item=this._find(event.layerPoint,touch?22:0);
    if(!item)return;
    if(item.stations.length===1)this._onSelect(item.stations[0]);
    else this._map.fitBounds(item.stations.map(s=>[s.lat,s.lng]),{
      maxZoom:Math.max(7,this._zoom+2),padding:[70,70]
    });
  },
  _hover(event){
    if(this._map.dragging?.moving())return;
    this._map.getContainer().style.cursor=this._find(event.layerPoint)?'pointer':'';
  },
  _draw(){
    const started=performance.now(),map=this._map,canvas=this._canvas,ctx=this._context;
    const size=map.getSize(),zoom=map.getZoom(),ratio=Math.min(window.devicePixelRatio||1,2);
    const width=size.x+PADDING*2,height=size.y+PADDING*2;
    if(canvas.width!==Math.ceil(width*ratio)||canvas.height!==Math.ceil(height*ratio)){
      canvas.width=Math.ceil(width*ratio);canvas.height=Math.ceil(height*ratio);
      canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;
    }
    this._zoom=zoom;
    this._origin=map.containerPointToLatLng([-PADDING,-PADDING]);
    const topLeft=map.containerPointToLayerPoint([-PADDING,-PADDING]);
    L.DomUtil.setTransform(canvas,topLeft);
    ctx.setTransform(ratio,0,0,ratio,0,0);
    ctx.clearRect(0,0,width,height);
    this._hits.clear();
    this._labelHits.clear();
    const bounds=map.getBounds().pad(.25),buckets=new Map(),aggregate=zoom<6;
    let visibleStations=0;
    for(const station of this._stations){
      if(station.lng==null||!bounds.contains([station.lat,station.lng]))continue;
      const point=map.latLngToContainerPoint([station.lat,station.lng]);
      if(point.x< -PADDING||point.x>size.x+PADDING||point.y< -PADDING||point.y>size.y+PADDING)continue;
      const world=aggregate?map.project([station.lat,station.lng],zoom):null;
      const key=aggregate&&!station.mapOrigin?`${Math.floor(world.x/27)},${Math.floor(world.y/27)}`:station.name;
      if(!buckets.has(key))buckets.set(key,[]);
      buckets.get(key).push(station);visibleStations++;
    }
    const names=[];
    ctx.lineWidth=1.5;ctx.strokeStyle='#fff';ctx.textAlign='center';ctx.textBaseline='middle';
    let clusters=0;
    for(const stations of buckets.values()){
      const grouped=stations.length>1;
      const lat=stations.reduce((sum,s)=>sum+s.lat,0)/stations.length;
      const lng=stations.reduce((sum,s)=>sum+s.lng,0)/stations.length;
      const layerPoint=map.latLngToLayerPoint([lat,lng]),point=layerPoint.subtract(topLeft);
      const radius=grouped?Math.min(13,6+Math.log2(stations.length)):(zoom<6?4:6);
      ctx.fillStyle=grouped?'#258771':stations[0].mapColor||COLORS[stations[0].kinds[0]||'unknown'];
      ctx.beginPath();ctx.arc(point.x,point.y,radius,0,Math.PI*2);ctx.fill();ctx.stroke();
      const key=`${Math.floor(layerPoint.x/HIT_CELL)},${Math.floor(layerPoint.y/HIT_CELL)}`;
      if(!this._hits.has(key))this._hits.set(key,[]);
      const hit={stations,layerPoint,radius};
      this._hits.get(key).push(hit);
      if(grouped){
        clusters++;ctx.font='700 12px "Microsoft YaHei", sans-serif';ctx.fillStyle='#fff';
        ctx.fillText(String(stations.length),point.x,point.y);
      }else if(!stations[0].mapOrigin&&point.x>=PADDING&&point.x<=size.x+PADDING&&point.y>=PADDING&&point.y<=size.y+PADDING){
        names.push({station:stations[0],point,radius,hit});
      }
    }
    // Prioritize busy stations and place labels in free space around each dot.
    // The grid avoids quadratic overlap checks, and the budget scales by area.
    names.sort((a,b)=>(b.station.mapPriority??b.station.trains?.length??0)-(a.station.mapPriority??a.station.trains?.length??0));
    const occupied=new Map(),budget=Math.min(450,Math.max(30,Math.floor(size.x*size.y/3600)));
    const cells=rect=>{
      const keys=[];
      for(let x=Math.floor(rect.x/LABEL_CELL);x<=Math.floor((rect.x+rect.w)/LABEL_CELL);x++)
        for(let y=Math.floor(rect.y/LABEL_CELL);y<=Math.floor((rect.y+rect.h)/LABEL_CELL);y++)keys.push(`${x},${y}`);
      return keys;
    };
    ctx.font='600 15px "Microsoft YaHei", sans-serif';
    ctx.textAlign='left';ctx.textBaseline='middle';ctx.lineJoin='round';ctx.lineWidth=4;
    let labels=0;
    for(const {station,point,radius,hit} of names){
      if(labels>=budget)break;
      const text=station.mapLabel||`${station.name}站`;
      if(!this._widths.has(text))this._widths.set(text,ctx.measureText(text).width);
      const w=this._widths.get(text)+8,h=23,gap=radius+6;
      const candidates=[
        {x:point.x+gap,y:point.y-h/2,w,h},
        {x:point.x-gap-w,y:point.y-h/2,w,h},
        {x:point.x-w/2,y:point.y-gap-h,w,h},
        {x:point.x-w/2,y:point.y+gap,w,h}
      ];
      for(const rect of candidates){
        if(rect.x<PADDING||rect.x+rect.w>PADDING+size.x||rect.y<PADDING||rect.y+rect.h>PADDING+size.y)continue;
        const keys=cells(rect);
        if(keys.some(key=>(occupied.get(key)||[]).some(other=>rect.x<other.x+other.w&&rect.x+rect.w>other.x&&rect.y<other.y+other.h&&rect.y+rect.h>other.y)))continue;
        for(const key of keys){if(!occupied.has(key))occupied.set(key,[]);occupied.get(key).push(rect);}
        ctx.strokeStyle='#f9fcf5';ctx.strokeText(text,rect.x+3,rect.y+h/2);
        ctx.fillStyle='#285342';ctx.fillText(text,rect.x+3,rect.y+h/2);
        const box={x:rect.x+topLeft.x,y:rect.y+topLeft.y,w:rect.w,h:rect.h};
        for(let x=Math.floor(box.x/HIT_CELL);x<=Math.floor((box.x+box.w)/HIT_CELL);x++)
          for(let y=Math.floor(box.y/HIT_CELL);y<=Math.floor((box.y+box.h)/HIT_CELL);y++){
            const key=`${x},${y}`;
            if(!this._labelHits.has(key))this._labelHits.set(key,[]);
            this._labelHits.get(key).push({box,hit});
          }
        labels++;break;
      }
    }
    canvas.dataset.visibleStations=String(visibleStations);
    canvas.dataset.labels=String(labels);
    canvas.dataset.clusters=String(clusters);
    canvas.dataset.drawMs=(performance.now()-started).toFixed(1);
  }
});

export function stationLayer(stations,onSelect){return new StationLayer(stations,onSelect);}
