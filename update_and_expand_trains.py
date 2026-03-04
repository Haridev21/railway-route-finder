"""
UPDATE & EXPAND TRAINS
======================
Does 3 things in one script:

  1. RE-SCRAPE existing 3,602 trains  — updates changed schedules, fixes old data
  2. DISCOVER new trains              — scans number ranges 10000-79999
  3. ADD new trains to graph          — builds new edges and merges into graph

HOW TO RUN:
    python update_and_expand_trains.py

    You will be asked what to do:
      [1] Update existing trains only      (~90 mins)
      [2] Discover + add new trains only   (~3-4 hours)
      [3] Full refresh — both              (~5 hours)

OUTPUT:
    train_schedules.json       — updated
    graph_adjacency_list.json  — expanded with new trains
    new_trains_found.json      — list of newly discovered trains

After this, re-run step2_enrich_graph.py and step4_add_coach_info.py
"""

import json, time, os, re, requests
from bs4 import BeautifulSoup
from collections import defaultdict

SCHEDULES_FILE = "train_schedules.json"
GRAPH_FILE     = "graph_adjacency_list.json"
NEW_TRAINS_FILE= "new_trains_found.json"
DELAY          = 1.2
SAVE_EVERY     = 100

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})

# Train number ranges to scan for new trains
# Format: (start, end, description, priority)
SCAN_RANGES = [
    (10000, 22999, "Express/Mail trains (already have most)",     "update"),
    (23000, 29999, "New Express trains (may have new ones)",      "new"),
    (50000, 59999, "Passenger trains (connect small stations)",   "new"),
    (60000, 69999, "DEMU/Passenger South India",                  "new"),
    (70000, 79999, "DEMU trains",                                 "new"),
]


# ── Scraper ───────────────────────────────────────────────────────────────────

def fetch_schedule(train_no: str) -> dict:
    """Fetch schedule for one train. Returns dict or {} on failure."""
    url = f"https://www.trainspnrstatus.com/train-schedule/{train_no}"
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")

    # Must have a proper title (not generic homepage)
    title_tag = soup.find("title")
    if not title_tag:
        return {}
    title_text = title_tag.get_text(strip=True)
    if "eRail" in title_text or train_no not in title_text:
        return {}

    # Extract train name
    train_name = re.sub(r"^\d+\s*", "", title_text)
    train_name = re.sub(r"\s*Train Time Table.*", "", train_name, flags=re.I).strip()

    result = {
        "train_no":    train_no,
        "train_name":  train_name,
        "running_days":[1,1,1,1,1,1,1],
        "stations":    [],
        "scraped_at":  time.strftime("%Y-%m-%d"),   # NEW: track when scraped
    }

    # Find schedule table
    table = None
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in tbl.find_all("th")]
        if any("station" in h for h in headers):
            table = tbl
            break
    if not table:
        return {}

    for row in table.find_all("tr")[1:]:
        cols = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if len(cols) < 3:
            continue

        raw_station = cols[1] if len(cols) > 1 else ""
        raw_time    = cols[2] if len(cols) > 2 else ""
        raw_info    = cols[3] if len(cols) > 3 else ""

        station_name = re.sub(r"\(.*?\)", "", raw_station).strip()
        code_match   = re.search(r"\(\s*([A-Z]+)\s*\)", raw_station)
        station_code = code_match.group(1) if code_match else ""

        times = re.findall(r"\d{1,2}:\d{2}", raw_time)
        if not times:
            arrival = departure = "--"
        elif len(times) == 1:
            arrival = departure = times[0].zfill(5)
        else:
            arrival   = times[0].zfill(5)
            departure = times[1].zfill(5)

        day_m  = re.search(r"Day\s*(\d)", raw_info, re.I)
        day    = int(day_m.group(1)) if day_m else 1
        dist_m = re.search(r"(\d+)\s*Km", raw_info, re.I)
        dist   = float(dist_m.group(1)) if dist_m else 0.0

        runs_text = re.sub(r".*Day\s*\d", "", raw_info, flags=re.I).strip()
        if "daily" in runs_text.lower() or not runs_text:
            running = [1,1,1,1,1,1,1]
        else:
            DAY_ABBR = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            running  = [0]*7
            for i, d in enumerate(DAY_ABBR):
                if d.lower() in runs_text.lower():
                    running[i] = 1
            if sum(running) == 0:
                running = [1,1,1,1,1,1,1]

        if not result["stations"]:
            result["running_days"] = running

        if station_name:
            result["stations"].append({
                "station":      station_name,
                "station_code": station_code,
                "arrival":      arrival,
                "departure":    departure,
                "day":          day,
                "distance_km":  dist,
            })

    if len(result["stations"]) < 2:
        return {}

    return result


