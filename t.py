import json

with open("graph_enriched.json") as f:
    graph = json.load(f)

correct_path = ["Rajapur Road","Vaibhavwadi Rd","Kankavali","Sindhudurg","Kudal","ZARAP","Sawantwadi Road","Madure","Pernem","Thivim","Karmali","Verna","Madgaon"]

print("Train 10101 timing status:")
for i in range(len(correct_path)-1):
    src = correct_path[i]
    dst = correct_path[i+1]
    for e in graph.get(src, []):
        if e["train"] == "10101" and e["to"] == dst:
            has_t = e.get("departure_time") is not None
            dep = e.get("departure_time","?")
            arr = e.get("arrival_time","?")
            print(f"  {src} -> {dst}: {'✓ '+dep+' -> '+arr if has_t else '✗ NO TIMING'}")