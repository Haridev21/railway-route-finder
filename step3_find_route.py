"""
STEP 3 (Final) - Time-Aware Dijkstra with Coach Info
"""

import json
import heapq

GRAPH_FILE     = "graph_enriched.json"
MAX_WAIT_HOURS = 20
MAX_TRANSFERS  = 5

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_INDEX = {d: i for i, d in enumerate(DAY_NAMES)}


def time_to_min(t):
    if not t or str(t) in ('--', 'None', 'null', 'none', ''):
        return None
    try:
        h, m = map(int, str(t).strip().split(':'))
        return h * 60 + m
    except Exception:
        return None


def min_to_time(m):
    m = int(m) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def train_runs_on_day(running_days, day_idx):
    if not running_days or len(running_days) < 7:
        return True
    return bool(running_days[day_idx % 7])


def find_best_route(graph, source, destination, travel_day, start_time,
                    require_ac=False, require_sleeper=False):

    all_stations = set(graph.keys())
    for edges in graph.values():
        for e in edges:
            all_stations.add(e['to'])

    lower_map   = {s.lower().strip(): s for s in all_stations}
    source      = lower_map.get(source.lower().strip(), source.strip())
    destination = lower_map.get(destination.lower().strip(), destination.strip())

    if source not in all_stations:
        print(f"❌ Source '{source}' not found.")
        return
    if destination not in all_stations:
        print(f"❌ Destination '{destination}' not found.")
        return

    start_day_idx = DAY_INDEX[travel_day]
    start_min     = time_to_min(start_time)
    if start_min is None:
        print("❌ Invalid time format. Use HH:MM")
        return

    counter = 0
    heap    = [(0, counter, start_min, 0, 0, source, [])]
    visited = {}

    while heap:
        elapsed, _, curr_abs, total_day_off, transfers, curr_stn, path = heapq.heappop(heap)

        if curr_stn == destination:
            _print_route(path, source, destination, travel_day, start_time, elapsed)
            return

        prev = visited.get(curr_stn)
        if prev and prev[0] <= elapsed and prev[1] <= transfers:
            continue
        visited[curr_stn] = (elapsed, transfers)

        if transfers > MAX_TRANSFERS:
            continue

        curr_train = path[-1]['train'] if path else None

        for edge in graph.get(curr_stn, []):
            train_no     = edge['train']
            train_name   = edge.get('train_name', '')
            dest         = edge['to']
            dep_str      = edge.get('departure_time')
            arr_str      = edge.get('arrival_time')
            travel_min   = edge.get('travel_minutes')
            running_days = edge.get('running_days', [1,1,1,1,1,1,1])
            d_off        = edge.get('day_offset', 0)
            classes      = edge.get('classes_available', [])

            # Filter by class preference
            if require_ac and not edge.get('has_ac', False):
                continue
            if require_sleeper and not edge.get('has_sleeper', False):
                continue

            dep_min = time_to_min(dep_str)
            arr_min = time_to_min(arr_str)
            has_timing = dep_min is not None and arr_min is not None and travel_min is not None

            if not has_timing:
                if train_no != curr_train:
                    continue
                w = edge.get('weight', 30)
                travel_min  = max(5, int(w / 60 * 60))
                counter    += 1
                new_elapsed = elapsed + travel_min
                new_path = path + [{
                    'from': curr_stn, 'to': dest,
                    'train': train_no, 'train_name': train_name,
                    'dep_time': None, 'arr_time': None,
                    'wait_min': 0, 'travel_min': travel_min,
                    'has_timing': False,
                    'dep_abs': curr_abs, 'arr_abs': curr_abs + travel_min,
                    'classes': classes,
                }]
                heapq.heappush(heap, (new_elapsed, counter, curr_abs + travel_min,
                                      total_day_off, transfers, dest, new_path))
                continue

            best_wait = best_dep_abs = best_day_off = None
            for days_ahead in range(8):
                day_idx = (start_day_idx + total_day_off + days_ahead) % 7
                if not train_runs_on_day(running_days, day_idx):
                    continue
                candidate_dep_abs = (total_day_off + days_ahead) * 1440 + dep_min
                if candidate_dep_abs < curr_abs:
                    continue
                wait = candidate_dep_abs - curr_abs
                if wait > MAX_WAIT_HOURS * 60:
                    break
                best_wait    = wait
                best_dep_abs = candidate_dep_abs
                best_day_off = total_day_off + days_ahead
                break

            if best_wait is None:
                continue

            arr_abs       = best_dep_abs + travel_min + d_off * 1440
            new_elapsed   = elapsed + best_wait + travel_min
            new_transfers = transfers + (0 if train_no == curr_train else 1)

            counter += 1
            new_path = path + [{
                'from': curr_stn, 'to': dest,
                'train': train_no, 'train_name': train_name,
                'dep_time': dep_str, 'arr_time': arr_str,
                'wait_min': best_wait, 'travel_min': travel_min,
                'has_timing': True,
                'dep_abs': best_dep_abs, 'arr_abs': arr_abs,
                'classes': classes,
            }]
            heapq.heappush(heap, (new_elapsed, counter, arr_abs,
                                  best_day_off, new_transfers, dest, new_path))

    print(f"\n❌ No route found from '{source}' to '{destination}' on {travel_day}.")
    if require_ac:
        print("   Try again without AC filter.")


