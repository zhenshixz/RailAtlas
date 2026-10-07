"""Read public 12306 data politely, cache validated responses and resume interrupted jobs."""
import argparse, concurrent.futures, csv, datetime, json, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
RAW=DATA/'raw'
RAW.mkdir(exist_ok=True)
STATION_URL='https://kyfw.12306.cn/otn/resources/js/framework/station_name.js'
SEARCH_URL='https://search.12306.cn/search/v1/train/search'
STOPS_URL='https://kyfw.12306.cn/otn/queryTrainInfo/query'
lock=threading.Lock()
sessions=threading.local()
try:
    import requests
except ImportError:
    requests=None

def save(path,obj):
    tmp=path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    # Windows readers/antivirus can briefly deny replacement of an open file.
    # Keep the previous published snapshot intact, and retry the atomic rename.
    deadline=time.monotonic()+8
    attempt=0
    try:
        while True:
            try:
                tmp.replace(path);return
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(min(.05*2**min(attempt,4),.5));attempt+=1
    finally:
        if tmp.exists():tmp.unlink()

def acquire_lock():
    handle=(DATA/'sync.lock').open('a+b')
    if handle.tell()==0:handle.write(b'0');handle.flush()
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close();raise RuntimeError('Another RailAtlas sync job is already running.')
    return handle

def fetch(url,timeout=25):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0', 'Referer':'https://www.12306.cn/'})
    for attempt in range(2):
        try:
            if requests is not None:
                if not hasattr(sessions,'client'):sessions.client=requests.Session()
                proxies=requests.utils.get_environ_proxies(url)
                # Windows Internet Settings may label the HTTP CONNECT proxy for
                # HTTPS destinations as https://localhost. Keep the same proxy
                # address and use its verified HTTP transport, like urllib does.
                if os.name=='nt':
                    for key,value in list(proxies.items()):
                        parsed=urllib.parse.urlsplit(value)
                        if parsed.scheme=='https' and parsed.hostname in ('127.0.0.1','localhost','::1'):
                            proxies[key]=urllib.parse.urlunsplit(('http',parsed.netloc,parsed.path,parsed.query,parsed.fragment))
                response=sessions.client.get(url,headers=dict(req.header_items()),timeout=timeout,proxies=proxies)
                if response.status_code in (403,429,502,503,504) and not attempt:
                    time.sleep(4);continue
                response.raise_for_status()
                return response.content.decode('utf-8')
            with urllib.request.urlopen(req,timeout=timeout) as response:return response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            if attempt or exc.code not in (403,429,502,503,504):raise
            # Retry the same public request once after a pause. Never solve or bypass a challenge.
            time.sleep(4)

def fetch_json(url):
    obj=json.loads(fetch(url))
    if obj.get('status') is not True: raise RuntimeError('12306 returned an unsuccessful response')
    return obj

def coordinates():
    result={}
    # A unique English map label can still identify several Chinese stations.
    # Reject homophone-only matches, even in older prepared coordinate files.
    owners={}
    dictionary=RAW/'station_name.js'
    if dictionary.exists():
        for entry in dictionary.read_text(encoding='utf-8').split('@')[1:]:
            fields=entry.split('|')
            if len(fields)>3:
                owners.setdefault(fields[3].lower(),set()).add(fields[1])
    ambiguous={name for names in owners.values() if len(names)>1 for name in names}
    path=DATA/'coordinate-stations.csv'
    if path.exists():
        for row in csv.DictReader(path.open(encoding='utf-8-sig',newline='')):
            try:
                lng,lat=float(row['WGS84_Lng']),float(row['WGS84_Lat'])
                if not (73<=lng<=136 and 18<=lat<=54): continue
                name=row['站名'].removesuffix('站')
                result[name]={'lng':lng,'lat':lat,'province':row['省'],'city':row['市'],'address':row['车站地址'],'coordinateSource':'社区车站坐标库（WGS84）','coordinateUrl':'https://github.com/listenzcc/China-rail-way-stations-data'}
            except (ValueError,KeyError): continue
    wikidata=DATA/'wikidata-stations.json'
    if wikidata.exists():
        for name,point in json.loads(wikidata.read_text(encoding='utf-8')).items():
            if name not in result:result[name]=point
    matched=DATA/'osm-matched-stations.json'
    if matched.exists():
        for name,point in json.loads(matched.read_text(encoding='utf-8')).items():
            if name not in result and name not in ambiguous:result[name]=point
    osm=DATA/'osm-stations.json'
    if osm.exists():
        for el in json.loads(osm.read_text(encoding='utf-8')).get('elements',[]):
            tags=el.get('tags',{}); pos=el.get('center',el)
            name=tags.get('name:zh',tags.get('name','')).removesuffix('站')
            if not name or 'lat' not in pos: continue
            # Retain supplied province/city when a newer OSM point is available.
            point={**result.get(name,{}),'lng':pos['lon'],'lat':pos['lat'],'coordinateSource':'OpenStreetMap（WGS84）','coordinateUrl':f"https://www.openstreetmap.org/{el['type']}/{el['id']}"}
            if name not in result or el['type']=='node': result[name]=point
    overrides=DATA/'coordinate-overrides.json'
    if overrides.exists():
        for name,point in json.loads(overrides.read_text(encoding='utf-8')).items():
            if not (-180<=point['lng']<=180 and -90<=point['lat']<=90) or not point.get('coordinateUrl'):
                raise ValueError('Invalid audited coordinate override: '+name)
            result[name]=point
    return result

