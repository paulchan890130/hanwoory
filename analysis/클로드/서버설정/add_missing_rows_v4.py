"""
누락 행 추가 v4 — M1-0357 ~ M1-0363
D-1 EXTEND/REENTRY, F-3 REGISTRATION/REENTRY, F-5 REGISTRATION/REENTRY, G-1 REENTRY
"""
import sys, openpyxl, os
sys.stdout.reconfigure(encoding='utf-8')

현재폴더 = os.path.dirname(os.path.abspath(__file__))
엑셀경로 = os.path.join(현재폴더, '..', '정리.xlsx')

BASIS_FILE = "260310 체류민원 자격별 안내 매뉴얼.pdf"

NEW_ROWS = [
    # ── D-1 문화예술 ──────────────────────────────────────────────
    {
        'row_id': 'M1-0357',
        'domain': '체류민원',
        'major_action_std': '체류기간 연장허가',
        'action_type': 'EXTEND',
        'business_name': '문화예술',
        'detailed_code': 'D-1',
        'overview_short': '문화예술(D-1) 체류기간 연장허가',
        'form_docs': '통합신청서 | 위임장 | 업무수행확인서 | 숙소제공확인서 | 외국인 직업 신고서 | 여권유효기간범위내체류확인서(해당자)',
        'supporting_docs': '연수기관이 작성한 연수일정표 | 체류지 입증서류(임대차계약서 등)',
        'exceptions_summary': '',
        'fee_rule': '기본 6만원',
        'basis_file': BASIS_FILE,
        'basis_section': '문화예술(D-1) > 체류기간연장허가',
        'status': '정상',
    },
    {
        'row_id': 'M1-0358',
        'domain': '체류민원',
        'major_action_std': '재입국허가',
        'action_type': 'REENTRY',
        'business_name': '문화예술',
        'detailed_code': 'D-1',
        'overview_short': '문화예술(D-1) 재입국허가',
        'form_docs': '통합신청서 | 위임장',
        'supporting_docs': '',
        'exceptions_summary': '출국한 날부터 1년 이내 재입국하고자 하는 자는 재입국허가 면제',
        'fee_rule': '단수 3만원 | 복수 5만원',
        'basis_file': BASIS_FILE,
        'basis_section': '재입국허가 공통|문화예술(D-1) > 재입국허가',
        'status': '정상',
    },
    # ── F-3 동반 ──────────────────────────────────────────────────
    {
        'row_id': 'M1-0359',
        'domain': '체류민원',
        'major_action_std': '외국인등록',
        'action_type': 'REGISTRATION',
        'business_name': '동반',
        'detailed_code': 'F-3',
        'overview_short': '동반(F-3) 외국인등록',
        'form_docs': '통합신청서 | 위임장 | 표준규격사진 1매',
        'supporting_docs': '부 또는 모의 외국인등록증 | 가족관계 입증서류(출생증명서 등) | 체류지 입증서류(임대차계약서 등)',
        'exceptions_summary': '',
        'fee_rule': '외국인등록증 발급 및 재발급 3만5천원',
        'basis_file': BASIS_FILE,
        'basis_section': '동반(F-3) > 외국인등록',
        'status': '정상',
    },
    {
        'row_id': 'M1-0360',
        'domain': '체류민원',
        'major_action_std': '재입국허가',
        'action_type': 'REENTRY',
        'business_name': '동반',
        'detailed_code': 'F-3',
        'overview_short': '동반(F-3) 재입국허가',
        'form_docs': '통합신청서 | 위임장',
        'supporting_docs': '',
        'exceptions_summary': '출국한 날부터 1년 이내 재입국하고자 하는 자는 재입국허가 면제',
        'fee_rule': '단수 3만원 | 복수 5만원',
        'basis_file': BASIS_FILE,
        'basis_section': '재입국허가 공통|동반(F-3) > 재입국허가|재입국허가 등 업무처리 지침',
        'status': '정상',
    },
    # ── F-5 영주 ──────────────────────────────────────────────────
    {
        'row_id': 'M1-0361',
        'domain': '체류민원',
        'major_action_std': '외국인등록',
        'action_type': 'REGISTRATION',
        'business_name': '영주',
        'detailed_code': 'F-5',
        'overview_short': '영주(F-5) 외국인등록',
        'form_docs': '통합신청서 | 위임장 | 표준규격사진 1매',
        'supporting_docs': '체류지 입증서류(임대차계약서, 부동산 등기부등본 등)',
        'exceptions_summary': '',
        'fee_rule': '외국인등록증 발급 및 재발급 3만5천원',
        'basis_file': BASIS_FILE,
        'basis_section': '영주(F-5) > 외국인등록',
        'status': '정상',
    },
    {
        'row_id': 'M1-0362',
        'domain': '체류민원',
        'major_action_std': '재입국허가',
        'action_type': 'REENTRY',
        'business_name': '영주',
        'detailed_code': 'F-5',
        'overview_short': '영주(F-5) 재입국허가',
        'form_docs': '통합신청서 | 위임장',
        'supporting_docs': '',
        'exceptions_summary': '출국한 날부터 1년 이내 재입국하고자 하는 자는 재입국허가 면제 / 복수재입국허가 가능',
        'fee_rule': '단수 3만원 | 복수 5만원',
        'basis_file': BASIS_FILE,
        'basis_section': '재입국허가 공통|영주(F-5) > 재입국허가|재입국허가 등 업무처리 지침',
        'status': '정상',
    },
    # ── G-1 기타 ──────────────────────────────────────────────────
    {
        'row_id': 'M1-0363',
        'domain': '체류민원',
        'major_action_std': '재입국허가',
        'action_type': 'REENTRY',
        'business_name': '기타',
        'detailed_code': 'G-1',
        'overview_short': '기타(G-1) 재입국허가',
        'form_docs': '통합신청서 | 위임장',
        'supporting_docs': '',
        'exceptions_summary': '출국한 날부터 1년 이내 재입국하고자 하는 자는 재입국허가 면제',
        'fee_rule': '수수료 없음 (재입국허가)',
        'basis_file': BASIS_FILE,
        'basis_section': '재입국허가 공통|기타(G-1) > 재입국허가',
        'status': '정상',
    },
]

