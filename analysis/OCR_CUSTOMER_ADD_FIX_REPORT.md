# OCR Scan → Customer Add — Diagnosis & Fix Report

작성일: 2026-06-03 · 브랜치: `feat/postgres-foundation`

---

## Active frontend file

`frontend/app/(main)/scan/page.tsx`
- OCR 추출: `POST /api/scan-workspace/passport`, `/api/scan-workspace/arc`
- 고객 반영 버튼("고객관리 반영") → `handleSubmit()` → `registerMut` →
  **`POST /api/scan/register`** (line 1203).
- 성공 시 `qc.invalidateQueries({ queryKey: ["customers"] })` 로 목록 갱신 (이미 정상).
- 실패 시 `toast.error("고객 등록/업데이트 실패")` — **백엔드 실제 에러를 숨김** (요구사항 #11 위반, 같이 수정).

## Active backend endpoint

`backend/routers/scan.py` → `@router.post("/register")` `scan_register()` (line 376).
- main.py 등록: `app.include_router(scan.router, prefix="/api/scan")`.

## Root cause

**`scan_register` 는 다른 모든 고객 쓰기 경로와 달리 `pg_customers_enabled()` 플래그를
존중하지 않고, 항상 Google Sheets 경로(`tenant_service.get_worksheet` → `ws.append_row` /
`ws.batch_update`)로만 쓴다.**

비교:
| 엔드포인트 | PG 분기 | 쓰기 경로 |
|---|---|---|
| `customers.add_customer` (POST `/api/customers`) | ✅ `if pg_customers_enabled():` | `customer_pg_service.upsert_customer` |
| `customers.update_customer` (PUT) | ✅ | `customer_pg_service.upsert_customer` |
| `customers.append_delegation` | ✅ | `customer_pg_service.append_delegation` |
| **`scan.scan_register` (POST `/api/scan/register`)** | ❌ **없음** | **항상 `get_worksheet().append_row`** |

현재 런타임이 PostgreSQL(`FEATURE_PG_CUSTOMERS=true`)일 때:
- 고객 목록(`GET /api/customers`)은 **PG 에서** 읽는다(`list_customers`).
- 그런데 스캔 저장은 **Sheets/local-drive-mock 에** 쓴다.
- → 새 고객이 PG 에 없으므로 **목록·검색에 나타나지 않는다 = "고객이 추가되지 않음"**.

이것이 보고된 버그의 정확한 실패 지점이다(위 목록의 "legacy Google Sheets path called
instead of PG path"에 해당). 프론트 버튼/요청/캐시 무효화는 모두 정상이며, 백엔드가
잘못된 저장소에 쓰는 것이 원인이다.

## Exact fix plan

`scan_register` 맨 앞에 `add_customer`/`update_customer` 와 동일한 PG 분기를 추가한다.
PG 플래그가 켜져 있으면 `customer_pg_service` 로 라우팅하고, 꺼져 있으면 기존 Sheets
코드 경로를 **그대로** 사용(하위호환).

PG 분기 동작 (row-level only):
1. `_normalize_fields(body)` 로 alias/날짜 정규화 (빈 값은 자동 제외 — 요구 #8 충족).
2. `list_customers(tenant_id)` 에서 매칭:
   - 1순위: 여권번호(`여권`) 일치
   - 2순위: 등록증 앞(`등록증`) + 뒤(`번호`) 동시 일치
3. 매칭 시 → 기존 dict 에 비어있지 않은 incoming 필드만 병합 후 `upsert_customer`
   (동일 `고객ID` 1행만 UPDATE, 빈 OCR 값이 기존 값 덮어쓰지 않음). status=`updated`.
4. 미매칭 시 → `next_customer_id(tenant_id)` 로 안전한 ID 발급, `upsert_customer` 로
   1행 INSERT. status=`created`. `tenant_id` 는 `upsert_customer` 내부에서 설정.
5. 응답에 `고객ID` 포함 (요구 #10). 실패 시 예외 → 프론트가 실제 detail 표시.

프론트:
- `registerMut.onError` 를 수정해 `err.response.data.detail`(실제 백엔드 에러)을 표시.

## Files to change

1. `backend/routers/scan.py` — `scan_register` 에 PG 분기 추가 (Sheets 경로는 else 로 보존).
2. `frontend/app/(main)/scan/page.tsx` — `registerMut.onError` 실제 에러 메시지 표시.

> 신규 서비스/리팩터 없음. `customer_pg_service` 의 기존 `list_customers` /
> `next_customer_id` / `upsert_customer` 재사용. 고객 테이블 전체 재작성/리셋 없음.

## Tests to run

- 자동: `customer_pg_service` 를 SQLite 인메모리로 구동해 scan_register PG 분기 단위 검증
  (신규 생성 / 여권 매칭 업데이트 / ARC 매칭 업데이트 / 테넌트 격리 / 빈 payload 400).
- `python -m py_compile backend/routers/scan.py`
- `cd frontend && npx tsc --noEmit`
- Manual Update v1 회귀: synthetic test + 엔드포인트 스모크 재실행.
