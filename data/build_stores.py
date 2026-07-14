"""Merge the Jan Aushadhi kendra list with pincode coordinates.

    python data/build_stores.py

Reads:  data/kendras-lookup.json  (pincode -> kendras; janaushdhi.pages.dev, ~18.9k stores)
        data/pincode.csv          (All India Pincode Directory w/ lat-lng, data.gov.in)
Writes: data/stores.json          {"stores": [[code, name, address, district, state,
                                               pincode, lat, lng], ...]}

Coordinates are the centroid of the pincode's post offices — accurate to the
neighbourhood, which is what "find my nearest store" needs.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    coords: dict[str, list] = defaultdict(list)
    with open(HERE / "pincode.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                lat, lng = float(row["Latitude"]), float(row["Longitude"])
            except (ValueError, TypeError):
                continue
            # some rows have junk coords (0, or swapped); India bounding box check
            if 6.0 <= lat <= 38.0 and 68.0 <= lng <= 98.0:
                coords[row["Pincode"].strip()].append((lat, lng))

    centroids = {pc: (round(sum(a for a, _ in pts) / len(pts), 5),
                      round(sum(b for _, b in pts) / len(pts), 5))
                 for pc, pts in coords.items()}

    kendras = json.loads((HERE / "kendras-lookup.json").read_text(encoding="utf-8"))
    stores, missing = [], 0
    for pincode, entries in kendras.items():
        ll = centroids.get(pincode)
        for k in entries:
            if ll is None:
                missing += 1
                continue
            stores.append([k["code"], k["name"], k["address"], k["district"],
                           k["state"], pincode, ll[0], ll[1]])

    (HERE / "stores.json").write_text(
        json.dumps({"stores": stores}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    print(f"{len(stores)} stores with coordinates ({missing} skipped, no pincode match); "
          f"{len(centroids)} pincode centroids available")


if __name__ == "__main__":
    main()
