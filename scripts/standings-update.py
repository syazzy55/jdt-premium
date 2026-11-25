import os,json,urllib.request
from pathlib import Path
from datetime import datetime,timezone
p=Path("www/standings.json")
data=json.loads(p.read_text()) if p.exists() else {}
def get(path):
    req=urllib.request.Request("https://api.sportsapi.app/v2"+path,headers={"Authorization":"Bearer "+os.environ["SPORTSAPI_KEY"],"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)
success=0
for league,name in [(204502,"Liga Super"),(195890,"ACLE"),(860531,"Shopee Cup")]:
    try:
        seasons=get(f"/leagues/{league}/seasons")["data"]
        season=next(s for s in seasons if s.get("startYear")==2026 and s.get("endYear")==2027)
        result=get(f"/leagues/{league}/standings?season={season['id']}&group=all")
        groups=result["data"]
        if not groups: raise ValueError("Empty standings")
        data[name]={"season":season["name"],"groups":groups,"updated":datetime.now(timezone.utc).isoformat()}
        success+=1
        print(name,"OK",len(groups))
    except Exception as e:
        print(name,type(e).__name__,str(e))
if not success: raise RuntimeError("No standings fetched")
p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
