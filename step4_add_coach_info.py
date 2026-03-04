"""
STEP 4 - Add Coach Info to Enriched Graph (Rule-Based)
=======================================================
Since no website exposes coach composition in scrapable HTML,
we use train name/type rules — which are accurate for Indian Railways:

  Rajdhani     → 1A, 2A, 3A
  Duronto      → 1A, 2A, 3A, SL
  Vande Bharat → EC, CC
  Humsafar     → 3A
  Tejas        → CC, EC
  Garib Rath   → 3A, CC
  Shatabdi     → CC, EC
  Jan Shatabdi → CC, 2S
  Intercity    → CC, 2S
  Mail/Express → 1A, 2A, 3A, SL, GN  (standard)
  Passenger    → SL, GN
  MEMU/DEMU    → 2S, GN

Also uses train NUMBER ranges (Indian Railways standard):
  12001-12299  → Rajdhani/Shatabdi (premium)
  22XXX        → Superfast (usually full AC or SL+AC)
  ...etc.

HOW TO RUN:
    python step4_add_coach_info.py

INPUT:  graph_enriched.json
OUTPUT: graph_enriched.json (updated in-place)
"""

import json, re

GRAPH_FILE = "graph_enriched.json"

# ── Coach rules by train name keywords ───────────────────────────────────────

CLASS_NAMES = {
    "1A":  "First AC (4-berth)",
    "2A":  "Second AC (6-berth)",
    "3A":  "Third AC (8-berth)",
    "3E":  "Third AC Economy",
    "EC":  "Executive Chair Car",
    "CC":  "AC Chair Car",
    "SL":  "Sleeper (non-AC)",
    "2S":  "Second Sitting (non-AC)",
    "GN":  "General / Unreserved",
    "FC":  "First Class (non-AC)",
}

# Rules: (keyword_pattern, classes_list)
# Order matters — more specific rules first
NAME_RULES = [
    # Premium trains
    (r'vande bharat',          ["EC", "CC"]),
    (r'tejas rajdhani',        ["1A", "2A", "3A"]),
    (r'tejas',                 ["EC", "CC"]),
    (r'rajdhani',              ["1A", "2A", "3A"]),
    (r'duronto',               ["1A", "2A", "3A", "SL"]),
    (r'shatabdi',              ["EC", "CC"]),
    (r'jan shatabdi',          ["CC", "2S"]),
    (r'humsafar',              ["3A"]),
    (r'hamsafar',              ["3A"]),
    (r'antyodaya',             ["SL", "GN"]),  # all unreserved
    (r'uday',                  ["EC", "CC"]),
    (r'gatimaan',              ["EC", "CC"]),
    (r'garib rath',            ["3A", "CC"]),
    (r'yuva',                  ["3A", "CC"]),
    (r'double.?decker',        ["CC"]),
    (r'ac express|ac sf|ac superfast', ["2A", "3A", "CC"]),
    (r'intercity',             ["CC", "2S"]),
    (r'jan sadharan',          ["SL", "GN"]),
    (r'passenger',             ["SL", "2S", "GN"]),
    (r'memu|demu|emu',         ["2S", "GN"]),
    (r'link express',          ["SL", "GN"]),
    (r'local',                 ["GN"]),
    # Default Mail/Express
    (r'express|mail|superfast|sf|suf', ["2A", "3A", "SL", "GN"]),
]

# Rules by train number range
NUMBER_RULES = [
    # Rajdhani / Shatabdi
    (12001, 12025, ["1A", "2A", "3A"]),          # Rajdhani
    (12030, 12099, ["EC", "CC"]),                  # Shatabdi
    (22436, 22436, ["EC", "CC"]),                  # Vande Bharat
    # Duronto
    (12200, 12299, ["1A", "2A", "3A", "SL"]),
    # Garib Rath
    (12203, 12260, ["3A", "CC"]),
    # Humsafar
    (22900, 22999, ["3A"]),
    # Vande Bharat (20000s)
    (20901, 20999, ["EC", "CC"]),
]


def infer_classes(train_no: str, train_name: str) -> dict:
    """
    Returns dict with classes_available, has_ac, has_sleeper, has_general,
    and class descriptions.
    """
    name_lower = train_name.lower().strip()
    classes    = None

    # 1. Match by train name
    for pattern, cls_list in NAME_RULES:
        if re.search(pattern, name_lower):
            classes = cls_list
            break

    # 2. Match by train number if name didn't match
    if not classes:
        try:
            num = int(train_no)
            for start, end, cls_list in NUMBER_RULES:
                if start <= num <= end:
                    classes = cls_list
                    break
        except ValueError:
            pass

    # 3. Default fallback
    if not classes:
        classes = ["2A", "3A", "SL", "GN"]  # standard express default

    return {
        "classes_available": classes,
        "classes_detail": {c: CLASS_NAMES.get(c, c) for c in classes},
        "has_ac":      any(c in classes for c in ["1A","2A","3A","3E","EC","CC"]),
        "has_sleeper": "SL" in classes,
        "has_general": any(c in classes for c in ["GN","2S"]),
    }


def main():
    print(f"Loading {GRAPH_FILE}...")
    with open(GRAPH_FILE, encoding="utf-8") as f:
        graph = json.load(f)

    total   = 0
    updated = 0

    # Track per-train so we don't recompute
    train_cache = {}

    for station, edges in graph.items():
        for edge in edges:
            total += 1
            train_no   = edge["train"]
            train_name = edge.get("train_name", "")

            if train_no not in train_cache:
                train_cache[train_no] = infer_classes(train_no, train_name)

            info = train_cache[train_no]
            edge.update(info)
            updated += 1

    with open(GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    # Print summary
    ac_trains      = sum(1 for v in train_cache.values() if v["has_ac"])
    sleeper_trains = sum(1 for v in train_cache.values() if v["has_sleeper"])
    general_trains = sum(1 for v in train_cache.values() if v["has_general"])

    print(f"\n✅ Coach info added to all edges!")
    print(f"   Total edges updated : {updated}")
    print(f"   Trains with AC      : {ac_trains}/{len(train_cache)}")
    print(f"   Trains with Sleeper : {sleeper_trains}/{len(train_cache)}")
    print(f"   Trains with General : {general_trains}/{len(train_cache)}")
    print(f"\nSample coach assignments:")

    shown = set()
    for station, edges in graph.items():
        for edge in edges:
            t = edge["train"]
            if t not in shown:
                shown.add(t)
                print(f"  {t:6s}  {edge.get('train_name','')[:35]:35s}  → {', '.join(edge['classes_available'])}")
            if len(shown) >= 15:
                break
        if len(shown) >= 15:
            break

    print(f"\nNow update step3_find_route.py to show coach info in output.")


if __name__ == "__main__":
    main()
