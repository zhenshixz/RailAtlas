"""Local/LAN server with public 12306 queries and read-only cached map data."""
import argparse, datetime, gzip, ipaddress, json, mimetypes, os, re, socket, subprocess, sys, threading, urllib.parse, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from sync_data import STOPS_URL, SEARCH_URL, fetch_json, save
from auto_repair import supervise

job=None
job_lock=threading.Lock()
query_slots=threading.BoundedSemaphore(3)
response_cache={}
repair_stop=threading.Event()

def launch_sync(date,repair=False):
    global job
    with job_lock:
        if job and job.poll() is None:return None
        statefile=ROOT/'data'/'sync-progress.json'
        try:state=json.loads(statefile.read_text(encoding='utf-8'))
        except (OSError,ValueError):state={}
        if state.get('state') in ('discovering','syncing','repairing') and state.get('pid'):
            try:os.kill(state['pid'],0);return None
            except OSError:pass
        logfile=(ROOT/'data'/'sync.log').open('a',encoding='utf-8')
        command=[sys.executable,'-u',str(ROOT/'scripts'/'sync_data.py'),'--date',date,'--workers','2' if repair else '3']
        if repair:command.append('--repair')
        try:job=subprocess.Popen(command,cwd=str(ROOT),stdout=logfile,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        finally:logfile.close()
        return job
def valid_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('日期格式应为 YYYY-MM-DD')
    return datetime.date.fromisoformat(value).isoformat()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)
    def json(self,obj,status=200):
        raw=json.dumps(obj,ensure_ascii=False).encode('utf-8')
        compressed=len(raw)>16384 and 'gzip' in self.headers.get('Accept-Encoding','')
        if compressed:raw=gzip.compress(raw,compresslevel=1)
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        if compressed:self.send_header('Content-Encoding','gzip');self.send_header('Vary','Accept-Encoding')
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        parsed=urllib.parse.urlsplit(self.path);params=urllib.parse.parse_qs(parsed.query)
        def param(name,default=''):return params.get(name,[default])[0]
        path=parsed.path
        if path in ('/api/atlas','/api/china','/api/rails','/api/progress'):
            files={'/api/atlas':'atlas.json','/api/china':'china.geojson','/api/rails':'rails.geojson','/api/progress':'sync-progress.json'}
            p=ROOT/'data'/files[path]
            if not p.exists():return self.json({'state':'idle'} if path=='/api/progress' else {'error':'数据尚未准备完成，请运行数据同步。'},200 if path=='/api/progress' else 503)
            try:
                data=json.loads(p.read_text(encoding='utf-8'))
                if path=='/api/progress':
                    try:data['repair']=json.loads((ROOT/'data'/'repair-status.json').read_text(encoding='utf-8'))
                    except (OSError,ValueError):data['repair']={'enabled':True,'state':'waiting'}
                return self.json(data)
            except (OSError,ValueError):return self.json({'error':'数据写入中，请稍后重试'},503)
        if path=='/api/health':return self.json({'ok':True,'name':'RailAtlas'})
        if path.startswith('/api/'):
            try:
                if path=='/api/train/search':
                    keyword=param('keyword').upper();date=valid_date(param('date'))
                    if not re.fullmatch('[GDC][0-9]{1,4}',keyword):raise ValueError('请输入 G/D/C 字头车次，例如 G1')
                    url=SEARCH_URL+'?'+urllib.parse.urlencode({'keyword':keyword,'date':date.replace('-','')})
                elif path=='/api/train/stops':
                    number=param('id');date=valid_date(param('date'))
                    if not re.fullmatch('[A-Za-z0-9]{6,24}',number):raise ValueError('无效的车次内部编号')
                    cached=ROOT/'data'/'raw'/date/'stops'/(number+'.json')
                    if cached.exists():return self.json({'source':'12306-cache','date':date,'result':json.loads(cached.read_text(encoding='utf-8'))})
                    url=STOPS_URL+'?'+urllib.parse.urlencode({'leftTicketDTO.train_no':number,'leftTicketDTO.train_date':date,'rand_code':''})
                else:return self.json({'error':'接口不存在'},404)
                if not query_slots.acquire(blocking=False):return self.json({'error':'正在查询，请稍后再试'},429)
                try:
                    import time
                    hit=response_cache.get(url)
                    if hit and time.monotonic()-hit[0]<300:obj=hit[1]
                    else:
                        obj=fetch_json(url);response_cache[url]=(time.monotonic(),obj)
                        if len(response_cache)>200:response_cache.pop(next(iter(response_cache)))
                    return self.json({'source':'12306','date':date,'result':obj})
                finally:query_slots.release()
            except ValueError as exc:return self.json({'error':str(exc)},400)
            except Exception:return self.json({'error':'12306 官方接口暂时不可用或要求验证。请稍后重试，或前往官网查询。'},502)
        if not (ROOT/'dist'/'index.html').exists():
            self.send_error(503,'Frontend not built. Run npm run build.');return
        if path=='/' or not Path(path).suffix:self.path='/index.html'
        return super().do_GET()
    def do_POST(self):
        global job
        if self.path!='/api/sync':return self.json({'error':'接口不存在'},404)
        # Only the machine owner can start a network/data-writing job; LAN visitors can browse.
        if not ipaddress.ip_address(self.client_address[0]).is_loopback:return self.json({'error':'请在运行服务器的电脑上启动数据同步'},403)
        origin=self.headers.get('Origin');host=self.headers.get('Host','')
        if origin and urllib.parse.urlsplit(origin).netloc!=host:return self.json({'error':'请求来源不匹配'},403)
        if self.headers.get('X-RailAtlas-Action')!='sync':return self.json({'error':'请求缺少操作标识'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<1024:raise ValueError('请求格式无效')
            data=json.loads(self.rfile.read(length));date=valid_date(data.get('date',''))
            if not launch_sync(date):return self.json({'error':'数据同步或自动补齐正在进行，请等待完成'},409)
            return self.json({'ok':True,'message':'已启动同步，支持断点续传'})
        except (ValueError,TypeError) as exc:return self.json({'error':str(exc)},400)
        except Exception:return self.json({'error':'无法启动数据同步，请检查 Python 环境'},500)

def addresses(port):
    result={'127.0.0.1'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):result.add(info[4][0])
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:sock.connect(('192.0.2.1',80));result.add(sock.getsockname()[0])
        finally:sock.close()
    except OSError:pass
    return [f'http://{ip}:{port}' for ip in sorted(result) if not ip.startswith('169.254.') and ipaddress.ip_address(ip) not in ipaddress.ip_network('198.18.0.0/15')]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8790);args=parser.parse_args()
    try:
        srv=ThreadingHTTPServer(('0.0.0.0',args.port),Handler)
        print('RailAtlas is running. Local / LAN URLs:',flush=True)
        for address in addresses(args.port):print('  '+address,flush=True)
        print('Keep this window open. Ctrl+C stops the server.',flush=True)
        threading.Thread(target=supervise,args=(repair_stop,launch_sync),daemon=True,name='official-data-repair').start()
        srv.serve_forever()
    except KeyboardInterrupt:pass
    except OSError as exc:print('Startup failed: '+str(exc),file=sys.stderr);sys.exit(1)
    finally:repair_stop.set()
