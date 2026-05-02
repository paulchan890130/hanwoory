"""하이코리아 매뉴얼 페이지 구조 분석 — 첨부파일 다운로드 URL 패턴 찾기."""
import re, sys, io, urllib3
import requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

r = requests.get(URL, headers=HEADERS, timeout=20, verify=False)
print("status:", r.status_code, "len:", len(r.text))

text = r.text

# .hwp 링크
hwp_links = re.findall(r'href=["\']([^"\']*\.hwp[^"\']*)', text, re.IGNORECASE)
print("\n[HWP href links]")
for x in hwp_links[:10]:
    print(" -", x)

# 다운로드 함수 호출 패턴
fn_calls = re.findall(r"(fn[A-Za-z]*[Dd]ownload[A-Za-z]*\([^)]*\))", text)
print("\n[download function calls]")
for x in set(fn_calls[:10]):
    print(" -", x)

# 파일 정보 패턴
file_info = re.findall(r"FILE_SEQ['\"]?\s*[:=]\s*['\"]?(\d+)", text)
print("\n[FILE_SEQ values]:", file_info[:10])

# 첨부파일 영역 추출
attach_block = re.search(r"첨부.*?</tr>", text, re.DOTALL)
if attach_block:
    print("\n[attach block snippet]")
    print(attach_block.group(0)[:2000])