def station_dictionary(cached_only=False):
    path=RAW/'station_name.js'
    try:
        text=path.read_text(encoding='utf-8') if cached_only else fetch(STATION_URL)
        if len(text)<10000 or 'station_names' not in text: raise ValueError('Invalid station dictionary')
        path.write_text(text,encoding='utf-8')
    except Exception:
        if not path.exists(): raise
        print('Station refresh failed, retaining official cached dictionary.',flush=True)
        text=path.read_text(encoding='utf-8')
    items=[]
    for entry in text.split('@')[1:]:
        f=entry.split('|')
        if len(f)>=6 and re.fullmatch('[A-Z]{3}',f[2]):
            items.append({'name':f[1],'code':f[2],'pinyin':f[3],'initials':f[4],'city':f[7] if len(f)>7 else ''})
    if len(items)<1000: raise ValueError('Station dictionary unexpectedly small')
    return items

def discover(date):
    folder=RAW/date/'search';folder.mkdir(parents=True,exist_ok=True)
    trains={}; calls=0;failed_prefixes=[]
    def visit(prefix):
        nonlocal calls
        path=folder/(prefix+'.json')
        if path.exists(): obj=json.loads(path.read_text(encoding='utf-8'))
        else:
            obj=fetch_json(SEARCH_URL+'?'+urllib.parse.urlencode({'keyword':prefix,'date':date.replace('-','')}))
            if not isinstance(obj.get('data'),list): raise ValueError('Invalid train search response')
            save(path,obj);time.sleep(.5);calls+=1
        rows=obj['data']
        for r in rows:
            if not r.get('station_train_code','').startswith(('G','D','C')): continue
            if r.get('date')!=date.replace('-',''): raise ValueError('Upstream returned a different date')
            trains[r['train_no']]=r
        if len(rows)>=200:
            if len(prefix)>5: raise ValueError('Search truncation cannot be resolved')
            for digit in '0123456789':
                try:visit(prefix+digit)
                except Exception as exc:
                    failed_prefixes.append({'prefix':prefix+digit,'error':str(exc)})
                    print('Search incomplete: '+prefix+digit+' '+str(exc),flush=True)
    for kind in 'GDC':
        try:visit(kind)
        except Exception as exc:failed_prefixes.append({'prefix':kind,'error':str(exc)})
        save(RAW/date/'trains.json',list(trains.values()))
        print(f'Discovered {kind}: {len(trains)} distinct train IDs',flush=True)
    save(RAW/date/'trains.json',list(trains.values()))
    save(RAW/date/'search-audit.json',{'complete':not failed_prefixes,'failedPrefixes':failed_prefixes})
    return list(trains.values()),not failed_prefixes

