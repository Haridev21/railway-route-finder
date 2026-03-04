from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os, gc
from datetime import datetime, date as dt_date

from dijkstra import dijkstra, mins_to_str
from fare_calculator import estimate_route_fare, cheapest_class, _CLASS_ORDER

app = Flask(__name__)
CORS(app)

DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

GRAPH           = None
ALL_STATIONS    = None
STATIONS_SORTED = None
TOTAL_EDGES     = None

def load_graph():
    global GRAPH, ALL_STATIONS, STATIONS_SORTED, TOTAL_EDGES
    if GRAPH is not None:
        return  

    print("Loading graph_enriched.json...")
    with open("graph_enriched.json", encoding="utf-8") as f:
        GRAPH = json.load(f)

    ALL_STATIONS = set(GRAPH.keys())
    for edges in GRAPH.values():
        for e in edges:
            ALL_STATIONS.add(e["to"])

    STATIONS_SORTED = sorted(ALL_STATIONS)
    TOTAL_EDGES     = sum(len(v) for v in GRAPH.values())

    gc.collect()  
    print(f"Loaded: {len(ALL_STATIONS)} stations | {TOTAL_EDGES} edges")



def date_to_day(s):
    for fmt in ('%Y-%m-%d','%d-%m-%Y','%d/%m/%Y'):
        try: return DAY_NAMES[datetime.strptime(s.strip(), fmt).weekday()]
        except: pass
    return DAY_NAMES[dt_date.today().weekday()]


def _build_segments(path):
    segments, i = [], 0
    while i < len(path):
        stop = path[i]; e = stop.get("edge", {})
        if not e: i += 1; continue
        tno   = stop["train"]; tname = e.get("train_name","")
        sfrom = e.get("from",""); sto   = e.get("to","")
        dep_t = e.get("dep_time","--"); dep_a = e.get("dep_ampm", dep_t)
        arr_t = e.get("arr_time","--"); arr_a = e.get("arr_ampm", arr_t)
        wmin  = e.get("wait_min",0);  trmin = e.get("travel_min",0)
        dist  = e.get("distance_km",0); classes = e.get("classes",[])
        has_ac = e.get("has_ac",False); has_sl = e.get("has_sleeper",False)
        doff  = e.get("day_off",0)
        j = i + 1
        while j < len(path):
            nxt = path[j]
            if nxt["train"] != tno: break
            ne = nxt.get("edge",{})
            if ne:
                sto   = ne.get("to", sto)
                arr_t = ne.get("arr_time", arr_t)
                arr_a = ne.get("arr_ampm", arr_t)
                trmin += ne.get("travel_min",0)
                dist  += ne.get("distance_km",0)
                doff   = ne.get("day_off", doff)
                if ne.get("has_ac"):      has_ac = True
                if ne.get("has_sleeper"): has_sl = True
            j += 1
        warn = "very_long" if wmin>480 else ("long" if wmin>240 else None)
        segments.append({
            "train_no": tno, "train_name": tname,
            "from": sfrom, "to": sto,
            "dep_time": dep_t, "dep_ampm": dep_a,
            "arr_time": arr_t, "arr_ampm": arr_a,
            "wait_minutes": int(wmin),
            "wait_str": mins_to_str(wmin) if wmin > 0 else None,
            "wait_warning": warn,
            "travel_minutes": int(trmin),
            "travel_str": mins_to_str(trmin),
            "distance_km": round(dist,1),
            "classes": classes, "has_ac": has_ac, "has_sleeper": has_sl,
            "overnight": doff > 0, "day_offset": int(doff),
        })
        i = j
    return segments


def _fmt(result, travel_date=""):
    segs = _build_segments(result["path"])
    tm = int(result.get("total_minutes",0))
    tv = int(result.get("travel_minutes",0))
    wt = int(result.get("waiting_minutes",0))
    return {
        "found": True, "source": result["source"], "destination": result["destination"],
        "travel_day": result.get("travel_day","Mon"), "travel_date": travel_date,
        "start_time": result.get("start_time","00:00"),
        "total_time": mins_to_str(tm), "travel_time": mins_to_str(tv),
        "waiting_time": mins_to_str(wt),
        "total_minutes": tm, "travel_minutes": tv, "waiting_minutes": wt,
        "distance_km": result.get("total_distance",0),
        "transfers": result.get("transfers",0),
        "segments": segs,
        "path": [{"station":s["station"],"train":s["train"]} for s in result["path"]],
    }



