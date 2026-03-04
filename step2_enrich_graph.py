"""
STEP 2 (FIXED v3) - Enrich Graph using Station Code Matching
=============================================================
Root cause of 60% miss rate:
  Graph uses abbreviated names: 'Bolpur S Niktn', 'Dd Upadhyaya Jn', 'Barddhaman Jn'
  Website uses full names     : 'Bolpur Santiniketan', 'Pt Deen Dayal Upadhyaya Jn', 'Bardhaman Junction'

Fix: 
  1. Build a master code->timing lookup from all schedules
  2. Match graph station names to station codes using fuzzy similarity
  3. Use codes for all timing lookups (codes are standardized: 'BWN', 'DDU', 'BHP')

HOW TO RUN:
    python step2_enrich_graph.py

INPUT:  graph_adjacency_list.json + train_schedules.json
OUTPUT: graph_enriched.json  +  station_code_map.json (for inspection)
"""

import json, re
from difflib import SequenceMatcher

GRAPH_FILE     = "graph_adjacency_list.json"
SCHEDULES_FILE = "train_schedules.json"
OUTPUT_FILE    = "graph_enriched.json"
CODE_MAP_FILE  = "station_code_map.json"   # saves the name->code mapping for debugging

# ── Text normalization ────────────────────────────────────────────────────────

SUFFIX_EXPAND = {
    'JN': 'JUNCTION', 'RD': 'ROAD', 'ST': 'STATION',
    'NGR': 'NAGAR', 'HLT': 'HALT', 'H': 'HALT',
    'MG': 'MARG', 'BR': 'BRIDGE', 'CANT': 'CANTONMENT',
    'NIKTN': 'NIKETAN', 'SNKT': 'SANTINIKETAN',
}

def normalize(name: str) -> str:
    s = re.sub(r'[^A-Za-z0-9 ]', ' ', name.upper())
    tokens = s.split()
    expanded = [SUFFIX_EXPAND.get(t, t) for t in tokens]
    return ' '.join(expanded)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def time_to_min(t):
    if not t or t in ('--', 'None', '', 'null'):
        return None
    try:
        h, m = map(int, t.strip().split(':'))
        return h * 60 + m
    except Exception:
        return None


def minutes_diff(dep, arr):
    if arr >= dep:
        return arr - dep, 0
    return (1440 - dep) + arr, 1


# ── Build master indexes ──────────────────────────────────────────────────────

def build_indexes(schedules):
    """
    Returns:
      code_to_fullname : { 'BWN': 'Bardhaman Junction', ... }
      norm_to_code     : { 'BARDHAMAN JUNCTION': 'BWN', ... }
      train_code_timing: { train_no: { station_code: {arr, dep, day} } }
    """
    code_to_fullname  = {}   # code -> most common full name seen
    norm_to_code      = {}   # normalized name -> code  
    train_code_timing = {}   # train -> code -> timing

    code_name_freq = {}      # code -> {name: count}

    for train_no, data in schedules.items():
        if data.get('error') or not data.get('stations'):
            continue

        train_code_timing[train_no] = {}

        for stop in data['stations']:
            code = stop.get('station_code', '').strip().upper()
            name = stop.get('station', '').strip()
            if not code or not name:
                continue

            # Track which full name is most commonly seen for each code
            if code not in code_name_freq:
                code_name_freq[code] = {}
            code_name_freq[code][name] = code_name_freq[code].get(name, 0) + 1

            # Store normalized name -> code mapping
            norm = normalize(name)
            if norm and norm not in norm_to_code:
                norm_to_code[norm] = code

            # Store timing
            timing = {
                'arrival':   stop['arrival'],
                'departure': stop['departure'],
                'day':       stop.get('day', 1)
            }
            train_code_timing[train_no][code] = timing

    # Build code_to_fullname from most frequent name
    for code, name_counts in code_name_freq.items():
        code_to_fullname[code] = max(name_counts, key=name_counts.get)

    return code_to_fullname, norm_to_code, train_code_timing


