"""
Address correction service using the 주소정보 도로명 master index.

Loads backend/data/addr_index.json (3MB, built from 도로명코드 master file)
and uses prefix-based matching to correct OCR-extracted ARC address strings.

The index covers 16 시도 × 256 regions × 172K unique road names.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

# ── index path ────────────────────────────────────────────────────────────────
_INDEX_PATH = Path(__file__).parent.parent / "data" / "addr_index.json"

_index: dict | None = None
_index_lock = threading.Lock()

# All valid 시도 names (stable, hard-coded for fast prefix matching)
_SIDOS: tuple[str, ...] = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "강원도",
    "충청북도", "충청남도",
    "전북특별자치도", "전라북도", "전라남도",
    "경상북도", "경상남도",
    "제주특별자치도", "제주도",
)
# Legacy name → current DB name
_SIDO_ALIAS: dict[str, str] = {
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "제주도": "제주특별자치도",
}

# Dong/ri suffixes — token ending with these is treated as a jibun address
_JIBUN_SUFFIX_RE = re.compile(r"[동리읍면]$")


# ── index loading ─────────────────────────────────────────────────────────────

def _load_index() -> dict:
    global _index
    if _index is not None:
        return _index
    with _index_lock:
        if _index is not None:
            return _index
        if not _INDEX_PATH.exists():
            _index = {"roads": {}, "dongs": {}}
            return _index
        try:
            with open(_INDEX_PATH, encoding="utf-8") as f:
                _index = json.load(f)
        except Exception:
            _index = {"roads": {}, "dongs": {}}
    return _index


# ── address parsing helpers ────────────────────────────────────────────────────

def _extract_sido(addr: str) -> tuple[str, str]:
    """Return (sido, remainder) — sido normalised to DB name, or ('', addr)."""
    addr = addr.strip()
    for s in _SIDOS:
        if addr.startswith(s):
            return _SIDO_ALIAS.get(s, s), addr[len(s):].strip()
    return "", addr


def _extract_sigungu(
    sido: str, remainder: str, roads: dict, dongs: dict
) -> tuple[str, str, str]:
    """Return (key, sigungu_text, remainder_after_sigungu) or ('','',remainder)."""
    tokens = remainder.split()
    # Try longest match first (up to 3 tokens = "수원시 장안구" etc.)
    for n in range(min(3, len(tokens)), 0, -1):
        candidate = " ".join(tokens[:n])
        key = f"{sido}|{candidate}"
        if key in roads or key in dongs:
            return key, candidate, " ".join(tokens[n:]).strip()
    # Fallback: single token ending in 시/군/구 — look up any matching sub-key
    if tokens and tokens[0][-1:] in ("시", "군", "구"):
        prefix = f"{sido}|{tokens[0]}"
        sub_keys = [k for k in roads if k == prefix or k.startswith(prefix + " ")]
        if not sub_keys:
            sub_keys = [k for k in dongs if k == prefix or k.startswith(prefix + " ")]
        if sub_keys:
            return sub_keys[0], tokens[0], " ".join(tokens[1:]).strip()
    return "", "", remainder


def _split_road_bldnum(text: str) -> tuple[str, str]:
    """
    Split 'road_name 5' or 'road_name5' → ('road_name', '5').
    Peels off a trailing digit-only or digit-dash-digit building number.
    """
    text = text.strip()
    if not text:
        return text, ""
    tokens = text.split()
    # Last token is a building number
    if len(tokens) >= 2 and re.match(r"^\d+(-\d+)?$", tokens[-1]):
        return " ".join(tokens[:-1]), tokens[-1]
    # Embedded: "조원로45" or "군서로12번길5"
    m = re.match(r"^(.+?(?:대로|번길|로\d+번길|로|길|도))(\d+(?:-\d+)?)(.*)$", text)
    if m:
        road = m.group(1).strip()
        bld = m.group(2).strip()
        extra = m.group(3).strip()
        return road, (bld + " " + extra).strip() if extra else bld
    return text, ""


def _prefix_match(token: str, candidates: list[str]) -> str | None:
    """
    Find the best candidate sharing the longest prefix with token.

    Rules:
    - Exact match always wins.
    - Otherwise, find the longest prefix (≥ 2 chars) shared with any candidate.
    - The shared prefix must cover ≥ 50% of the shorter of the two strings.
    - Among ties pick the candidate closest in length to token.
    - Return None if no sufficiently long shared prefix is found.

    This approach corrects OCR suffix errors (로→도, 대로→도 etc.) without
    false-matching completely different road names.
    """
    if not token or not candidates:
        return None
    if token in candidates:
        return token

    best_cand: str | None = None
    best_prefix_len = 0

    for cand in candidates:
        # Find length of common prefix
        pl = 0
        for a, b in zip(token, cand):
            if a == b:
                pl += 1
            else:
                break
        if pl < 2:
            continue
        min_len = min(len(token), len(cand))
        # Shared prefix must be >= 60% of the shorter string to avoid
        # matching unrelated road names that merely share a short prefix.
        if pl < min_len * 0.6:
            continue
        if pl > best_prefix_len or (
            pl == best_prefix_len
            and abs(len(cand) - len(token)) < abs(len(best_cand) - len(token))
        ):
            best_prefix_len = pl
            best_cand = cand

    # Precision gate: shared prefix must cover >= 60% of token length
    if best_cand and best_prefix_len >= max(2, int(len(token) * 0.6)):
        return best_cand
    return None


# ── public API ────────────────────────────────────────────────────────────────

def correct_address(ocr_addr: str) -> str:
    """
    Attempt to correct an OCR-extracted ARC address using the national
    road-name index.  Returns the corrected address if a plausible match
    is found; otherwise returns the original string unchanged.

    Examples
    --------
    "울산광역시 중구 다운도 1"         →  "울산광역시 중구 다운로 1"
    "서울특별시 강남구 테헤란도 100"   →  "서울특별시 강남구 테헤란로 100"
    "울산광역시 중구 학성동 11-1"      →  unchanged  (exact jibun dong)
    "경기도 수원시 팔달구 조원로 45"   →  unchanged  (road not in 팔달구)
    """
    if not ocr_addr:
        return ocr_addr

    idx = _load_index()
    if not idx.get("roads") and not idx.get("dongs"):
        return ocr_addr

    roads = idx["roads"]
    dongs = idx["dongs"]

    # ① Extract 시도
    sido, rem1 = _extract_sido(ocr_addr)
    if not sido:
        return ocr_addr

    # ② Extract 시군구
    key, sigungu_text, rem2 = _extract_sigungu(sido, rem1, roads, dongs)
    if not key:
        return ocr_addr

    # ③ Split road/dong token and building number
    road_token, bld_part = _split_road_bldnum(rem2)
    if not road_token:
        return ocr_addr

    # ④ Jibun address branch: token ends in 동/리/읍/면
    if _JIBUN_SUFFIX_RE.search(road_token):
        candidate_dongs = dongs.get(key, [])
        # Exact match → address is already valid, return unchanged
        if road_token in candidate_dongs:
            return ocr_addr
        # Prefix-based correction of dong name
        corrected = _prefix_match(road_token, candidate_dongs)
        if corrected:
            parts = [sido, sigungu_text, corrected]
            if bld_part:
                parts.append(bld_part)
            return " ".join(parts)
        return ocr_addr

    # ⑤ Road address branch
    candidate_roads = roads.get(key, [])
    # Exact match → already correct
    if road_token in candidate_roads:
        return ocr_addr
    # Prefix-based correction within the matched region
    corrected = _prefix_match(road_token, candidate_roads)
    if corrected:
        parts = [sido, sigungu_text, corrected]
        if bld_part:
            parts.append(bld_part)
        return " ".join(parts)

    # ⑥ Sibling-region fallback: OCR may have omitted 구 (e.g., "수원시" instead of
    #    "수원시 장안구").  Try all sub-keys of the same 시/군.
    #    Collects ALL sibling matches then picks the best (highest prefix overlap).
    base_sigungu = sigungu_text.split()[0]  # e.g., "수원시" from "수원시 장안구"
    prefix_key = f"{sido}|{base_sigungu}"
    siblings = [
        k for k in roads
        if k != key and (k == prefix_key or k.startswith(prefix_key + " "))
    ]

    best_sibling: tuple[str, str, int] | None = None  # (sibling_key, corrected_road, score)
    for sibling_key in siblings:
        sibling_roads = roads.get(sibling_key, [])
        if road_token in sibling_roads:
            # Exact match → score = length of road name (prefer longer exact matches)
            best_sibling = (sibling_key, road_token, len(road_token) + 1000)
            break  # exact match wins immediately
        corrected = _prefix_match(road_token, sibling_roads)
        if corrected:
            # Score by shared prefix length
            pl = sum(1 for a, b in zip(road_token, corrected) if a == b)
            if best_sibling is None or pl > best_sibling[2]:
                best_sibling = (sibling_key, corrected, pl)

    if best_sibling:
        sibling_key, best_road, _ = best_sibling
        sibling_sigungu = sibling_key.split("|", 1)[1]
        parts = [sido, sibling_sigungu, best_road]
        if bld_part:
            parts.append(bld_part)
        return " ".join(parts)

    return ocr_addr
