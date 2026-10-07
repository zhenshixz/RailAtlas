"""Server-owned, persistent backoff for incomplete official data snapshots."""
import datetime,json,os,time
from pathlib import Path
from sync_data import acquire_lock,save

ROOT=Path(__file__).resolve().parents[1]
STATUS=ROOT/'data/repair-status.json'
DELAYS=(60,300,900,3600,10800,21600)
def retry_delay(attempt):return DELAYS[min(max(attempt-1,0),len(DELAYS)-1)]
def read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
def stamp(timestamp):return datetime.datetime.fromtimestamp(timestamp,datetime.timezone(datetime.timedelta(hours=8))).isoformat()

def supervise(stop,launch):
    state=read(STATUS)
    child=None
    atlas_path=ROOT/'data/atlas.json'
    atlas_mtime=None
    meta={}
    while not stop.is_set():
        try:
            current_mtime=atlas_path.stat().st_mtime_ns
            if current_mtime!=atlas_mtime:
                atlas=read(atlas_path)
                if atlas:
                    meta=atlas.get('meta',{})
                    atlas_mtime=current_mtime
            date=meta.get('date')
            if not date:stop.wait(15);continue
            if child and child.poll() is None:stop.wait(5);continue
            if child:
                child=None
                if not meta.get('coverageComplete'):
                    delay=retry_delay(state.get('attempt',1))
                    state.update({'state':'waiting','nextRetryTimestamp':time.time()+delay,'nextRetryAt':stamp(time.time()+delay),'failures':meta.get('failures',[]),'remaining':meta.get('discoveredTrainCount',0)-meta.get('completedTrainCount',0)})
                    save(STATUS,state)
            if meta.get('coverageComplete'):
                if state.get('state')!='complete' or state.get('date')!=date:
                    state={'enabled':True,'state':'complete','date':date,'attempt':0,'remaining':0,'nextRetryAt':None};save(STATUS,state)
                stop.wait(30);continue
            if state.get('date')!=date or state.get('state')=='complete':
                state={'enabled':True,'state':'waiting','date':date,'attempt':0,'nextRetryTimestamp':0,'nextRetryAt':None};save(STATUS,state)
            elif state.get('state')=='repairing':
                # Recover from a server shutdown during its previous repair.
                state.update({'state':'waiting','nextRetryTimestamp':time.time()+retry_delay(state.get('attempt',1)),'nextRetryAt':stamp(time.time()+retry_delay(state.get('attempt',1)))})
                save(STATUS,state)
            if time.time()<state.get('nextRetryTimestamp',0):stop.wait(10);continue
            try:
                probe=acquire_lock();probe.close()
            except RuntimeError:stop.wait(15);continue
            launched=launch(date,bool(meta.get('searchComplete')))
            if launched:
                child=launched
                state.update({'enabled':True,'state':'repairing','date':date,'attempt':state.get('attempt',0)+1,'lastAttemptAt':stamp(time.time()),'nextRetryAt':None,'nextRetryTimestamp':0})
                save(STATUS,state)
            stop.wait(5)
        except Exception as error:
            # Preserve the snapshot and keep the supervisor alive on local errors.
            print('Auto repair postponed: '+str(error),flush=True)
            stop.wait(30)
