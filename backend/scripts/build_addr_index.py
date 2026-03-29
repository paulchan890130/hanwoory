"""
Build compact address index from 주소정보 도로명 마스터 file.

Usage:
    python backend/scripts/build_addr_index.py PATH_TO_도로명마스터.txt

The 도로명 마스터 file is the nationwide single file (e.g. 도로명주소_전체분_전체분.txt)
from the 주소정보 DB zip distributed by the government.
Encoding: cp949  |  separator: |  columns: 17

Output: backend/data/addr_index.json  (~3MB)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def build(master_file: str) -> dict:
    roads: dict[str, set] = defaultdict(set)
    dongs: dict[str, set] = defaultdict(set)

    with open(master_file, encoding="cp949", errors="replace") as f:
        for line in f:
            cols = line.rstrip("\n").split("|")
            if len(cols) < 9:
                continue
            doroname = cols[1].strip()
            sido = cols[4].strip()
            sigungu = cols[6].strip()
            dongname = cols[8].strip()

            if not (doroname and sido and sigungu):
                continue
            key = f"{sido}|{sigungu}"
            roads[key].add(doroname)
            if dongname:
                dongs[key].add(dongname)

    return {
        "roads": {k: sorted(v) for k, v in roads.items()},
        "dongs": {k: sorted(v) for k, v in dongs.items()},
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python build_addr_index.py <도로명마스터.txt>", file=sys.stderr)
        sys.exit(1)

    idx = build(sys.argv[1])

    out = Path(__file__).parent.parent / "data" / "addr_index.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))

    total_roads = sum(len(v) for v in idx["roads"].values())
    total_dongs = sum(len(v) for v in idx["dongs"].values())
    size_kb = out.stat().st_size // 1024
    print(f"Regions: {len(idx['roads'])}, Roads: {total_roads}, Dongs: {total_dongs}")
    print(f"Saved to {out} ({size_kb}KB)")