@app.route("/", methods=["GET"])
def health():
    load_graph()
    return jsonify({"status":"ok","stations":len(ALL_STATIONS),"edges":TOTAL_EDGES})


@app.route("/stations", methods=["GET"])
def stations():
    load_graph()
    q = request.args.get("q","").lower().strip()
    out = [s for s in STATIONS_SORTED if q in s.lower()] if q else STATIONS_SORTED
    return jsonify({"stations": out, "count": len(out)})


@app.route("/shortest-path", methods=["POST"])
def shortest_path():
    load_graph()
    d = request.get_json()
    if not d: return jsonify({"error":"No JSON"}), 400
    src = d.get("source","").strip(); dst = d.get("destination","").strip()
    if not src or not dst: return jsonify({"error":"source and destination required"}), 400
    if src == dst: return jsonify({"error":"Same source and destination"}), 400
    result = dijkstra(GRAPH, src, dst, travel_day="Mon", start_time="00:00")
    if not result["found"]: return jsonify({"error":result.get("error","No route"),"found":False}), 404
    return jsonify(_fmt(result))


@app.route("/find-route", methods=["POST"])
def find_route():
    try:
        load_graph()
        return _find_route_inner()
    except Exception as e:
        print(f"[find-route crash] {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Server error: {e}", "found": False}), 500


def _find_route_inner():
    d = request.get_json()
    if not d: return jsonify({"error":"No JSON"}), 400

    src   = d.get("source","").strip()
    dst   = d.get("destination","").strip()
    stime = d.get("start_time","00:00").strip()
    pref  = d.get("preference","any").strip().lower()
    cls   = d.get("coach_class", None)
    tdate = d.get("travel_date","").strip()
    tday  = d.get("travel_day","").strip()
    bgt   = d.get("budget", None)

    if not src or not dst:
        return jsonify({"error":"source and destination are required"}), 400
    if src == dst:
        return jsonify({"error":"Source and destination cannot be the same"}), 400

    if tdate:
        tday = date_to_day(tdate)
    elif tday:
        tday = tday.capitalize()[:3]
        if tday not in DAY_NAMES: tday = "Mon"
    else:
        tday = DAY_NAMES[dt_date.today().weekday()]

    pac = pref == "ac"
    psl = pref in ("sleeper","sl")

    if psl and cls in (None, 'GN', '2S'):
        cls = 'SL'
    elif pac and cls in (None, 'GN', '2S', 'SL'):
        cls = '3A'

    result = dijkstra(GRAPH, src, dst, travel_day=tday, start_time=stime,
                      prefer_ac=pac, prefer_sleeper=psl)

    if not result["found"]:
        return jsonify({"error":result.get("error","No route found"),
                        "found":False,"source":src,"destination":dst}), 404

    out = _fmt(result, travel_date=tdate)

    try:
        if psl:
            fare_classes = ['GN','2S','SL']
        elif pac:
            fare_classes = ['CC','3E','3A','2A','1A']
        else:
            fare_classes = ['GN','2S','SL','3A','2A','1A']

        all_fares = {}
        for c in fare_classes:
            if out["segments"] and all(c in seg.get("classes",[]) for seg in out["segments"]):
                fi = estimate_route_fare(out["segments"], preferred_class=c)
                all_fares[c] = fi["total_fare"]

        fare_info = estimate_route_fare(out["segments"], preferred_class=cls)
        out["fare"]             = fare_info["total_fare"]
        out["fare_breakdown"]   = fare_info["breakdown"]
        out["fare_class"]       = fare_info["class_used"]
        out["fare_per_segment"] = fare_info["per_segment"]
        out["all_class_fares"]  = all_fares
    except Exception as e:
        out["fare"]             = 0
        out["fare_class"]       = cls or "SL"
        out["fare_breakdown"]   = ""
        out["fare_per_segment"] = []
        out["all_class_fares"]  = {}
        print(f"[fare error] {e}")

    try: bgt = int(bgt) if bgt is not None else None
    except: bgt = None

    if bgt is not None:
        out["budget"] = bgt
        if fare_info["total_fare"] > bgt:
            out["budget_exceeded"]    = True
            out["budget_gap"]         = fare_info["total_fare"] - bgt
            out["budget_alternative"] = _find_alternative(
                src, dst, tday, stime, bgt, cls, out, pac, psl)
        else:
            out["budget_exceeded"] = False
            out["budget_gap"]      = 0

    return jsonify(out)


