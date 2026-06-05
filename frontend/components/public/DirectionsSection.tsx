// 공개 홈페이지 메인(/) 하단 "오시는 길" 섹션.
// 정적 안내 + 링크 중심(지도 API/외부 SDK 미연동). 기존 homepage.css 토큰/클래스를 재사용한다.
// 위치 기준: 시흥정왕동우체국 → 경기스마트고등학교 방향 약 150m → 한우리행정사사무소.
// 지도 타일을 복사하지 않고, 위치관계만 반영한 "간략 안내도"(CSS 도식)로 표현한다.
// 지도 링크는 상수로 분리 — 추후 링크만 교체 가능. #directions anchor로 바로 진입 가능.
const NAVER_MAP_URL = "https://naver.me/xXnSEq0b"; // 확정됨
// TODO: 카카오맵 링크 확정 시 KAKAO_MAP_URL 상수 추가 후 버튼 1개 더 노출 (이번 작업 범위 아님)

const PHONE = "01047028886";
const PHONE_DISPLAY = "010-4702-8886";
const ADDRESS = "경기도 시흥시 군서마을로 12, 101호";

// 주변 주요 지점(칩) — 우체국 출발 기준 + 인근 기준점
const NEARBY = ["시흥정왕동우체국", "경기스마트고사거리", "정왕시장 인근", "경기스마트고등학교 방향"];

// 찾아오는 방법 안내 — 우체국 기준, 경기스마트고 방향 약 150m
const FIND_TIPS = [
  "시흥정왕동우체국을 기준으로 경기스마트고등학교 방향으로 약 150m 이동합니다.",
  "군서마을로 도로변에서 한우리행정사사무소를 확인하실 수 있습니다.",
  "정확한 위치는 네이버지도에서 확인 가능합니다.",
];

// 간략 안내도 도식 — 우체국(출발) → 사무소(도착) → 경기스마트고사거리(경기스마트고 방향)
const MAP_CAPTION = "시흥정왕동우체국 → 경기스마트고등학교 방향 약 150m → 한우리행정사사무소";
const MAP_ARIA =
  "간략 안내도: 시흥정왕동우체국에서 경기스마트고등학교 방향으로 군서마을로를 따라 약 150m 이동하면 한우리행정사사무소가 있으며, 인근에 정왕시장과 경기스마트고사거리가 있습니다.";

export function DirectionsSection() {
  return (
    <section id="directions" className="section-alt" aria-labelledby="directions-title">
      <div className="container">
        <p className="section-label fade-in">Location</p>
        <h2 className="section-title fade-in" id="directions-title">오시는 길</h2>
        <p className="section-desc fade-in">
          한우리행정사사무소는 시흥정왕동우체국에서 경기스마트고등학교 방향으로
          약 150m 거리에 위치해 있습니다.
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

          {/* 찾아오는 방법 카드 */}
          <div className="dir-card dir-card-route fade-in">
            <h3 className="dir-route-title">찾아오는 방법</h3>
            <ul className="dir-bullets">
              {FIND_TIPS.map((t) => <li key={t}>{t}</li>)}
            </ul>
          </div>
        </div>

        {/* 간략 안내도 — 지도 타일 복사 없이 위치관계만 도식화 */}
        <div className="dir-map fade-in">
          <div className="dir-map-head">
            <span className="dir-map-badge">간략 안내도</span>
            <p className="dir-map-caption">{MAP_CAPTION}</p>
          </div>
          <div className="dir-map-canvas" role="img" aria-label={MAP_ARIA}>
            <span className="dir-map-ref">정왕시장</span>
            <div className="dir-map-row">
              <div className="dir-map-node">
                <span className="dir-map-node-name">시흥정왕동우체국</span>
                <span className="dir-map-node-tag">출발 기준점</span>
              </div>
              <div className="dir-map-link">
                <span className="dir-map-road">군서마을로 · 약 150m</span>
                <span className="dir-map-arrow" aria-hidden="true">→</span>
              </div>
              <div className="dir-map-node dir-map-node-dest">
                <span className="dir-map-node-name">한우리행정사사무소</span>
                <span className="dir-map-node-tag">도착</span>
              </div>
              <div className="dir-map-link dir-map-link-short">
                <span className="dir-map-arrow" aria-hidden="true">→</span>
              </div>
              <div className="dir-map-node dir-map-node-cross">
                <span className="dir-map-node-name">경기스마트고사거리</span>
                <span className="dir-map-node-tag">경기스마트고등학교 방향</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
