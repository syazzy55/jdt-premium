import json,re
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import requests
from bs4 import BeautifulSoup

p=Path('www/matches.json')
d=json.loads(p.read_text())
url='https://johorsoutherntigers.my/calendar/2026-27-jdt-fc-calendar-results/'
r=requests.get(url,timeout=30);r.raise_for_status()
s=BeautifulSoup(r.text,'html.parser')
aliases={'daejeon hanacitizen':'Daejeon Hana Citizen','kuala lumpur city fc':'Kuala Lumpur City','cong an hanoi fc':'Cong An Hanoi','dpmm':'Brunei DPMM','dpmm fc':'Brunei DPMM','jeonbuk hyundai motors':'Jeonbuk','fc pohang steelers':'Pohang Steelers','svay rieng fc':'Svay Rieng','kuching city fc':'Kuching City','kelantan red warrior fc':'Kelantan Red Warrior','star city fc':'Star City','negeri sembilan fc':'Negeri Sembilan','shan united fc':'Shan United'}
jdt=re.compile(r"^(?:JDT(?: FC)?|Johor Darul Ta['’]zim(?: FC)?)$",re.I)
found=[]
for tr in s.select('tr'):
    c=[x.get_text(' ',strip=True) for x in tr.find_all('td',recursive=False)]
    if len(c)<5 or not re.search(r'2026\s*/\s*27',c[4]): continue
    dt=re.search(r'(202[67]-\d\d-\d\d)(?:\s+(\d\d:\d\d))?',c[0])
    if not dt: continue
    event=re.sub(r'^(?:Charity Cup|LS\s*\d+|ACLE\s*\d+|SC\s*\d+|FAC\s*(?:(?:QF|SF)\s*)?\d+)\s+','',c[1],flags=re.I)
    sides=re.split(r'\s+vs\.?\s+',event,flags=re.I)
    if len(sides)!=2: continue
    home=bool(jdt.fullmatch(sides[0]))
    if not home and not jdt.fullmatch(sides[1]): continue
    opp=sides[1] if home else sides[0]
    opp=aliases.get(opp.lower(),opp)
    league=c[3].lower()
    comp=next((v for k,v in [('super league','Liga Super'),('fa cup','Piala FA'),('champions league elite','ACLE'),('shopee cup','Shopee Cup'),('asean club','Shopee Cup'),('malaysia cup','Piala Malaysia'),('piala sumbangsih','Piala Sumbangsih')] if k in league),None)
    if not comp: continue
    m=dict(date=dt[1],opponent=opp,competition=comp,venue='Home' if home else 'Away')
    score=re.fullmatch(r'\s*(\d+)\s*[-–]\s*(\d+)\s*',c[2])
    if score:
        a,b=map(int,score.groups());m.update(jdtScore=a if home else b,opponentScore=b if home else a)
    else:
        t=re.search(r'(\d{1,2}):(\d\d)\s*([ap]m)',c[2],re.I)
        if not t: continue
        hour=int(t[1])%12+(12 if t[3].lower()=='pm' else 0)
        # Foreign venue times are not assumed to be MYT.
        m['time']=f'{hour:02}:{t[2]}' if home or comp in ('Liga Super','Piala FA','Piala Malaysia') and opp!='Brunei DPMM' else ''
    found.append(m)
if len(found)<10: raise RuntimeError('Source layout changed; preserving existing data')
def key(m): return (m['opponent'].casefold(),m['competition'],m['venue'],m['date'])
fixtures={key(m):m for m in d['fixtures']}
results={key(m):m for m in d['results']}
for m in found:
    k=key(m)
    if 'jdtScore' in m: results[k]=m;fixtures.pop(k,None)
    elif k not in results: fixtures[k]=m
d['fixtures']=sorted(fixtures.values(),key=lambda m:m['date'])
d['results']=sorted(results.values(),key=lambda m:m['date'],reverse=True)
d['updated']=datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat()
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print('Parsed',len(found),'official records')
