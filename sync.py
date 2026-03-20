import json
import os
import urllib.request
import urllib.error
import base64
import time
import sys

GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
GITHUB_REPO   = os.environ["GITHUB_REPOSITORY"]
DATA_FILE     = "pool_data.json"
API_BASE      = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"

HEADERS_GH = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

# ESPN team name → pool team name mapping
# ESPN uses full official names; map them to whatever is in pool_data.json
ESPN_NAME_MAP = {
    "Duke Blue Devils": "Duke",
    "Arizona Wildcats": "Arizona",
    "Michigan Wolverines": "Michigan",
    "Florida Gators": "Florida",
    "Houston Cougars": "Houston",
    "Connecticut Huskies": "UConn",
    "Iowa State Cyclones": "Iowa State",
    "Purdue Boilermakers": "Purdue",
    "Michigan State Spartans": "Michigan State",
    "Illinois Fighting Illini": "Illinois",
    "Gonzaga Bulldogs": "Gonzaga",
    "Virginia Cavaliers": "Virginia",
    "Nebraska Cornhuskers": "Nebraska",
    "Alabama Crimson Tide": "Alabama",
    "Kansas Jayhawks": "Kansas",
    "Arkansas Razorbacks": "Arkansas",
    "Vanderbilt Commodores": "Vanderbilt",
    "St. John's Red Storm": "St. John's",
    "Texas Tech Red Raiders": "Texas Tech",
    "Wisconsin Badgers": "Wisconsin",
    "Tennessee Volunteers": "Tennessee",
    "North Carolina Tar Heels": "North Carolina",
    "Louisville Cardinals": "Louisville",
    "BYU Cougars": "BYU",
    "Kentucky Wildcats": "Kentucky",
    "Saint Mary's Gaels": "Saint Mary's",
    "Miami Hurricanes": "Miami (FL)",
    "UCLA Bruins": "UCLA",
    "Clemson Tigers": "Clemson",
    "Villanova Wildcats": "Villanova",
    "Ohio State Buckeyes": "Ohio State",
    "Georgia Bulldogs": "Georgia",
    "Utah State Aggies": "Utah State",
    "TCU Horned Frogs": "TCU",
    "Saint Louis Billikens": "Saint Louis",
    "Iowa Hawkeyes": "Iowa",
    "Santa Clara Broncos": "Santa Clara",
    "UCF Knights": "UCF",
    "Missouri Tigers": "Missouri",
    "Texas A&M Aggies": "Texas A&M",
    "NC State Wolfpack": "NC State",
    "Texas Longhorns": "Texas",
    "SMU Mustangs": "SMU",
    "Miami RedHawks": "Miami (OH)",
    "VCU Rams": "VCU",
    "South Florida Bulls": "South Florida",
    "McNeese Cowboys": "McNeese",
    "Akron Zips": "Akron",
    "Northern Iowa Panthers": "Northern Iowa",
    "High Point Panthers": "High Point",
    "California Baptist Lancers": "Cal Baptist",
    "Hofstra Pride": "Hofstra",
    "Troy Trojans": "Troy",
    "Hawaii Rainbow Warriors": "Hawaii",
    "Hawaiʻi Rainbow Warriors": "Hawaii",
    "North Dakota State Bison": "North Dakota State",
    "Penn Quakers": "Penn",
    "Pennsylvania Quakers": "Penn",
    "Wright State Raiders": "Wright State",
    "Kennesaw State Owls": "Kennesaw State",
    "Tennessee State Tigers": "Tennessee State",
    "Idaho Vandals": "Idaho",
    "Furman Paladins": "Furman",
    "Queens Royals": "Queens",
    "Siena Saints": "Siena",
    "LIU Sharks": "LIU",
    "Howard Bison": "Howard",
    "UMBC Retrievers": "UMBC",
    "Lehigh Mountain Hawks": "Lehigh",
    "Prairie View A&M Panthers": "Prairie View A&M",
}

# ── 1. Load current state from GitHub repo ───────────────────────────────────

print("Loading pool_data.json from GitHub repo...")
req = urllib.request.Request(API_BASE, headers=HEADERS_GH)
try:
    with urllib.request.urlopen(req) as resp:
        meta = json.loads(resp.read())
        content_b64 = meta["content"].replace("\n", "")
        file_sha = meta["sha"]
        state = json.loads(base64.b64decode(content_b64))
        print(f"  Loaded. Eliminated so far: {len(state.get('eliminatedTeams', []))} teams")
except urllib.error.HTTPError as e:
    print(f"ERROR loading from GitHub: HTTP {e.code} {e.read().decode()}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR loading from GitHub: {e}")
    sys.exit(1)

eliminated = state.get("eliminatedTeams", [])
all_assigned = []
for p in state.get("participants", []):
    for t in p.get("teams", []):
        if t != "Sorry" and t not in eliminated and t not in all_assigned:
            all_assigned.append(t)

if not all_assigned:
    print("No active teams left. Pool may be over.")
    sys.exit(0)

print(f"  Active teams to check: {', '.join(all_assigned)}")

# ── 2. Fetch completed NCAA Tournament games from ESPN ───────────────────────

print("\nFetching tournament results from ESPN...")

# We need to check results across multiple days since the tournament spans weeks.
# Fetch the scoreboard for a date range by iterating recent dates.
# ESPN scoreboard returns today's games by default; use dates param for past games.
# Also fetch the tournament bracket endpoint which has all rounds.

newly_eliminated = []
games_found = 0

