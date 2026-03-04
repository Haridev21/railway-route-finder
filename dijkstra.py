import heapq

TRAIN_CHANGE_PENALTY = 30
MAX_WAIT_MINUTES     = 1200
MAX_TRANSFERS        = 6

DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
DAY_INDEX  = {d: i for i, d in enumerate(DAY_NAMES)}


def time_to_min(t):
    if not t or str(t).strip() in ("--","None","null",""): return None
    try:
        h, m = map(int, str(t).strip().split(":"))
        return h * 60 + m
    except: return None

def min_to_time(m):
    m = int(m) % 1440
    return f"{m//60:02d}:{m%60:02d}"

def to_ampm(t):
    if not t or t == "--": return t
    try:
        h, m = map(int, t.split(":"))
        period = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {period}"
    except: return t

def mins_to_str(m):
    m = int(m)
    h, rem = divmod(m, 60)
    if h == 0: return f"{rem}m"
    if rem == 0: return f"{h}h"
    return f"{h}h {rem}m"

def train_runs_on_day(running_days, day_idx):
    if not running_days or len(running_days) < 7: return True
    return bool(running_days[day_idx % 7])

def fuzzy_match_station(name, all_stations):
    name_lower = name.lower().strip()
    for s in all_stations:
        if s.lower().strip() == name_lower: return s
    candidates = [s for s in all_stations
                  if name_lower in s.lower() or s.lower() in name_lower]
    if len(candidates) == 1: return candidates[0]
    if len(candidates) > 1: return sorted(candidates, key=len)[0]
    name_words = set(name_lower.split())
    best, best_score = None, 0
    for s in all_stations:
        overlap = len(name_words & set(s.lower().split()))
        if overlap > best_score and overlap >= min(2, len(name_words)):
            best, best_score = s, overlap
    return best


