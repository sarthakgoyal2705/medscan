"""Convert the 253k-row 1mg-derived CSV into a compact runtime index.

    python data/import_bulk.py

Reads  data/indian_medicine_data.csv  (github.com/junioralive/Indian-Medicine-Dataset)
Writes data/bulk.json:
    {"sigs":  [[sig_string, cheapest_brand, cheapest_price, n_products], ...],
     "items": [[name, salt_str, [salt_keys], pack, price, sig_idx], ...]}

Discontinued products and rows without a parseable price/composition are dropped.
"""

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app import salts  # noqa: E402

SRC = HERE / "indian_medicine_data.csv"
OUT = HERE / "bulk.json"


def main() -> None:
    items = []
    sig_ids: dict[str, int] = {}
    sigs: list[list] = []  # [sig_string, cheapest_name, cheapest_price, count]

    kept = dropped = 0
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["Is_discontinued"].strip().upper() == "TRUE":
                dropped += 1
                continue
            try:
                price = float(row["price(₹)"])
            except (ValueError, KeyError):
                dropped += 1
                continue
            comps = []
            for col in ("short_composition1", "short_composition2"):
                c = salts.parse_component(row.get(col) or "")
                if c:
                    comps.append(c)
            if not comps or price <= 0:
                dropped += 1
                continue

            name = row["name"].strip()
            salt_str = " + ".join(
                (f"{k.title()} ({s})" if s else k.title()) for k, s in comps)
            keys = sorted({k for k, _ in comps})
            pack = row["pack_size_label"].strip()
            sig = salts.signature(comps)

            idx = sig_ids.get(sig)
            if idx is None:
                idx = sig_ids[sig] = len(sigs)
                sigs.append([sig, name, price, 0])
            sigs[idx][3] += 1
            if price < sigs[idx][2]:
                sigs[idx][1], sigs[idx][2] = name, price

            items.append([name, salt_str, keys, pack, price, idx])
            kept += 1

    OUT.write_text(json.dumps({"sigs": sigs, "items": items},
                              ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    mb = OUT.stat().st_size / 1e6
    print(f"kept {kept}, dropped {dropped}, {len(sigs)} distinct salt signatures, bulk.json {mb:.1f} MB")


if __name__ == "__main__":
    main()
