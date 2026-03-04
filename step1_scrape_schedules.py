

import json, time, os, re
import requests
from bs4 import BeautifulSoup


GRAPH_FILE    = "graph_adjacency_list.json"
OUTPUT_FILE   = "train_schedules.json"
DELAY_SECONDS = 1.2
SAVE_EVERY    = 50


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
})

DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_running_days(text: str) -> list:

    text = text.strip().lower()
    if not text or "daily" in text:
        return [1,1,1,1,1,1,1]

    days = [0,0,0,0,0,0,0]

    if "except" in text:
        days = [1,1,1,1,1,1,1]
        for i, abbr in enumerate(DAY_ABBR):
            if abbr.lower() in text:
                days[i] = 0
        return days

    for i, abbr in enumerate(DAY_ABBR):
        if abbr.lower() in text:
            days[i] = 1

    return days if sum(days) > 0 else [1,1,1,1,1,1,1]


def parse_time(text: str) -> str:
    """Extract HH:MM from text. Returns '--' if not found."""
    text = text.strip()
   
    m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if m:
        t = m.group(1)
        return t if len(t) == 5 else "0" + t
    return "--"


def get_train_schedule(train_no: str) -> dict:
    url = f"https://www.trainspnrstatus.com/train-schedule/{train_no}"
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return {}
    except Exception as e:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")

    result = {
        "train_no":     train_no,
        "train_name":   "",
        "running_days": [1,1,1,1,1,1,1],
        "stations":     []
    }

   
    title = soup.find("title")
    if title:
       
        t = title.get_text(strip=True)
       
        t = re.sub(r"^\d+\s*", "", t)
        t = re.sub(r"\s*Train Time Table.*", "", t, flags=re.I)
        result["train_name"] = t.strip()


    table = None
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in tbl.find_all("th")]
        if any("station" in h for h in headers) and any("arr" in h or "dep" in h for h in headers):
            table = tbl
            break

    if not table:
        return result  

    rows = table.find_all("tr")

    for row in rows[1:]:  # skip header row
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
        if len(times) == 0:
            arrival   = "--"
            departure = "--"
        elif len(times) == 1:

            arrival   = times[0] if len(times[0]) == 5 else "0" + times[0]
            departure = arrival
        else:
            arrival   = times[0] if len(times[0]) == 5 else "0" + times[0]
            departure = times[1] if len(times[1]) == 5 else "0" + times[1]


        day_match  = re.search(r"Day\s*(\d)", raw_info, re.I)
        day        = int(day_match.group(1)) if day_match else 1

        dist_match = re.search(r"(\d+)\s*Km", raw_info, re.I)
        distance   = float(dist_match.group(1)) if dist_match else 0.0


        runs_text  = re.sub(r".*Day\s*\d", "", raw_info, flags=re.I).strip()
        running    = parse_running_days(runs_text)

        
        if not result["stations"]:
            result["running_days"] = running

        if station_name:
            result["stations"].append({
                "station":      station_name,
                "station_code": station_code,
                "arrival":      arrival,
                "departure":    departure,
                "day":          day,
                "distance_km":  distance
            })

    return result


def main():
    print(f"Loading {GRAPH_FILE}...")
    with open(GRAPH_FILE, encoding="utf-8") as f:
        graph = json.load(f)

    all_trains = set()
    for edges in graph.values():
        for edge in edges:
            all_trains.add(edge["train"])
    print(f"Unique trains: {len(all_trains)} | Stations: {len(graph)}\n")

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            schedules = json.load(f)
        already_done = {k for k, v in schedules.items() if len(v.get("stations", [])) > 0}
        print(f"Resuming — {len(already_done)} trains already have data.\n")
    else:
        schedules = {}
        already_done = set()

    remaining = sorted(all_trains - already_done)
    total     = len(all_trains)
    eta       = len(remaining) * DELAY_SECONDS / 60
    print(f"To fetch : {len(remaining)} trains")
    print(f"ETA      : ~{eta:.0f} mins (~{eta/60:.1f} hours)\n")

    for i, train_no in enumerate(remaining, 1):
        done_so_far = len(already_done) + i - 1
        pct = done_so_far / total * 100
        print(f"[{done_so_far+1}/{total} | {pct:.1f}%] Train {train_no}...", end=" ", flush=True)

        data = get_train_schedule(train_no)

        if data and len(data.get("stations", [])) > 0:
            schedules[train_no] = data
            print(f"✓  {len(data['stations'])} stops — {data.get('train_name','')[:45]}")
        else:
            schedules[train_no] = {"train_no": train_no, "error": True, "stations": []}
            print("✗  (no data)")

        if i % SAVE_EVERY == 0:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(schedules, f, ensure_ascii=False)
            ok = sum(1 for v in schedules.values() if len(v.get("stations", [])) > 0)
            print(f"\n  ── Saved: {ok}/{total} trains ({ok/total*100:.1f}%) ──\n")

        time.sleep(DELAY_SECONDS)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2, ensure_ascii=False)

    ok = sum(1 for v in schedules.values() if len(v.get("stations", [])) > 0)
    print(f"\n✅ Done! {ok}/{total} trains fetched successfully.")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
