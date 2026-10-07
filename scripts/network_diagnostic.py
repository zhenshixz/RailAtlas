import json,urllib.request,urllib.parse
import requests
url='https://search.12306.cn/search/v1/train/search?keyword=C&date=20261006'
def clean(proxies):
    return {k:{'host':urllib.parse.urlsplit(v).hostname,'port':urllib.parse.urlsplit(v).port,'scheme':urllib.parse.urlsplit(v).scheme} for k,v in proxies.items() if k!='no'}
print('urllib proxies',clean(urllib.request.getproxies()),flush=True)
print('requests proxies',clean(requests.utils.get_environ_proxies(url)),flush=True)
for name in ('urllib','requests'):
    try:
        if name=='urllib':
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.12306.cn/'})
            with urllib.request.urlopen(req,timeout=20) as r:obj=json.loads(r.read())
        else:
            r=requests.get(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.12306.cn/'},timeout=20);r.raise_for_status();obj=r.json()
        print(name,'success',len(obj.get('data',[])),flush=True)
    except Exception as exc:print(name,type(exc).__name__,str(exc)[:350],flush=True)