HEADERS = ['row_id', 'domain', 'major_action_std', 'action_type', 'business_name',
           'detailed_code', 'overview_short', 'form_docs', 'supporting_docs',
           'exceptions_summary', 'fee_rule', 'basis_file', 'basis_section', 'status']


def main():
    print('=' * 60)
    print('  누락 행 추가 스크립트 v4')
    print('=' * 60)

    if not os.path.exists(엑셀경로):
        print(f'[오류] 파일을 찾을 수 없습니다: {엑셀경로}')
        return

    print(f'[1/3] 엑셀 파일 열기...')
    wb = openpyxl.load_workbook(엑셀경로)
    ws = wb['MASTER_ROWS']

    existing_ids = set(ws.cell(r, 1).value for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value)
    print(f'  기존 행 수: {len(existing_ids)}')

    print(f'[2/3] 새 행 추가...')
    added = 0
    skipped = 0
    for row_data in NEW_ROWS:
        rid = row_data['row_id']
        if rid in existing_ids:
            print(f'  SKIP: {rid} (이미 존재)')
            skipped += 1
            continue
        ws.append([row_data.get(h, '') or '' for h in HEADERS])
        print(f'  ADD: {rid} | {row_data["detailed_code"]} {row_data["action_type"]}')
        added += 1

    print(f'[3/3] 저장...')
    wb.save(엑셀경로)
    print()
    print(f'  추가: {added}건, 건너뜀(중복): {skipped}건')
    print(f'  저장 완료: {엑셀경로}')
    print()
    print('다음 단계:')
    print('  1. python 엑셀_json_변환.py')
    print('  2. cp 서버설정/immigration_guidelines_db_v2.json backend/data/')
    print('  3. python backend/scripts/migrate_guidelines_v2.py')


if __name__ == '__main__':
    main()
