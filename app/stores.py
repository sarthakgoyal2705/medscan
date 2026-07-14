"""Jan Aushadhi kendra locator.

18.6k government generic-medicine stores, geolocated to their pincode centroid.
Nearest-store queries by coordinates (browser geolocation) or by pincode.
"""

import json
import math
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "stores.json"

if DATA_PATH.exists():
    _STORES = json.loads(DATA_PATH.read_text(encoding="utf-8"))["stores"]
else:
    _STORES = []

# pincode -> centroid (any store's coords in that pincode), for pincode queries
_PIN_LL = {s[5]: (s[6], s[7]) for s in _STORES}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def available() -> bool:
    return bool(_STORES)


def resolve_pincode(pincode: str) -> tuple[float, float] | None:
    return _PIN_LL.get(pincode.strip())


def nearest(lat: float, lng: float, limit: int = 10) -> list[dict]:
    scored = sorted(
        ((_haversine_km(lat, lng, s[6], s[7]), s) for s in _STORES),
        key=lambda x: x[0])
    out = []
    for dist, s in scored[:limit]:
        code, name, address, district, state, pincode, slat, slng = s
        out.append({
            "code": code,
            "name": name,
            "address": address,
            "district": district,
            "state": state,
            "pincode": pincode,
            "distance_km": round(dist, 1),
            "maps_url": f"https://www.google.com/maps/search/?api=1&query="
                        f"{'Jan Aushadhi Kendra ' + address + ' ' + district + ' ' + pincode}".replace(" ", "+"),
        })
    return out