# ── Graph builder ─────────────────────────────────────────────────────────────

def add_train_to_graph(graph, train_no, schedule):
    """Add edges for a train to the graph. Returns count of new edges added."""
    stations = schedule.get("stations", [])
    added = 0
    for i in range(len(stations) - 1):
        src  = stations[i]["station"]
        dst  = stations[i+1]["station"]
        dist = stations[i+1]["distance_km"] - stations[i]["distance_km"]
        if dist < 0:
            dist = abs(dist)

        if src not in graph:
            graph[src] = []

        # Check if edge already exists (same train)
        exists = any(e["to"] == dst and e["train"] == train_no for e in graph[src])
        if not exists:
            graph[src].append({"to": dst, "train": train_no, "weight": round(dist, 1)})
            added += 1
    return added


# ── Phase 1: Update existing trains ──────────────────────────────────────────

def update_existing_trains(schedules, graph):
    trains = sorted([t for t, v in schedules.items()
                     if not v.get("error") and v.get("stations")])
    total  = len(trains)
    updated = 0
    failed  = 0
    new_edges = 0

    print(f"\nUpdating {total} existing trains...")
    print(f"ETA: ~{total * DELAY / 60:.0f} mins\n")

    for i, train_no in enumerate(trains, 1):
        print(f"[{i}/{total}] Train {train_no}...", end=" ", flush=True)
        data = fetch_schedule(train_no)

        if data and data.get("stations"):
            old_stops = len(schedules[train_no].get("stations", []))
            new_stops = len(data["stations"])
            schedules[train_no] = data
            new_edges += add_train_to_graph(graph, train_no, data)
            diff = new_stops - old_stops
            diff_str = f"(+{diff} stops)" if diff > 0 else f"({diff} stops)" if diff < 0 else ""
            print(f"✓ {new_stops} stops {diff_str}")
            updated += 1
        else:
            print("✗ (keeping old data)")
            failed += 1

        if i % SAVE_EVERY == 0:
            _save(schedules, graph)
            print(f"\n  ── Saved. Updated: {updated}, Failed: {failed} ──\n")

        time.sleep(DELAY)

    return updated, failed, new_edges


# ── Phase 2: Discover new trains ──────────────────────────────────────────────

def discover_new_trains(schedules, graph, existing_trains):
    new_found   = []
    new_edges   = 0
    checked     = 0

    # Build list of train numbers to check
    to_check = []
    for start, end, desc, kind in SCAN_RANGES:
        if kind == "update":
            continue  # skip — handled in phase 1
        for n in range(start, end + 1):
            t = str(n)
            if t not in existing_trains:
                to_check.append(t)

    print(f"\nScanning {len(to_check)} potential new train numbers...")
    print(f"ETA: ~{len(to_check) * DELAY / 60:.0f} mins (~{len(to_check) * DELAY / 3600:.1f} hrs)\n")

    total = len(to_check)
    for i, train_no in enumerate(to_check, 1):
        pct = i / total * 100
        print(f"[{i}/{total} | {pct:.1f}%] Train {train_no}...", end=" ", flush=True)
        checked += 1

        data = fetch_schedule(train_no)

        if data and data.get("stations"):
            schedules[train_no] = data
            edges = add_train_to_graph(graph, train_no, data)
            new_edges  += edges
            new_found.append(train_no)
            print(f"NEW! {len(data['stations'])} stops — {data.get('train_name','')[:35]}")
        else:
            schedules[train_no] = {"train_no": train_no, "error": True, "stations": []}
            print("✗")

        if i % SAVE_EVERY == 0:
            _save(schedules, graph)
            with open(NEW_TRAINS_FILE, "w") as f:
                json.dump(new_found, f)
            print(f"\n  ── Saved. New trains found: {len(new_found)}, New edges: {new_edges} ──\n")

        time.sleep(DELAY)

    return new_found, new_edges