def assemble(date,stations,trains,complete,failures):
    dictionary_count=len(stations);loc=coordinates();by_name={s['name']:s for s in stations}
    for s in stations:
        s.update(loc.get(s['name'],{}));s.update({'kinds':[],'trains':[],'verifiedDate':None,'verificationSource':None})
    endpoint_names=set()
    for t in trains:
        kind=t['station_train_code'][0]
        for field in ('from_station','to_station'):
            name=re.sub(r'\s+','',t[field]);endpoint_names.add(name)
            s=by_name.get(name)
            if s is None:
                s={'name':name,'code':None,'pinyin':'','initials':'','city':'','kinds':[],'trains':[],'verifiedDate':None,**loc.get(name,{})}
                stations.append(s);by_name[name]=s
            if kind not in s['kinds']:s['kinds'].append(kind)
            if t['train_no'] not in s['trains']:s['trains'].append(t['train_no'])
            s['verifiedDate']=date;s['verificationSource']='12306 车次搜索（始发/终到）'
    routes=[];segments={};count=0;stop_conflicts=[]
    for t in trains:
        path=RAW/date/'stops'/(t['train_no']+'.json')
        if not path.exists(): continue
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('_railatlasAudit',{}).get('stationCountMismatch'):
            stop_conflicts.append({'train':t['station_train_code'],**data['_railatlasAudit']['stationCountMismatch']})
        stops=data['data']['data'];kind=t['station_train_code'][0];count+=1
        route={'id':t['train_no'],'code':t['station_train_code'],'kind':kind,'from':re.sub(r'\s+','',t['from_station']),'to':re.sub(r'\s+','',t['to_station']),'date':date,'stops':[]}
        for stop in stops:
            name=re.sub(r'\s+','',stop['station_name']);s=by_name.get(name)
            if s is None:
                s={'name':name,'code':None,'pinyin':'','initials':'','city':'','kinds':[],'trains':[],'verifiedDate':None,**loc.get(name,{})}
                stations.append(s);by_name[name]=s
            if kind not in s['kinds']: s['kinds'].append(kind)
            if t['train_no'] not in s['trains']:s['trains'].append(t['train_no'])
            s['verifiedDate']=date;s['verificationSource']='12306 经停查询'
            route['stops'].append({'name':name,'stationCode':s['code'],'arrival':stop.get('arrive_time',''),'departure':stop.get('start_time',''),'stopover':stop.get('stopover_time',''),'day':stop.get('arrive_day_str',''),'dayDiff':stop.get('arrive_day_diff','0')})
        for a,b in zip(route['stops'],route['stops'][1:]):
            aa,bb=by_name[a['name']],by_name[b['name']]
            # Never connect over an intermediate stop without coordinates.
            if 'lng' not in aa or 'lng' not in bb: continue
            key='|'.join(sorted((aa['name'],bb['name'])))
            edge=segments.setdefault(key,{'from':aa['name'],'to':bb['name'],'kinds':[],'trainCount':0,'coordinates':[[aa['lat'],aa['lng']],[bb['lat'],bb['lng']]]})
            edge['trainCount']+=1
            if kind not in edge['kinds']:edge['kinds'].append(kind)
        routes.append(route)
    known=[s for s in stations if s['kinds']];located=[s for s in known if 'lng' in s]
    audit_path=RAW/date/'search-audit.json'
    audit=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}
    meta={'date':date,'updatedAt':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'stationDictionaryCount':dictionary_count,'discoveredTrainCount':len(trains),'completedTrainCount':count,'failedTrainCount':len(failures),'failedSearchPrefixes':audit.get('failedPrefixes',[]),'searchComplete':complete,'coverageComplete':complete and count==len(trains) and bool(trains),'verifiedStationCount':len(known),'mappedStationCount':len(located),'missingCoordinates':len(known)-len(located),'segmentCount':len(segments),'officialStationSource':STATION_URL,'officialTrainSource':SEARCH_URL,'officialStopsSource':STOPS_URL,'scope':'所选日期的12306公开G/D/C车次与经停；不包含未在该日开行的车次、未被公开接口返回的车次或台湾铁路','coordinateSystem':'WGS84','failures':failures[:50]}
    meta['stopCountConflicts']=stop_conflicts
    save(DATA/'atlas.json',{'meta':meta,'stations':stations,'routes':routes,'segments':list(segments.values())})
    return meta