def merge_segments(path):
    if not path:
        return path
    merged = []
    curr = dict(path[0])
    for seg in path[1:]:
        if seg['train'] == curr['train']:
            curr['to']          = seg['to']
            curr['arr_time']    = seg['arr_time']
            curr['arr_abs']     = seg['arr_abs']
            curr['travel_min'] += seg['travel_min']
            curr['has_timing']  = curr['has_timing'] and seg['has_timing']
        else:
            merged.append(curr)
            curr = dict(seg)
    merged.append(curr)
    return merged


def format_classes(classes):
    if not classes:
        return ""
    icons = {"1A": "🔵", "2A": "🟣", "3A": "🟡", "3E": "🟠",
             "EC": "🔴", "CC": "🟢", "SL": "⚪", "2S": "⚫", "GN": "⬛"}
    parts = [f"{icons.get(c,'•')}{c}" for c in classes]
    return "  ·  " + "  ".join(parts)


def _print_route(path, source, destination, travel_day, start_time, total_elapsed):
    path = merge_segments(path)

    print("\n" + "═" * 68)
    print(f"  🚂 ROUTE  : {source}  →  {destination}")
    print(f"  📅 Day    : {travel_day}   ⏰ Depart after: {start_time}")
    print("═" * 68)

    total_travel = sum(s['travel_min'] for s in path)
    total_wait   = sum(s['wait_min']   for s in path)
    transfers    = len(path) - 1

    for i, seg in enumerate(path):
        w_h, w_m   = divmod(int(seg['wait_min']), 60)
        t_h, t_m   = divmod(int(seg['travel_min']), 60)
        travel_str = f"{t_h}h {t_m}m" if t_h else f"{t_m}m"

        if seg['wait_min'] > 0:
            wait_str = f"{w_h}h {w_m}m" if w_h else f"{w_m}m"
            print(f"\n  ⏳ Wait at {seg['from']}: {wait_str}")

        name_str    = f" — {seg['train_name']}" if seg['train_name'] else ""
        class_str   = format_classes(seg.get('classes', []))

        if seg['has_timing'] and seg['dep_time'] and seg['arr_time']:
            time_str = f"Dep {seg['dep_time']}  →  Arr {seg['arr_time']}"
        else:
            time_str = f"~{travel_str} estimated"

        print(f"\n  ┌─ Segment {i+1}: Train {seg['train']}{name_str}")
        print(f"  │  🚉 {seg['from']}  →  {seg['to']}")
        print(f"  │  🕐 {time_str}  ·  {travel_str}")
        print(f"  └─ 🪑 Classes:{class_str if class_str else ' N/A'}")

    print("\n" + "─" * 68)
    te_h, te_m = divmod(int(total_elapsed), 60)
    tt_h, tt_m = divmod(int(total_travel), 60)
    tw_h, tw_m = divmod(int(total_wait), 60)
    print(f"  🕐 Total journey : {te_h}h {te_m}m")
    print(f"  🚆 Travel time   : {tt_h}h {tt_m}m")
    print(f"  ⏳ Waiting time  : {tw_h}h {tw_m}m")
    print(f"  🔄 Train changes : {transfers}")
    print("═" * 68 + "\n")


def main():
    print("Loading graph...")
    with open(GRAPH_FILE, encoding='utf-8') as f:
        graph = json.load(f)
    print(f"Graph loaded: {len(graph)} stations.\n")

    print("Sample stations:", ", ".join(list(graph.keys())[:8]))
    print()

    while True:
        source      = input("Source station                            : ").strip()
        destination = input("Destination station                       : ").strip()
        travel_day  = input("Travel day (Mon/Tue/Wed/Thu/Fri/Sat/Sun)  : ").strip().capitalize()[:3]
        start_time  = input("Earliest departure time (HH:MM)           : ").strip()

        pref = input("Preference? (ac / sleeper / any)          : ").strip().lower()
        require_ac      = pref == "ac"
        require_sleeper = pref == "sleeper"

        if travel_day not in DAY_INDEX:
            print("❌ Invalid day.\n")
            continue

        find_best_route(graph, source, destination, travel_day, start_time,
                        require_ac=require_ac, require_sleeper=require_sleeper)


if __name__ == "__main__":
    main()