def _save(schedules, graph):
    with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f, ensure_ascii=False)
    with open(GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  INDIAN RAILWAY — Update & Expand Train Database")
    print("=" * 60)

    print(f"\nLoading {SCHEDULES_FILE}...")
    with open(SCHEDULES_FILE, encoding="utf-8") as f:
        schedules = json.load(f)

    print(f"Loading {GRAPH_FILE}...")
    with open(GRAPH_FILE, encoding="utf-8") as f:
        graph = json.load(f)

    existing = set(schedules.keys())
    valid    = sum(1 for v in schedules.values() if not v.get("error") and v.get("stations"))

    print(f"\nCurrent status:")
    print(f"  Trains in schedules : {len(existing)}")
    print(f"  Valid trains        : {valid}")
    print(f"  Stations in graph   : {len(graph)}")

    total_edges = sum(len(v) for v in graph.values())
    print(f"  Edges in graph      : {total_edges}")

    print(f"\nWhat would you like to do?")
    print(f"  [1] Update existing {valid} trains only        (~{valid * DELAY / 60:.0f} mins)")
    print(f"  [2] Discover & add new trains only          (~3-4 hours)")
    print(f"  [3] Full refresh — update + add new         (~5 hours)")
    print(f"  [4] Quick scan — new trains only (23000-29999)  (~30 mins)")

    choice = input("\nEnter choice (1/2/3/4): ").strip()

    if choice == "1":
        u, f, e = update_existing_trains(schedules, graph)
        _save(schedules, graph)
        print(f"\n✅ Done! Updated: {u}, Failed: {f}, New edges: {e}")
        print("Now re-run: step2_enrich_graph.py  then  step4_add_coach_info.py")

    elif choice == "2":
        new_found, new_edges = discover_new_trains(schedules, graph, existing)
        _save(schedules, graph)
        with open(NEW_TRAINS_FILE, "w") as f:
            json.dump(new_found, f, indent=2)
        print(f"\n✅ Done! New trains found: {len(new_found)}, New edges: {new_edges}")
        print(f"New train list saved: {NEW_TRAINS_FILE}")
        print("Now re-run: step2_enrich_graph.py  then  step4_add_coach_info.py")

    elif choice == "3":
        print("\n--- Phase 1: Updating existing trains ---")
        u, f, e1 = update_existing_trains(schedules, graph)
        print(f"\n--- Phase 2: Discovering new trains ---")
        new_found, e2 = discover_new_trains(schedules, graph, set(schedules.keys()))
        _save(schedules, graph)
        with open(NEW_TRAINS_FILE, "w") as nf:
            json.dump(new_found, nf, indent=2)
        print(f"\n✅ Full refresh complete!")
        print(f"   Updated trains  : {u}")
        print(f"   New trains found: {len(new_found)}")
        print(f"   Total new edges : {e1 + e2}")
        print(f"   Stations in graph: {len(graph)}")
        print("Now re-run: step2_enrich_graph.py  then  step4_add_coach_info.py")

    elif choice == "4":
        # Quick scan — just 23000-29999 range
        to_check = [str(n) for n in range(23000, 30000) if str(n) not in existing]
        print(f"\nQuick scan: {len(to_check)} trains in range 23000-29999")
        print(f"ETA: ~{len(to_check) * DELAY / 60:.0f} mins\n")
        new_found = []
        new_edges = 0
        for i, train_no in enumerate(to_check, 1):
            print(f"[{i}/{len(to_check)}] {train_no}...", end=" ", flush=True)
            data = fetch_schedule(train_no)
            if data and data.get("stations"):
                schedules[train_no] = data
                new_edges += add_train_to_graph(graph, train_no, data)
                new_found.append(train_no)
                print(f"NEW! {data.get('train_name','')[:40]}")
            else:
                schedules[train_no] = {"train_no": train_no, "error": True, "stations": []}
                print("✗")
            if i % SAVE_EVERY == 0:
                _save(schedules, graph)
            time.sleep(DELAY)
        _save(schedules, graph)
        print(f"\n✅ Done! New trains: {len(new_found)}, New edges: {new_edges}")
        print("Now re-run: step2_enrich_graph.py  then  step4_add_coach_info.py")

    else:
        print("Invalid choice.")


if __name__ == "__main__":
    main()