def dijkstra(graph, source, destination,
             travel_day="Mon", start_time="00:00",
             prefer_ac=False, prefer_sleeper=False):
    """
    Time-aware Dijkstra for Indian Railways.
    Minimises total journey time = travel_time + waiting_time.
    Respects start_time: never boards trains departing before start_time.
    """
    all_stations = set(graph.keys())
    for edges in graph.values():
        for e in edges: all_stations.add(e["to"])

    src = fuzzy_match_station(source, all_stations)
    dst = fuzzy_match_station(destination, all_stations)

    if not src:
        return {"found":False,"error":f"Station '{source}' not found.",
                "source":source,"destination":destination,"path":[]}
    if not dst:
        return {"found":False,"error":f"Station '{destination}' not found.",
                "source":source,"destination":destination,"path":[]}

    source      = src
    destination = dst
    start_day_idx = DAY_INDEX.get(travel_day, 0)
    start_min     = time_to_min(start_time) or 0

    distances  = {source: 0}
    parent     = {}
    train_used = {}
    edge_used  = {}
    counter    = 0

   
    pq = [(0, counter, start_min, 0, source, None)]

    while pq:
        elapsed, _, clock_min, day_off, station, last_train = heapq.heappop(pq)

        if elapsed > distances.get(station, float("inf")): continue
        if station == destination: break

        # Enforce transfer limit
        hops, curr = 0, station
        while curr in parent:
            prev = parent[curr]
            if train_used.get(curr) != train_used.get(prev): hops += 1
            curr = prev
        if hops >= MAX_TRANSFERS: continue

        for edge in graph.get(station, []):
            next_stn     = edge["to"]
            train_no     = edge["train"]
            train_name   = edge.get("train_name", "")
            running_days = edge.get("running_days", [1,1,1,1,1,1,1])
            dep_str      = edge.get("departure_time")
            arr_str      = edge.get("arrival_time")
            travel_min   = edge.get("travel_minutes")
            edge_day_off = edge.get("day_offset", 0)
            weight       = edge.get("weight", 0)
            classes      = edge.get("classes_available", [])

            if prefer_ac      and not edge.get("has_ac",      False): continue
            if prefer_sleeper and not edge.get("has_sleeper",  False): continue

            dep_min    = time_to_min(dep_str)
            arr_min    = time_to_min(arr_str)
            has_timing = (dep_min is not None and arr_min is not None and travel_min is not None)

            if has_timing:
                wait_min = best_dep_abs = best_day_off = None
                for days_ahead in range(8):
                    check_day_idx = (start_day_idx + day_off + days_ahead) % 7
                    if not train_runs_on_day(running_days, check_day_idx): continue
                    candidate_dep = (day_off + days_ahead) * 1440 + dep_min
                    if candidate_dep < clock_min: continue
                    wait = candidate_dep - clock_min
                    if wait > MAX_WAIT_MINUTES: break
                    wait_min = wait; best_dep_abs = candidate_dep
                    best_day_off = day_off + days_ahead
                    break
                if wait_min is None: continue

                new_elapsed = elapsed + wait_min + travel_min
                if last_train is not None and train_no != last_train:
                    new_elapsed += TRAIN_CHANGE_PENALTY
                arr_clock = best_dep_abs + travel_min

            else:
                if train_no != last_train or last_train is None: continue
                travel_min  = max(5, int(weight))
                wait_min    = 0
                new_elapsed = elapsed + travel_min
                arr_clock   = clock_min + travel_min
                best_day_off = day_off

            if new_elapsed < distances.get(next_stn, float("inf")):
                distances[next_stn]  = new_elapsed
                parent[next_stn]     = station
                train_used[next_stn] = train_no
                edge_used[next_stn]  = {
                    "from": station, "to": next_stn,
                    "train": train_no, "train_name": train_name,
                    "dep_time": dep_str or "--", "arr_time": arr_str or "--",
                    "dep_ampm": to_ampm(dep_str), "arr_ampm": to_ampm(arr_str),
                    "wait_min": wait_min, "travel_min": travel_min,
                    "has_timing": has_timing, "distance_km": weight,
                    "classes": classes,
                    "has_ac":      edge.get("has_ac",      False),
                    "has_sleeper": edge.get("has_sleeper",  False),
                    "dep_abs":  best_dep_abs if has_timing else clock_min,
                    "arr_abs":  arr_clock,
                    "day_off":  best_day_off if has_timing else day_off,
                }
                counter += 1
                heapq.heappush(pq, (new_elapsed, counter, arr_clock,
                                    best_day_off if has_timing else day_off,
                                    next_stn, train_no))

    if distances.get(destination, float("inf")) == float("inf"):
        return {"found":False,"error":f"No route found from '{source}' to '{destination}'.",
                "source":source,"destination":destination,"path":[]}

    path = []
    curr = destination
    while curr != source:
        e = edge_used.get(curr, {})
        path.append({"station":curr,"train":train_used.get(curr),"edge":e})
        curr = parent.get(curr)
        if curr is None: break
    path.append({"station":source,"train":None,"edge":{}})
    path.reverse()

    total_travel = sum(p["edge"].get("travel_min",0) for p in path if p.get("edge"))
    total_wait   = sum(p["edge"].get("wait_min",0)   for p in path if p.get("edge"))
    total_min    = total_travel + total_wait
    total_dist   = sum(p["edge"].get("distance_km",0) for p in path if p.get("edge"))
    trains       = [p["train"] for p in path if p.get("train")]
    transfers    = sum(1 for i in range(1,len(trains)) if trains[i]!=trains[i-1])

    return {
        "found":True,"source":source,"destination":destination,
        "travel_day":travel_day,"start_time":start_time,
        "total_minutes":total_min,"travel_minutes":total_travel,"waiting_minutes":total_wait,
        "total_time":mins_to_str(total_min),"travel_time":mins_to_str(total_travel),
        "waiting_time":mins_to_str(total_wait),
        "total_distance":round(total_dist,1),"transfers":transfers,"path":path,
    }
