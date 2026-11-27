import json, os, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta


# Shared persistent API cooldown (UTC epoch seconds).
from email.utils import parsedate_to_datetime
cooldown_file = Path("www/api-cooldown.json")
def record_cooldown(exc):
    delay = 3600
    header = exc.headers.get("Retry-After")
    if header:
        try:
            delay = max(60, int(header))
        except ValueError:
            try:
                delay = max(60, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    until = int(time.time() + delay + 1)
    cooldown_file.write_text(json.dumps({"until": until}) + "\n")
    print("::warning::SportsAPI rate limited; deferred until " + datetime.fromtimestamp(until, timezone.utc).isoformat())

def cooldown_active():
    if not cooldown_file.exists():
        return False
    raw = cooldown_file.read_text().strip()
    if raw.endswith("\\n"):
        raw = raw[:-2].rstrip()
    try:
        return json.loads(raw)["until"] > time.time()
    except (ValueError, KeyError, TypeError):
        print("::warning::Invalid cooldown file; API requests deferred for safety.")
        return True

if cooldown_active():
    print("::notice::SportsAPI cooldown active; cached data retained.")
    raise SystemExit(0)

path=Path('www/details.json')
try: cache=json.loads(path.read_text())
except FileNotFoundError: cache={}
data=json.loads(Path('www/matches.json').read_text())
now=datetime.now(timezone.utc)
key=os.environ['SPORTSAPI_KEY']
matches=[m for m in data['results'][:5]+data['fixtures'][:2] if m.get('id')]
print('Historical results missing fixture ID:', sum(not m.get('id') for m in data['results']))
requests=0
budget=8
rate_limited=False
for m in matches:
    if rate_limited or requests>=budget: break
    ident=str(m['id'])
    entry=cache.setdefault(ident,{})
    if m.get('status')=='finished' and all(k in entry for k in ('fixture','events','lineups','statistics','h2h')) and entry.get('finished'): continue
    for name,suffix in [('fixture',''),('events','/events'),('lineups','/lineups'),('statistics','/statistics'),('h2h','/h2h')]:
        if m.get('status')=='finished' and entry.get('finished') and entry.get(name) is not None: continue
        if requests>=budget: break
        requests+=1
        time.sleep(3)
        try:
            req=urllib.request.Request('https://api.sportsapi.app/v2/fixtures/'+ident+suffix,headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=20) as res: value=json.load(res)['data']
            if value is not None: entry[name]=value
            print(ident,name,'OK')
        except urllib.error.HTTPError as e:
            print(ident,name,e.code)
            if e.code == 429: record_cooldown(e)
            if e.code in (401,403,429):
                rate_limited=True
                break
        except (OSError,ValueError,KeyError) as e: print(ident,name,type(e).__name__)
    entry['finished']=entry.get('fixture',{}).get('status',{}).get('type')=='finished'
    entry['updated']=now.isoformat()
# Backfill older finished matches gradually, prioritizing missing lineups.
recent=sorted(data['results'],key=lambda m:(m.get('date',''),m.get('time','')),reverse=True)
attempts=0
for m in recent:
    if rate_limited or attempts>=3 or requests>=budget: break
    if not m.get('id'): continue
    ident=str(m['id'])
    entry=cache.setdefault(ident,{})
    lineup=entry.get('lineups') or {}
    if isinstance(lineup,dict) and any(p.get('rating') is not None or (p.get('statistics') or {}).get('rating') is not None for side in ('home','away') for p in (lineup.get(side) or {}).get('players',[])): continue
    try:
        last=datetime.fromisoformat(entry.get('lineupAttempt',''))
        if now-last<timedelta(hours=24): continue
    except (ValueError,TypeError): pass
    attempts+=1
    requests+=1
    time.sleep(3)
    try:
        req=urllib.request.Request('https://api.sportsapi.app/v2/fixtures/'+ident+'/lineups',headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=20) as res: value=json.load(res)['data']
        entry['lineupAttempt']=now.isoformat()
        if isinstance(value,dict) and any((value.get(side) or {}).get('players') for side in ('home','away')):
            entry['lineups']=value
            print(ident,'historical lineup OK')
        else: print(ident,'historical lineup unavailable')
    except urllib.error.HTTPError as e:
        print(ident,'historical lineup',e.code)
        if e.code == 429: record_cooldown(e)
        if e.code in (401,403,429): break
        entry['lineupAttempt']=now.isoformat()
    except (OSError,ValueError,KeyError) as e: print(ident,'historical lineup',type(e).__name__)
print('Match detail API requests:', requests, '/', budget)
tmp=path.with_suffix('.tmp')
tmp.write_text(json.dumps(cache,ensure_ascii=False,separators=(',',':')))
tmp.replace(path)
