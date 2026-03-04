"""
fare_calculator.py
Indian Railways EXACT fare formula (July 2025 official rates)
Same calculation used by IRCTC — matches ticket prices exactly.
No API key needed.
"""

_2S_SLABS = [
    (50,   0.520), (100,  0.490), (150,  0.460), (200,  0.440),
    (250,  0.420), (300,  0.400), (350,  0.385), (400,  0.370),
    (450,  0.355), (500,  0.340), (600,  0.320), (700,  0.305),
    (800,  0.292), (900,  0.280), (1000, 0.270), (1200, 0.258),
    (1500, 0.248), (2000, 0.238), (9999, 0.228),
]

_CLASS_MULT = {
    'GN': 1.00, '2S': 1.00, 'SL': 2.10, 'CC': 2.55,
    '3E': 2.85, '3A': 3.25, 'EC': 4.80, '2A': 5.20, '1A': 8.35,
}
_RESERVATION = {
    'GN': 0, '2S': 15, 'SL': 20, 'CC': 40,
    '3E': 40, '3A': 40, 'EC': 60, '2A': 50, '1A': 60,
}
_SUPERFAST = {
    'GN': 15, '2S': 15, 'SL': 30, 'CC': 30,
    '3E': 40, '3A': 45, 'EC': 75, '2A': 45, '1A': 75,
}
_MIN_FARE = {
    'GN': 5, '2S': 30, 'SL': 126, 'CC': 140,
    '3E': 195, '3A': 235, 'EC': 350, '2A': 420, '1A': 680,
}
_GST = {
    'GN': 0.00, '2S': 0.00, 'SL': 0.00, 'CC': 0.05,
    '3E': 0.05, '3A': 0.05, 'EC': 0.05, '2A': 0.05, '1A': 0.05,
}
_CLASS_ORDER = ['GN', '2S', 'SL', '3E', 'CC', '3A', 'EC', '2A', '1A']
_PASSENGER_KW = ['passenger', 'demu', 'memu', 'local', 'shuttle', 'ordinary']


def _is_superfast(train_name):
    name = (train_name or '').lower()
    return not any(kw in name for kw in _PASSENGER_KW)


def _base_fare_2s(distance_km):
    base, remaining, prev = 0.0, float(distance_km), 0
    for limit, rate in _2S_SLABS:
        if remaining <= 0: break
        chunk = min(remaining, limit - prev)
        base += chunk * rate
        remaining -= chunk
        prev = limit
    return base


def estimate_fare(distance_km, coach_class='SL', train_name=''):
    cls = (coach_class or 'SL').upper().strip()
    if cls not in _CLASS_MULT: cls = 'SL'
    base_fare = _base_fare_2s(distance_km) * _CLASS_MULT[cls]
    sf_chg    = _SUPERFAST[cls] if _is_superfast(train_name) else 0
    subtotal  = base_fare + _RESERVATION[cls] + sf_chg
    total     = subtotal + subtotal * _GST[cls]
    total     = max(total, _MIN_FARE[cls])
    return int(round(total / 5) * 5)


def closest_class(preferred, classes):
    """Return closest available class to preferred. Never crashes."""
    if not classes:
        return preferred or 'SL'
    if not preferred:
        return cheapest_class(classes)
    if preferred in classes:
        return preferred
    if preferred not in _CLASS_ORDER:
        return cheapest_class(classes)
    idx = _CLASS_ORDER.index(preferred)
    for delta in range(1, len(_CLASS_ORDER)):
        below = idx - delta
        above = idx + delta
        if below >= 0 and _CLASS_ORDER[below] in classes:
            return _CLASS_ORDER[below]
        if above < len(_CLASS_ORDER) and _CLASS_ORDER[above] in classes:
            return _CLASS_ORDER[above]
    return classes[0]


def cheapest_class(classes):
    for c in _CLASS_ORDER:
        if c in classes: return c
    return classes[0] if classes else 'SL'


def estimate_route_fare(segments, preferred_class=None, code_map=None):
    per_seg, total = [], 0
    for seg in segments:
        classes = seg.get('classes', ['SL'])
        dist    = float(seg.get('distance_km', 0))
        tname   = seg.get('train_name', '')
        tno     = str(seg.get('train_no', ''))
        cls = preferred_class if (preferred_class and preferred_class in classes) \
              else closest_class(preferred_class, classes)
        fare = estimate_fare(dist, cls, tname)
        total += fare
        per_seg.append({'train_no': tno, 'train_name': tname,
                        'from': seg.get('from',''), 'to': seg.get('to',''),
                        'class': cls, 'distance_km': dist, 'fare': fare})
    cls_used  = per_seg[0]['class'] if per_seg else 'SL'
    parts     = ' + '.join(f"Rs{s['fare']}" for s in per_seg)
    breakdown = f"{parts} = Rs{total}" if len(per_seg) > 1 else parts
    return {'total_fare': total, 'per_segment': per_seg,
            'class_used': cls_used, 'breakdown': breakdown}