def _find_alternative(src, dst, tday, stime, budget, cls, primary, pac, psl):
    segs  = primary["segments"]
    pfare = primary["fare"]
    pcls  = primary["fare_class"]
    ptime = primary["total_minutes"]

    idx = _CLASS_ORDER.index(pcls) if pcls in _CLASS_ORDER else 4
    for c in _CLASS_ORDER[:idx]:
        if not all(c in s.get("classes",[]) for s in segs): continue
        a = estimate_route_fare(segs, preferred_class=c)
        if a["total_fare"] <= budget:
            dep = segs[0].get("dep_ampm","--") if segs else "--"
            return {
                "type":           "cheaper_class",
                "coach_class":    c,
                "fare":           a["total_fare"],
                "fare_breakdown": a["breakdown"],
                "savings":        pfare - a["total_fare"],
                "time_diff_min":  0,
                "time_diff_str":  "Same route, same time",
                "total_time":     primary["total_time"],
                "total_minutes":  ptime,
                "transfers":      primary["transfers"],
                "segments":       segs,
                "summary": (
                    f"Fastest route in {pcls} costs Rs{pfare} — over your budget of Rs{budget}.\n"
                    f"Here's the same route in {c}:\n"
                    f"Rs{a['total_fare']} | {c} class | Same travel time | Dep {dep}"
                ),
            }

    if pac or psl:
        r2 = dijkstra(GRAPH, src, dst, travel_day=tday, start_time=stime,
                      prefer_ac=False, prefer_sleeper=False)
        if r2["found"]:
            f2   = _fmt(r2)
            a2   = estimate_route_fare(f2["segments"])
            td   = r2.get("total_minutes",0) - ptime
            dep2 = f2["segments"][0].get("dep_ampm","--") if f2["segments"] else "--"
            if a2["total_fare"] <= budget and abs(td) <= 180:
                return {
                    "type":           "relaxed_preference",
                    "coach_class":    a2["class_used"],
                    "fare":           a2["total_fare"],
                    "fare_breakdown": a2["breakdown"],
                    "savings":        pfare - a2["total_fare"],
                    "time_diff_min":  td,
                    "time_diff_str":  f"+{mins_to_str(td)} longer" if td>0 else f"{mins_to_str(abs(td))} faster",
                    "total_time":     f2["total_time"],
                    "total_minutes":  r2.get("total_minutes",0),
                    "transfers":      r2.get("transfers",0),
                    "segments":       f2["segments"],
                    "summary": (
                        f"Fastest route costs Rs{pfare} — over budget.\n"
                        f"More affordable option:\n"
                        f"Rs{a2['total_fare']} | "
                        f"{'+' if td>0 else ''}{mins_to_str(abs(td))} | "
                        f"Dep {dep2}"
                    ),
                }

    gn  = estimate_route_fare(segs, preferred_class='GN')
    dep = segs[0].get("dep_ampm","--") if segs else "--"
    return {
        "type":           "closest_available",
        "coach_class":    "GN",
        "fare":           gn["total_fare"],
        "fare_breakdown": gn["breakdown"],
        "savings":        pfare - gn["total_fare"],
        "time_diff_min":  0,
        "time_diff_str":  "Same route, same time",
        "total_time":     primary["total_time"],
        "total_minutes":  ptime,
        "transfers":      primary["transfers"],
        "segments":       segs,
        "summary": (
            f"No route found within Rs{budget}.\n"
            f"Cheapest available: Rs{gn['total_fare']} (GN class) — "
            f"Rs{gn['total_fare']-budget} over your budget."
        ),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