def build_graph_station_to_code(all_graph_stations, norm_to_code, code_to_fullname):
    """
    For each station name in the graph, find its best matching station code.
    Strategy (in order):
      1. Exact normalized match
      2. High-similarity fuzzy match (>= 0.85)
      3. One string contains the other
    """
    station_to_code = {}
    
    # Pre-compute normalized versions of all schedule station names
    norm_keys = list(norm_to_code.keys())

    matched    = 0
    unmatched  = []

    for station in sorted(all_graph_stations):
        norm_station = normalize(station)

        # 1. Exact match
        if norm_station in norm_to_code:
            station_to_code[station] = norm_to_code[norm_station]
            matched += 1
            continue

        # 2. Fuzzy match — only check keys with similar length (speed optimization)
        slen = len(norm_station)
        candidates = [(k, norm_to_code[k]) for k in norm_keys
                      if abs(len(k) - slen) <= max(6, slen * 0.4)]

        best_score = 0.0
        best_code  = None
        for cand_norm, cand_code in candidates:
            score = similarity(norm_station, cand_norm)
            if score > best_score:
                best_score = score
                best_code  = cand_code

        if best_score >= 0.82:
            station_to_code[station] = best_code
            matched += 1
            continue

        # 3. Substring match — one contains all words of the other
        station_words = set(norm_station.split())
        for cand_norm, cand_code in candidates:
            cand_words = set(cand_norm.split())
            if station_words and cand_words:
                overlap = len(station_words & cand_words)
                if overlap >= min(len(station_words), len(cand_words)) - 1 and overlap >= 2:
                    station_to_code[station] = cand_code
                    matched += 1
                    break
        else:
            unmatched.append(station)

    print(f"  Station name->code matched  : {matched}/{len(all_graph_stations)} ({matched/len(all_graph_stations)*100:.1f}%)")
    print(f"  Station name->code unmatched: {len(unmatched)}")
    if unmatched[:10]:
        print(f"  Unmatched samples: {unmatched[:10]}")

    return station_to_code


def lookup_timing(train_code_timing, train_no, station_code):
    if not train_no or not station_code:
        return None
    t = train_code_timing.get(train_no, {})
    return t.get(station_code.upper())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Loading {GRAPH_FILE}...")
    with open(GRAPH_FILE, encoding='utf-8') as f:
        graph = json.load(f)

    print(f"Loading {SCHEDULES_FILE}...")
    with open(SCHEDULES_FILE, encoding='utf-8') as f:
        schedules = json.load(f)

    print("\nBuilding schedule indexes...")
    code_to_fullname, norm_to_code, train_code_timing = build_indexes(schedules)
    print(f"  Unique station codes found : {len(code_to_fullname)}")
    print(f"  Normalized name->code keys : {len(norm_to_code)}")

    # Collect all station names used in the graph
    all_graph_stations = set(graph.keys())
    for edges in graph.values():
        for e in edges:
            all_graph_stations.add(e['to'])
    print(f"\nMatching {len(all_graph_stations)} graph stations to codes...")

    station_to_code = build_graph_station_to_code(
        all_graph_stations, norm_to_code, code_to_fullname
    )

    # Save the mapping for inspection
    with open(CODE_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            s: {
                'code': station_to_code.get(s, ''),
                'full_name': code_to_fullname.get(station_to_code.get(s, ''), '')
            }
            for s in sorted(all_graph_stations)
        }, f, indent=2, ensure_ascii=False)
    print(f"  Station code map saved: {CODE_MAP_FILE}")

    # Enrich the graph
    print("\nEnriching graph edges...")
    total = enriched = missing = 0
    enriched_graph = {}

    for station, edges in graph.items():
        enriched_graph[station] = []
        src_code = station_to_code.get(station)

        for edge in edges:
            total += 1
            train_no = edge['train']
            dest     = edge['to']
            dst_code = station_to_code.get(dest)

            new_edge = dict(edge)
            sdata = schedules.get(train_no, {})
            new_edge['running_days'] = sdata.get('running_days', [1,1,1,1,1,1,1])
            new_edge['train_name']   = sdata.get('train_name', '')

            src_t = lookup_timing(train_code_timing, train_no, src_code)
            dst_t = lookup_timing(train_code_timing, train_no, dst_code)

            if src_t and dst_t:
                dep = src_t['departure'] if src_t['departure'] not in ('--','') else src_t['arrival']
                arr = dst_t['arrival']   if dst_t['arrival']   not in ('--','') else dst_t['departure']

                dep_min = time_to_min(dep)
                arr_min = time_to_min(arr)

                if dep_min is not None and arr_min is not None:
                    travel_min, day_offset = minutes_diff(dep_min, arr_min)
                    new_edge['departure_time'] = dep
                    new_edge['arrival_time']   = arr
                    new_edge['travel_minutes'] = travel_min
                    new_edge['day_offset']     = day_offset
                    enriched += 1
                else:
                    new_edge.update({'departure_time': None, 'arrival_time': None,
                                     'travel_minutes': None, 'day_offset': 0})
                    missing += 1
            else:
                new_edge.update({'departure_time': None, 'arrival_time': None,
                                 'travel_minutes': None, 'day_offset': 0})
                missing += 1

            enriched_graph[station].append(new_edge)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(enriched_graph, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Enrichment complete!")
    print(f"   Total edges    : {total}")
    print(f"   Enriched       : {enriched}  ({enriched/total*100:.1f}%)")
    print(f"   Missing timing : {missing}  ({missing/total*100:.1f}%)")
    print(f"   Output saved   : {OUTPUT_FILE}")
    print(f"\n   Tip: Open {CODE_MAP_FILE} to see how graph stations mapped to codes.")


if __name__ == '__main__':
    main()