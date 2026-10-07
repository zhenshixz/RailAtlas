export const TRAVEL_COLORS=['#17866e','#4487b3','#c98c42'];

export function formatMinutes(value){
  const minutes=Math.round(value);
  if(minutes<60)return `${minutes}分钟`;
  const hours=Math.floor(minutes/60),rest=minutes%60;
  return `${hours}小时${rest?`${rest}分`:''}`;
}
export function travelColor(minutes,limit){
  return TRAVEL_COLORS[Math.min(2,Math.floor(minutes/(limit/3)))];
}
function clock(value){
  const match=/^(\d{2}):(\d{2})$/.exec(value||'');
  if(!match||Number(match[1])>23||Number(match[2])>59)return null;
  return Number(match[1])*60+Number(match[2]);
}
function dayOf(stop){
  if(/^\d+$/.test(String(stop.dayDiff??'')))return Number(stop.dayDiff);
  if(/当日|当天/.test(stop.day||''))return 0;
  if(/次日|翌日/.test(stop.day||''))return 1;
  const day=/第([一二三四五六七八九十]|\d+)日/.exec(stop.day||'');
  return day?(/^\d+$/.test(day[1])?Number(day[1]):'一二三四五六七八九十'.indexOf(day[1])+1)-1:null;
}
export function timeline(stops){
  let previous=null;
  const rows=[];
  for(const stop of stops){
    const day=dayOf(stop),arrive=clock(stop.arrival),depart=clock(stop.departure);
    let arrival=null,departure=null;
    if(arrive!=null){
      arrival=(day??Math.floor((previous??0)/1440))*1440+arrive;
      if(day==null&&previous!=null)while(arrival<previous)arrival+=1440;
      if(previous!=null&&arrival<previous)return null;
    }
    if(depart!=null){
      departure=(arrival!=null?Math.floor(arrival/1440):day??Math.floor((previous??0)/1440))*1440+depart;
      const lower=arrival??previous;
      if(lower!=null)while(departure<lower)departure+=1440;
    }
    rows.push({arrival,departure});
    previous=departure??arrival??previous;
  }
  return rows;
}
export function directDestinations(routes,originName,stations){
  if(!originName)return [];
  const byName=new Map(stations.map(station=>[station.name,station])),destinations=new Map();
  for(const route of routes){
    if(!['G','D','C'].includes(route.kind))continue;
    const start=route.stops.findIndex(stop=>stop.name===originName);
    if(start<0||start===route.stops.length-1)continue;
    const times=timeline(route.stops);
    if(!times||times[start].departure==null)continue;
    const departure=times[start].departure;
    for(let end=start+1;end<route.stops.length;end++){
      const stop=route.stops[end],station=byName.get(stop.name),arrival=times[end].arrival;
      if(stop.name===originName||!station||arrival==null||arrival<=departure)continue;
      if(!destinations.has(stop.name))destinations.set(stop.name,{station,trips:[],seen:new Set()});
      const result=destinations.get(stop.name);
      // Public search may return duplicate versions of one daily service.
      const key=`${route.code}:${departure}:${arrival}`;
      if(result.seen.has(key))continue;
      result.seen.add(key);
      result.trips.push({route,start,end,minutes:arrival-departure,departure:route.stops[start].departure,
        arrival:stop.arrival,arrivalDay:Math.floor(arrival/1440)-Math.floor(departure/1440)});
    }
  }
  return [...destinations.values()].map(({station,trips})=>{
    trips.sort((a,b)=>a.minutes-b.minutes||a.departure.localeCompare(b.departure));
    const middle=Math.floor(trips.length/2);
    const median=trips.length%2?trips[middle].minutes:(trips[middle-1].minutes+trips[middle].minutes)/2;
    return {station,trips,median,min:trips[0].minutes,max:trips.at(-1).minutes,count:trips.length};
  }).sort((a,b)=>a.median-b.median||b.count-a.count||a.station.name.localeCompare(b.station.name,'zh-CN'));
}
