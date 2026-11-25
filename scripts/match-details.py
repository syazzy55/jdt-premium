import json, os, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

path=Path('www/details.json')
try: cache=json.loads(path.read_text())
except FileNotFoundError: cache={}
data=json.loads(Path('www/matches.json').read_text())
now=datetime.now(timezone.utc)
key=os.environ['SPORTSAPI_KEY']
matches=[m for m in data['results'][:5]+data['fixtures'][:2] if m.get('id')]
for m in matches:
    ident=str(m['id'])
    entry=cache.setdefault(ident,{})
    if m.get('status')=='finished' and all(k in entry for k in ('fixture','events','lineups','statistics','h2h')) and entry.get('finished'): continue
    for name,suffix in [('fixture',''),('events','/events'),('lineups','/lineups'),('statistics','/statistics'),('h2h','/h2h')]:
        try:
            req=urllib.request.Request('https://api.sportsapi.app/v2/fixtures/'+ident+suffix,headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=20) as res: value=json.load(res)['data']
            if value is not None: entry[name]=value
            print(ident,name,'OK')
        except urllib.error.HTTPError as e:
            print(ident,name,e.code)
            if e.code in (401,403,429): break
        except (OSError,ValueError,KeyError) as e: print(ident,name,type(e).__name__)
    entry['finished']=entry.get('fixture',{}).get('status',{}).get('type')=='finished'
    entry['updated']=now.isoformat()
tmp=path.with_suffix('.tmp')
tmp.write_text(json.dumps(cache,ensure_ascii=False,separators=(',',':')))
tmp.replace(path)