def validate_stops(train,obj):
    rows=obj.get('data',{}).get('data')
    if not isinstance(rows,list) or len(rows)<2 or not all(isinstance(row,dict) and row.get('station_name') for row in rows):
        raise ValueError('官方经停接口暂未返回有效站表')
    normalize=lambda name:re.sub(r'\s+','',name or '')
    if normalize(rows[0]['station_name'])!=normalize(train['from_station']) or normalize(rows[-1]['station_name'])!=normalize(train['to_station']):
        raise ValueError('官方经停始终点与车次目录不一致，暂不采用')
    def valid_clock(value):
        match=re.fullmatch(r'(\d{2}):(\d{2})',value or '')
        return bool(match and int(match[1])<24 and int(match[2])<60)
    if not valid_clock(rows[0].get('start_time')) or not valid_clock(rows[-1].get('arrive_time')):
        raise ValueError('官方经停缺少有效始发或到达时刻')
    mismatch=len(rows)!=int(train['total_num'])
    if mismatch:
        # Search catalogue counts can be stale. Only adopt the detailed official
        # response when its sequence and explicit endpoints prove completeness.
        if [row.get('station_no') for row in rows]!=[str(i).zfill(2) for i in range(1,len(rows)+1)]:
            raise ValueError('目录站数不同且经停序号不完整，暂不采用')
        head=rows[0]
        if head.get('is_start')!='Y' or normalize(head.get('end_station_name'))!=normalize(train['to_station']):
            raise ValueError('目录站数不同且经停详情无法确认终点，暂不采用')
        if head.get('station_train_code')!=train['station_train_code']:
            raise ValueError('目录站数不同且车次标识不一致，暂不采用')
        if any(not valid_clock(row.get('arrive_time')) or not valid_clock(row.get('start_time')) for row in rows[1:-1]):
            raise ValueError('目录站数不同且中间经停时刻缺失，暂不采用')
        obj['_railatlasAudit']={'stationCountMismatch':{'catalogueCount':int(train['total_num']),'detailCount':len(rows)},'source':STOPS_URL,'validatedAt':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()}
    return obj

def fetch_stops(train,date):
    url=STOPS_URL+'?'+urllib.parse.urlencode({'leftTicketDTO.train_no':train['train_no'],'leftTicketDTO.train_date':date,'rand_code':''})
    return validate_stops(train,fetch_json(url))

def repair(date,workers=2):
    folder=RAW/date/'stops';folder.mkdir(parents=True,exist_ok=True)
    catalog=RAW/date/'trains.json'
    if not catalog.exists():raise RuntimeError('尚无已缓存车次目录，需要先同步数据')
    trains=json.loads(catalog.read_text(encoding='utf-8'))
    audit=json.loads((RAW/date/'search-audit.json').read_text(encoding='utf-8'))
    pending=[train for train in trains if not (folder/(train['train_no']+'.json')).exists()]
    progress={'state':'repairing','pid':os.getpid(),'date':date,'total':len(trains),'completed':len(trains)-len(pending),'message':'正在自动补齐缺失经停'}
    save(DATA/'sync-progress.json',progress)
    failures=[]
    def obtain(train):
        try:
            # Refresh only missing services. An internal train number can change
            # while the public code and endpoints remain the same.
            current=train
            try:
                search=fetch_json(SEARCH_URL+'?'+urllib.parse.urlencode({'keyword':train['station_train_code'],'date':date.replace('-','')}))
                choices=[row for row in search.get('data',[]) if row['station_train_code']==train['station_train_code'] and re.sub(r'\s+','',row['from_station'])==re.sub(r'\s+','',train['from_station']) and re.sub(r'\s+','',row['to_station'])==re.sub(r'\s+','',train['to_station'])]
                exact=next((row for row in choices if row['train_no']==train['train_no']),None)
                if exact:current=exact
                elif len(choices)==1:current=choices[0]
            except Exception:pass  # A fresh stop response may still be available.
            obj=fetch_stops(current,date)
            save(folder/(current['train_no']+'.json'),obj)
            return train,current,None
        except Exception as error:return train,train,{'train':train['station_train_code'],'error':str(error)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(2,workers))) as pool:
        for old,current,error in pool.map(obtain,pending):
            if error:failures.append(error)
            else:
                trains[trains.index(old)]=current
                print('Recovered '+current['station_train_code'],flush=True)
    save(catalog,trains)
    meta=assemble(date,station_dictionary(cached_only=True),trains,audit.get('complete',False),failures)
    save(DATA/'sync-progress.json',{'state':'complete' if meta['coverageComplete'] else 'partial','date':date,'total':len(trains),'completed':meta['completedTrainCount'],'failed':len(failures),'message':'经停已自动补齐' if meta['coverageComplete'] else '本轮已补齐可用记录，未返回的官方数据稍后自动重试'})
    return meta

