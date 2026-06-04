// 공개 홈페이지 메인(/) 하단 "오시는 길" 섹션.
// 정적 안내 + 링크 중심(지도 API/외부 SDK 미연동). 기존 homepage.css 토큰/클래스를 재사용한다.
// 지도 링크는 상수로 분리 — 추후 링크만 교체 가능.
const NAVER_MAP_URL = "https://naver.me/xXnSEq0b"; // 확정됨
// TODO: 카카오맵 링크 확정 시 KAKAO_MAP_URL 상수 추가 후 버튼 1개 더 노출 (이번 작업 범위 아님)

const PHONE = "01047028886";
const PHONE_DISPLAY = "010-4702-8886";
const ADDRESS = "경기도 시흥시 군서마을로 12, 101호";

const NEARBY = ["정왕시장 인근", "시흥정왕동우체국 인근", "경기스마트고등학교 인근"];

const ROUTE_STEPS = ["큰도로 진입", "작은도로 방향", "한우리행정사사무소"];

const FIND_TIPS = [
  "큰도로 쪽에서 진입 후 작은도로 방향으로 들어오시면 사무실을 찾기 쉽습니다.",
  "정왕시장과 시흥정왕동우체국을 기준으로 보시면 위치 파악이 쉽습니다.",
  "경기스마트고등학교 인근 방향에서도 접근 가능합니다.",
  "사무실은 작은도로 앞쪽에 위치해 가까이 오시면 비교적 쉽게 확인하실 수 있습니다.",
];

export function DirectionsSection() {
  return (
    <section id="directions" className="section-alt" aria-labelledby="directions-title">
      <div className="container">
        <p className="section-label fade-in">Location</p>
        <h2 className="section-title fade-in" id="directions-title">오시는 길</h2>
        <p className="section-desc fade-in">
          정왕시장·시흥정왕동우체국 인근에 위치한 한우리행정사사무소입니다.
          큰도로에서 작은도로 방향으로 들어오시면 비교적 쉽게 찾으실 수 있습니다.
        </p>

        <div className="dir-grid">
          {/* 핵심 정보 카드 */}
          <div className="dir-card fade-in">
            <div className="dir-rows">
              <div className="dir-row">
                <span className="dir-row-label">사무소명</span>
                <span className="dir-row-value">한우리행정사사무소</span>
              </div>
              <div className="dir-row">
                <span className="dir-row-label">주소</span>
                <span className="dir-row-value">{ADDRESS}</span>
              </div>
              <div className="dir-row">
                <span className="dir-row-label">전화</span>
                <a className="dir-row-value dir-tel" href={`tel:${PHONE}`}>{PHONE_DISPLAY}</a>
              </div>
            </div>

            <div className="dir-places-area">
              <span className="dir-row-label">주변 주요 지점</span>
              <div className="dir-places">
                {NEARBY.map((p) => (
                  <span key={p} className="dir-chip">{p}</span>
                ))}
              </div>
            </div>

            <div className="dir-actions">
              <a
                className="btn-primary"
                href={NAVER_MAP_URL}
                target="_blank"
                rel="noopener noreferrer"
              >
                <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                네이버지도에서 보기
              </a>
              <a className="btn-secondary" href={`tel:${PHONE}`}>
                <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
                </svg>
                전화하기
              </a>
            </div>
          </div>

          {/* 찾아오는 길 카드 */}
          <div className="dir-card dir-card-route fade-in">
            <h3 className="dir-route-title">찾아오는 길</h3>
            <div className="dir-route" aria-label="큰도로에서 작은도로를 거쳐 사무실로 오는 경로">
              {ROUTE_STEPS.map((step, i) => (
                <div key={step} style={{ width: "100%" }}>
                  <div className={`dir-route-step${i === ROUTE_STEPS.length - 1 ? " dir-route-dest" : ""}`}>
                    <span className="dir-route-num">{i + 1}</span>
                    {step}
                  </div>
                  {i < ROUTE_STEPS.length - 1 && <div className="dir-route-arrow" aria-hidden="true">↓</div>}
                </div>
              ))}
            </div>
            <ul className="dir-bullets">
              {FIND_TIPS.map((t) => <li key={t}>{t}</li>)}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
