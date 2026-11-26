
import os
import json
import urllib.request
import urllib.error
import time
from email.utils import parsedate_to_datetime
from datetime import timezone
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

TEAM_ID = 210860
API_KEY = os.environ["SPORTSAPI_KEY"]
BASE = "https://api.sportsapi.app/v2"
FILE = Path("www/matches.json")
TZ = ZoneInfo("Asia/Kuala_Lumpur")

NAMES = {
    250820: "Ratchaburi FC",
    250817: "Cong An Hanoi",
    229081: "Kuala Lumpur City",
    168292: "Penang FC",
    204621: "Kelantan Red Warrior",
    252092: "Brunei DPMM",
    263786: "Negeri Sembilan",
    204623: "Terengganu FC",
    218411: "Star City"
}

LEAGUES = {
    195890: "ACLE",
    204502: "Liga Super",
    860531: "Shopee Cup",
    278820: "Piala FA"
}

def fetch(kind):
    matches = []
    for page in range(51):
        url = (
            f"{BASE}/teams/{TEAM_ID}/fixtures"
            f"?type={kind}&page={page}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Accept": "application/json"
            }
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                delay = 30 * (2 ** attempt)
                header = exc.headers.get("Retry-After")
                if header:
                    try:
                        delay = max(delay, int(header))
                    except ValueError:
                        try:
                            delay = max(delay, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
                if delay > 120:
                    print("API cooldown exceeds 120 seconds; preserving cached matches.")
                    raise
                print(f"API rate limited; retrying in {delay:.0f}s")
                time.sleep(delay)
        time.sleep(2)

        matches.extend(payload["data"])

        if not payload.get("meta", {}).get("hasNextPage"):
            return matches

    raise RuntimeError("Pagination limit exceeded")

def convert(match):
    home = match["home"]["id"] == TEAM_ID
    opponent = match["away"] if home else match["home"]

    dt = datetime.fromisoformat(
        match["startTime"].replace("Z", "+00:00")
    ).astimezone(TZ)

    overrides = {1047302: ("2026-12-10", "20:00"), 1284367: ("2026-12-17", "")}
    league = match["league"]

    item = {
        "id": match["id"],
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M"),
        "opponent": NAMES.get(
            opponent["id"], opponent["name"]
        ),
        "venue": "Home" if home else "Away",
        "competition": LEAGUES.get(
            league["id"], league["name"]
        ),
        "logo": opponent.get("image"),
        "status": match["status"]["type"]
    }

    if match["id"] in overrides:
        item["date"], item["time"] = overrides[match["id"]]

    if item["status"] in ("finished", "inprogress", "live"):
        hs = (match.get("homeScore") or {}).get("current")
        aws = (match.get("awayScore") or {}).get("current")
        if hs is None or aws is None:
            if item["status"] == "finished":
                raise ValueError("Missing final score")
            return item

        item["jdtScore"] = hs if home else aws
        item["opponentScore"] = aws if home else hs

    return item

def key(item):
    return (
        item["date"],
        item["opponent"],
        item["competition"]
    )

data = json.loads(FILE.read_text(encoding="utf-8"))

upcoming = fetch("upcoming")
recent = fetch("recent")

if not upcoming and not recent:
    raise RuntimeError("Empty API response. Update cancelled.")

fixtures = {
    key(x): x for x in data.get("fixtures", [])
}

results = {
    key(x): x for x in data.get("results", [])
}

for match in upcoming + recent:
    item = convert(match)
    k = key(item)
    status = item["status"]
    for old_key, old in list(fixtures.items()):
        if old_key != k and old.get("id") == item["id"]:
            fixtures.pop(old_key)

    if status == "finished":
        results[k] = item
        fixtures.pop(k, None)

    elif status in ("notstarted", "inprogress", "live"):
        if k not in results:
            fixtures[k] = item

    elif status in ("postponed", "canceled", "cancelled"):
        old = fixtures.get(k)
        if old and old.get("status") != "notstarted":
            fixtures.pop(k, None)

data["fixtures"] = sorted(
    fixtures.values(),
    key=lambda x: (x["date"], x.get("time", ""))
)

data["results"] = sorted(
    results.values(),
    key=lambda x: x["date"],
    reverse=True
)

data["updated"] = datetime.now(TZ).strftime("%Y-%m-%d")
data["updatedAt"] = datetime.now(TZ).isoformat()

data["sources"] = list(dict.fromkeys(
    data.get("sources", []) + [BASE]
))

temp = FILE.with_suffix(".tmp")
temp.write_text(
    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8"
)
temp.replace(FILE)

print("SportsAPI Smart Update successful!")
print("Upcoming API matches:", len(upcoming))
print("Recent API matches:", len(recent))
print("Saved fixtures:", len(data["fixtures"]))
print("Saved results:", len(data["results"]))