def run(date,workers=3,limit=None):
    folder=RAW/date/'stops';folder.mkdir(parents=True,exist_ok=True)
    stations=station_dictionary();progress={'state':'discovering','pid':os.getpid(),'date':date,'message':'正在按编号分段获取12306车次'};save(DATA/'sync-progress.json',progress)
    cached_list=RAW/date/'trains.json'
    if cached_list.exists():assemble(date,json.loads(json.dumps(stations)),json.loads(cached_list.read_text(encoding='utf-8')),False,[])
    complete=False;failures=[]
    try:
        trains,complete=discover(date)
    except Exception as exc:
        cached=RAW/date/'trains.json'
        if not cached.exists():
            assemble(date,stations,[],False,[]);raise
        trains=json.loads(cached.read_text(encoding='utf-8'));print('Train discovery incomplete: '+str(exc),flush=True)
    save(DATA/'sync-progress.json',{'state':'syncing','pid':os.getpid(),'date':date,'total':len(trains),'completed':sum((folder/(t['train_no']+'.json')).exists() for t in trains)})
    assemble(date,json.loads(json.dumps(stations)),trains,complete,[])
    pending=[t for t in trains if not (folder/(t['train_no']+'.json')).exists()]
    # Read a long itinerary for each origin/destination pair first. This expands
    # station coverage quickly while still downloading every remaining train.
    representatives={}
    for train in pending:
        pair=(train['from_station'],train['to_station'])
        if pair not in representatives or int(train['total_num'])>int(representatives[pair]['total_num']):representatives[pair]=train
    priority={t['train_no'] for t in representatives.values()}
    pending=sorted(representatives.values(),key=lambda t:-int(t['total_num']))+[t for t in pending if t['train_no'] not in priority]
    if limit is not None:pending=pending[:limit]
    consecutive=0;abort=threading.Event()
    def obtain(t):
        if abort.is_set():return t,None,'Stopped after repeated upstream failures'
        try:
            obj=fetch_stops(t,date)
            save(folder/(t['train_no']+'.json'),obj);time.sleep(.25)
            return t,obj,None
        except Exception as exc:return t,None,str(exc)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(6,workers))) as pool:
            # Bounded submission prevents thousands of queued requests after an upstream restriction.
            for start in range(0,len(pending),25):
                if abort.is_set():break
                for t,obj,error in pool.map(obtain,pending[start:start+25]):
                    if error:
                        failures.append({'train':t['station_train_code'],'error':error});consecutive+=1
                        if consecutive>=8:abort.set()
                    else:consecutive=0
                meta=assemble(date,json.loads(json.dumps(stations)),trains,complete,failures)
                save(DATA/'sync-progress.json',{'state':'syncing','pid':os.getpid(),'date':date,'total':len(trains),'completed':meta['completedTrainCount'],'failed':len(failures)})
                print(f"Stops {meta['completedTrainCount']}/{len(trains)} | mapped {meta['mappedStationCount']} | errors {len(failures)}",flush=True)
    finally:
        meta=assemble(date,json.loads(json.dumps(stations)),trains,complete,failures)
        save(DATA/'sync-progress.json',{'state':'complete' if meta['coverageComplete'] else 'partial','date':date,'total':len(trains),'completed':meta['completedTrainCount'],'failed':len(failures),'message':'数据同步完成' if meta['coverageComplete'] else '数据未完整，可再次同步续传'})
    return meta

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--date',default=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat());parser.add_argument('--workers',type=int,default=3);parser.add_argument('--limit',type=int);parser.add_argument('--repair',action='store_true')
    args=parser.parse_args()
    try:instance=acquire_lock()
    except RuntimeError as exc:print(str(exc),flush=True);raise SystemExit(2)
    try:print(json.dumps(repair(args.date,args.workers) if args.repair else run(args.date,args.workers,args.limit),ensure_ascii=True),flush=True)
    except Exception as exc:
        try:progress=json.loads((DATA/'sync-progress.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):progress={}
        progress.update({'state':'error','date':args.date,'message':'本地数据文件被占用，保存失败；已保留下载缓存，可继续同步。' if isinstance(exc,PermissionError) else str(exc)})
        save(DATA/'sync-progress.json',progress)
        print('Sync failed: '+str(exc),flush=True);raise SystemExit(1)
    finally:instance.close()
