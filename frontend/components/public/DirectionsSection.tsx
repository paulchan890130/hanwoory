// 공개 홈페이지 메인(/) 하단 "오시는 길" 섹션.
// 레이아웃: 상단 = 약도 이미지(전체폭) / 하단 = 핵심 정보 가로 바(사무소명·주소·전화·주변지점·버튼).
// 약도는 PPT에서 작성한 이미지(public/directions-map.png)를 그대로 사용한다(지도 API 미연동).
// 지도/전화 링크는 상수로 분리. #directions anchor로 바로 진입 가능.
const NAVER_MAP_URL = "https://naver.me/xXnSEq0b"; // 확정됨
const MAP_IMAGE = "/directions-map.png"; // PPT 기반 약도 (public/)

const PHONE = "01047028886";
const PHONE_DISPLAY = "010-4702-8886";
const ADDRESS = "경기도 시흥시 군서마을로 12, 101호";

// 주변 주요 지점(칩) — 우체국 출발 기준 + 인근 기준점
const NEARBY = ["시흥정왕동우체국", "경기스마트고사거리", "정왕시장 인근", "경기스마트고등학교 방향"];

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

        {/* 약도 (PPT 기반 이미지, 전체폭) */}
        <figure className="dir-map-figure fade-in">
          <img
            className="dir-map-img"
            src={MAP_IMAGE}
            alt="한우리행정사사무소 약도 — 시흥정왕동우체국에서 경기스마트고등학교 방향으로 군서마을로를 따라 약 150m"
            loading="lazy"
            width={4852}
            height={1681}
          />
        </figure>

        {/* 핵심 정보 — 약도 하단 가로 바 */}
        <div className="dir-bar fade-in">
          <div className="dir-bar-info">
            <div className="dir-bar-item">
              <span className="dir-bar-label">사무소명</span>
              <span className="dir-bar-value">한우리행정사사무소</span>
            </div>
            <span className="dir-bar-sep" aria-hidden="true" />
            <div className="dir-bar-item">
              <span className="dir-bar-label">주소</span>
              <span className="dir-bar-value">{ADDRESS}</span>
            </div>
            <span className="dir-bar-sep" aria-hidden="true" />
            <div className="dir-bar-item">
              <span className="dir-bar-label">전화</span>
              <a className="dir-bar-value dir-bar-tel" href={`tel:${PHONE}`}>{PHONE_DISPLAY}</a>
            </div>
          </div>

          <div className="dir-bar-places">
            {NEARBY.map((p) => (
              <span key={p} className="dir-chip">{p}</span>
            ))}
          </div>

          <div className="dir-bar-actions">
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
      </div>
    </section>
  );
}
