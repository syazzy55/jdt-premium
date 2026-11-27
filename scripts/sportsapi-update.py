
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
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                record_cooldown(exc)
                raise SystemExit(0)
            raise
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

# Recover missing historical IDs using documented date/league endpoint.
# Bound additional requests; only attach IDs to unambiguous score/venue matches.
from urllib.parse import urlencode
league_ids = {name: ident for ident, name in LEAGUES.items()}
pending = sorted((x for x in results.values() if not x.get("id")
                  and x.get("competition") in league_ids),
                 key=lambda x: x["date"], reverse=True)
# Rotate unmatched dates so unavailable historical coverage cannot block older games.
offset = int(data.get("historyRecoveryOffset", 0))
if pending and not data.get("historyRecoveryForbidden"):
    offset %= len(pending)
    batch = (pending[offset:] + pending[:offset])[:2]
    for old in batch:
        url = BASE + "/fixtures?" + urlencode({
            "date": old["date"], "league": league_ids[old["competition"]],
            "tz": "Asia/Kuala_Lumpur"})
        try:
            time.sleep(3)
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as response:
                rows = json.load(response)["data"]
        except urllib.error.HTTPError as exc:
            print("History recovery HTTP", exc.code)
            if exc.code == 403:
                data["historyRecoveryForbidden"] = True
                print("History endpoint forbidden; automatic recovery paused until access is verified.")
                break
            if exc.code == 429:
                record_cooldown(exc)
                break
            continue
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            print("History recovery unavailable:", type(exc).__name__)
            continue
        candidates = []
        for row in rows:
            if TEAM_ID not in (row["home"]["id"], row["away"]["id"]):
                continue
            if row["status"]["type"] != "finished":
                continue
            try:
                item = convert(row)
            except (ValueError, KeyError, TypeError):
                continue
            if all(item.get(k) == old.get(k) for k in
                   ("date", "competition", "venue", "jdtScore", "opponentScore")):
                candidates.append(item)
        if len(candidates) == 1 and not any(
                x.get("id") == candidates[0]["id"] for x in results.values()):
            old["id"] = candidates[0]["id"]
            print("Historical ID recovered:", old["date"], old["id"])
        else:
            print("Historical ID not uniquely matched:", old["date"])
    data["historyRecoveryOffset"] = offset + len(batch)
if data.get("historyRecoveryForbidden"):
    print("Historical date endpoint paused; normal team fixture updates remain active.")
print("Historical results still missing ID:", sum(not x.get("id") for x in results.values()))

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
