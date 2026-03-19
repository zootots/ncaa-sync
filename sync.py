import json
import os
import urllib.request
import urllib.error
import base64
import re
import time
import sys

ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
GITHUB_REPO   = os.environ["GITHUB_REPOSITORY"]   # e.g. "yourname/ncaa-sync"
DATA_FILE     = "pool_data.json"
API_BASE      = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"

HEADERS_GH = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
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

# ── 2. Build list of active assigned teams ───────────────────────────────────

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

# ── 3. Ask Claude (with web search) for eliminated teams ─────────────────────

print("\nAsking Claude for latest tournament results...")
prompt = (
    "You are helping track a March Madness pool. Today is March 2026.\n\n"
    "The 2026 NCAA Men's Basketball Tournament is currently in progress. "
    "Using web search, find all teams that have been ELIMINATED (i.e. LOST a game) "
    "so far, including the First Four.\n\n"
    "From this list of teams still active in my pool, tell me which ones have been eliminated:\n"
    + ", ".join(all_assigned) + "\n\n"
    "IMPORTANT: Only list teams that have definitively LOST. "
    "Do NOT include teams that won or have not played. Do NOT make up results.\n\n"
    "Respond ONLY with valid JSON, no markdown, no explanation:\n"
    '{"eliminated": ["TeamA", "TeamB"], "games_found": 5, "note": "brief summary"}\n\n'
    "Team names must match exactly as given in my list above."
)

payload = json.dumps({
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 1000,
    "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    "messages": [{"role": "user", "content": prompt}]
}).encode()

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01"
    }
)
try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
except urllib.error.HTTPError as e:
    print(f"ERROR calling Anthropic API: {e.code} {e.read().decode()}")
    sys.exit(1)

# ── 4. Parse Claude's response ───────────────────────────────────────────────

raw = " ".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
raw = raw.replace("```json", "").replace("```", "").strip()
try:
    parsed = json.loads(raw)
except Exception:
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        parsed = json.loads(m.group())
    else:
        print(f"ERROR: Could not parse Claude response:\n{raw}")
        sys.exit(1)

newly_eliminated = [t for t in parsed.get("eliminated", []) if t not in eliminated]
print(f"\nClaude says: {parsed.get('note', '')}")
print(f"Games found: {parsed.get('games_found', 'unknown')}")
print(f"Newly eliminated: {newly_eliminated if newly_eliminated else 'none'}")

if not newly_eliminated:
    print("\nNo new eliminations. Repo not updated.")
    sys.exit(0)

# ── 5. Update state ──────────────────────────────────────────────────────────

state["eliminatedTeams"] = eliminated + newly_eliminated
if parsed.get("games_found"):
    state["gamesPlayed"] = max(state.get("gamesPlayed", 0), int(parsed["games_found"]))
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
            print(f"  {p['name']} is first eliminated — consolation prize!")
            break

# ── 6. Write updated pool_data.json back to GitHub repo ─────────────────────

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
