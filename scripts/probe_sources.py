import urllib.request, urllib.parse, json, re, concurrent.futures
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def probe(item):
    name, url = item
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.12306.cn/'})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        text = raw.decode('utf-8')
        if name == 'czxx-js':
            (ROOT / 'data' / 'probe-czxx.js').write_text(text, encoding='utf-8')
            snippets = [text[max(0,m.start()-100):m.end()+250] for m in re.finditer(r'czxx/query|train_start_date|randCode',text)][:12]
            return {'name':name,'size':len(raw),'snippets':snippets}
        try:
            obj=json.loads(text)
            (ROOT / 'data' / ('probe-'+name+'.json')).write_text(text,encoding='utf-8')
            if isinstance(obj,dict):
                return {'name':name,'size':len(raw),'keys':list(obj),'sample':str(obj)[:900]}
            return {'name':name,'size':len(raw),'sample':str(obj)[:900]}
        except ValueError:
            return {'name':name,'size':len(raw),'sample':text[:400]}
    except Exception as e:
        return {'name':name,'error':str(e)}

items=[('czxx-js','https://kyfw.12306.cn/otn/resources/merged/czxxcx_js.js'),
 ('train-G','https://search.12306.cn/search/v1/train/search?keyword=G&date=20261006'),
 ('train-G1','https://search.12306.cn/search/v1/train/search?keyword=G1&date=20261006'),
 ('train-D','https://search.12306.cn/search/v1/train/search?keyword=D&date=20261006'),
 ('github-tree','https://api.github.com/repos/listenzcc/China-rail-way-stations-data/git/trees/main?recursive=1'),
 ('github-sim','https://api.github.com/repos/linroger/china-hsr-simulation/git/trees/main?recursive=1')]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    for result in ex.map(probe,items): print(json.dumps(result,ensure_ascii=True))