def espn_name_to_pool(espn_name):
    """Convert ESPN team name to pool team name."""
    # Try direct map first
    if espn_name in ESPN_NAME_MAP:
        return ESPN_NAME_MAP[espn_name]
    # Try partial match against pool names
    espn_lower = espn_name.lower()
    for pool_name in all_assigned:
        if pool_name.lower() in espn_lower or espn_lower in pool_name.lower():
            return pool_name
    return None

def fetch_url(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ncaa-pool-tracker/1.0)"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

# Use ESPN's tournament bracket API — this contains ALL games across all rounds
try:
    bracket_url = "https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/tournament/0"
    data = fetch_url(bracket_url)

    # Walk through all rounds and games
    for region in data.get("bracket", {}).get("fullBracket", []):
        for round_data in region.get("rounds", []):
            for game in round_data.get("competitions", []):
                status = game.get("status", {}).get("type", {}).get("name", "")
                if status != "STATUS_FINAL":
                    continue
                games_found += 1
                competitors = game.get("competitors", [])
                for comp in competitors:
                    if comp.get("winner") is False:
                        espn_name = comp.get("team", {}).get("displayName", "")
                        pool_name = espn_name_to_pool(espn_name)
                        if pool_name and pool_name not in eliminated and pool_name not in newly_eliminated:
                            newly_eliminated.append(pool_name)
                            print(f"  Found eliminated: {pool_name} (ESPN: {espn_name})")

    print(f"  Bracket endpoint: {games_found} completed games found")

except Exception as e:
    print(f"  Bracket endpoint failed ({e}), trying scoreboard fallback...")

    # Fallback: fetch scoreboard for each date since tournament started
    # Use multiple endpoint variations to maximize coverage
    from datetime import date, timedelta
    tournament_start = date(2026, 3, 17)
    today = date.today()
    check_date = tournament_start

    while check_date <= today:
        date_str = check_date.strftime("%Y%m%d")
        # Try both with and without groups filter, and with calendartype=postseason
        urls = [
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={date_str}&limit=100",
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={date_str}&groups=100&limit=100",
        ]
        for url in urls:
            try:
                data = fetch_url(url)
                for event in data.get("events", []):
                    # Check if this is a tournament game
                    season_type = event.get("season", {}).get("type", 0)
                    name = event.get("name", "")
                    notes = event.get("competitions", [{}])[0].get("notes", [])
                    note_text = " ".join(n.get("headline", "") for n in notes).lower()
                    is_tourney = (season_type == 3 or
                                  "ncaa" in note_text or
                                  "tournament" in note_text or
                                  "first round" in note_text or
                                  "second round" in note_text or
                                  "sweet 16" in note_text or
                                  "elite eight" in note_text or
                                  "final four" in note_text or
                                  "first four" in note_text)
                    status = event.get("status", {}).get("type", {}).get("name", "")
                    if status != "STATUS_FINAL":
                        continue
                    games_found += 1
                    comp = event.get("competitions", [{}])[0]
                    for team in comp.get("competitors", []):
                        if team.get("winner") is False:
                            espn_name = team.get("team", {}).get("displayName", "")
                            pool_name = espn_name_to_pool(espn_name)
                            if pool_name and pool_name not in eliminated and pool_name not in newly_eliminated:
                                newly_eliminated.append(pool_name)
                                print(f"  Found eliminated: {pool_name} (ESPN: {espn_name})")
                            elif not pool_name and espn_name:
                                # Log unmatched names to help diagnose mapping issues
                                print(f"  Unmatched ESPN name: '{espn_name}'")
            except Exception as de:
                print(f"  Skipping {date_str} ({url[-30:]}): {de}")
        check_date += timedelta(days=1)
        time.sleep(0.2)

    print(f"  Scoreboard fallback: {games_found} completed games across all dates")

print(f"\nNewly eliminated: {newly_eliminated if newly_eliminated else 'none'}")

if not newly_eliminated:
    print("No new eliminations. Repo not updated.")
    sys.exit(0)

# ── 3. Update state ──────────────────────────────────────────────────────────

state["eliminatedTeams"] = eliminated + newly_eliminated
state["gamesPlayed"] = max(state.get("gamesPlayed", 0), games_found)
state["lastSync"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def teams_remaining(p):
    return sum(
        1 for t in p.get("teams", [])
        if t != "Sorry" and t not in state["eliminatedTeams"]
    )

if not state.get("firstEliminated"):
    for p in state["participants"]:
        if teams_remaining(p) == 0 and len(p.get("teams", [])) > 0:
            state["firstEliminated"] = p["name"]
            print(f"  {p['name']} is first eliminated!")
            break

# ── 4. Write updated pool_data.json back to GitHub repo ─────────────────────

print(f"\nWriting updated pool_data.json to repo ({len(newly_eliminated)} new elimination(s))...")
new_content = base64.b64encode(json.dumps(state, indent=2).encode()).decode()
payload = json.dumps({
    "message": f"Auto-sync: eliminate {', '.join(newly_eliminated)}",
    "content": new_content,
    "sha": file_sha
}).encode()

req = urllib.request.Request(
    API_BASE,
    data=payload,
    method="PUT",
    headers={**HEADERS_GH, "Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req) as resp:
        print("  Saved successfully.")
        print(f"  Newly eliminated: {', '.join(newly_eliminated)}")
except urllib.error.HTTPError as e:
    print(f"ERROR writing to GitHub: {e.code} {e.read().decode()}")
    sys.exit(1)

print("\nSync complete.")
