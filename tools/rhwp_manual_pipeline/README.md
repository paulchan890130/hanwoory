# rhwp_manual_pipeline

안정 위치에 재배치된 rhwp 기반 매뉴얼 처리 CLI. `backend/scripts/manual_update_local.py` 가 subprocess 로 호출.

## 의존성

`@rhwp/core` 와 `playwright-core` 를 **새로 설치하지 않음** — 직전 PoC 의 `analysis/rhwp_pdf_poc_260414/node_modules` 를 그대로 참조 (`_lib.mjs` 내 절대경로 import). 그래서 `tools/rhwp_manual_pipeline` 자체에 `node_modules` 는 없음. 디스크 절약 + version drift 방지.

만약 PoC 폴더가 삭제되면 본 CLI 가 동작 안 함 — `analysis/rhwp_pdf_poc_260414/` 보존 필요.

## CLI

```
node tools/rhwp_manual_pipeline/extract.mjs       --src <HWP> --label <label> --out-dir <DIR>
node tools/rhwp_manual_pipeline/generate_pdf.mjs  --src <HWP> --label <label> --out-dir <DIR>  [--skip-existing]
```

### extract.mjs
- 입력: HWP/HWPX 파일
- 출력:
  - `<OUT>/<label>_pages.jsonl` (rhwp_page_index, printed_page_no, text, text_hash, normalized_text_hash, keywords)
  - `<OUT>/page_text/<label>/p####.txt` (페이지별 평문)
  - `<OUT>/<label>_meta.json` (page_count, total_chars, elapsed)

### generate_pdf.mjs
- 입력: HWP/HWPX 파일
- 출력:
  - `<OUT>/pdf_pages/<label>/p####.pdf` (페이지별)
  - 합본은 별도 Python 머지 단계 (`backend/scripts/manual_update_local.py` 내부)
- `--skip-existing` 시 이미 존재하는 페이지 PDF 는 건너뜀 (resume 안전)
