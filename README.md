# 🚂 Railway Network Enrichment — Minor Project

## What These Scripts Do

| Script | Purpose |
|--------|---------|
| `step1_scrape_schedules.py` | Fetches timing + running days for all 3602 trains from erail.in |
| `step2_enrich_graph.py`     | Combines your graph JSON with schedule data |
| `step3_find_route.py`       | Time-aware pathfinding with waiting time calculation |

---

## Setup

```bash
pip install requests beautifulsoup4
```

Put all 3 scripts in the **same folder** as your `graph_adjacency_list.json`.

---

## Step 1 — Scrape Train Schedules

```bash
python step1_scrape_schedules.py
```

- Fetches schedules for all **3602 trains** from [erail.in](https://erail.in)
- Saves progress every 50 trains — **safe to interrupt and resume**
- Takes ~1.5–2 hours (respects rate limiting with 1.2s delay)
- Output: `train_schedules.json`

> **Tip:** Run this overnight. If it stops, just run it again — it resumes automatically.

---

## Step 2 — Enrich Your Graph

```bash
python step2_enrich_graph.py
```

Merges timing data into your graph. Each edge becomes:

```json
{
  "to": "Ratnagiri",
  "train": "10102",
  "weight": 89.0,
  "train_name": "KOKAN KANYA EXP",
  "departure_time": "06:40",
  "arrival_time": "08:14",
  "travel_minutes": 94,
  "day_offset": 0,
  "running_days": [1, 1, 1, 1, 1, 1, 1]
}
```

**`running_days`** = [Mon, Tue, Wed, Thu, Fri, Sat, Sun] where **1 = runs**, **0 = doesn't run**

**`day_offset`** = 1 means the train crosses midnight and arrives the next day

- Output: `graph_enriched.json`

---

## Step 3 — Find a Route

```bash
python step3_find_route.py
```

Example interaction:
```
Enter SOURCE station      : Rajapur Road
Enter DESTINATION station : Madgaon
Enter travel day (Mon/Tue/Wed/Thu/Fri/Sat/Sun): Mon
Enter departure time (HH:MM): 08:00
```

Example output:
```
═══════════════════════════════════════════════════════════════════
  🚂 ROUTE: Rajapur Road  →  Madgaon
  📅 Date : Mon   ⏰ Start: 08:00
═══════════════════════════════════════════════════════════════════

  Segment 1
  🚉 From : Rajapur Road
  🚉 To   : Kankavali
  🚆 Train: 10101 (KOKAN KANYA EXP)
  🕐 Dep  : 08:35   Arr: 09:10
  ⏱  Travel time: 0h 35m

  ⏳ Wait at Kankavali: 0h 45m

  Segment 2
  🚉 From : Kankavali
  🚉 To   : Madgaon
  🚆 Train: 16345 (NETRAVATI EXP)
  🕐 Dep  : 09:55   Arr: 11:40
  ⏱  Travel time: 1h 45m

─────────────────────────────────────────────────────────────────
  Total travel time : 2h 20m
  Total waiting time: 0h 45m + 0h 35m (wait for first train)
  Total journey time: 3h 40m
  Transfers         : 1
═══════════════════════════════════════════════════════════════════
```

---

## How Waiting Time is Calculated

```
waiting_time = departure_time_of_next_train - arrival_time_of_previous_train
```

The algorithm automatically:
1. Checks if the next train actually **runs on your travel day**
2. Finds the **earliest available train** at each station after you arrive
3. If no train today, waits until the **next day the train runs**
4. Never suggests waiting more than **12 hours** for a connection

---

## Data Model Explanation for Your Report

```
graph_enriched.json
│
├── Station (key)
│   └── Edge (array of connections)
│       ├── to            → destination station name
│       ├── train         → 5-digit train number
│       ├── train_name    → e.g. "KOKAN KANYA EXP"
│       ├── weight        → distance in km
│       ├── departure_time→ "HH:MM" from source station
│       ├── arrival_time  → "HH:MM" at destination
│       ├── travel_minutes→ integer, actual travel time
│       ├── day_offset    → 0 = same day, 1 = arrives next day
│       └── running_days  → [1,1,1,1,1,1,1] Mon-Sun
```

---

## What to Tell Your Sir

Your project now handles:

- ✅ **Train schedules** — arrival and departure at each station
- ✅ **Running days** — which days each train operates
- ✅ **Waiting/transfer time** — automatically calculated between connections
- ✅ **Overnight journeys** — day_offset tracks trains crossing midnight
- ✅ **Time-aware routing** — Dijkstra that respects time, not just distance
