"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import "./homepage.css";

interface Post {
  id: string;
  title: string;
  category: string;
  summary: string;
  content: string;
  created_at: string;
  updated_at: string;
  is_published: string;
}

export default function HomePage() {
  const navRef = useRef<HTMLElement>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("전체");
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);

  // Nav scroll shadow
  useEffect(() => {
    const onScroll = () => {
      navRef.current?.classList.toggle("scrolled", window.scrollY > 10);
    };
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Fade-in intersection observer
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) e.target.classList.add("visible");
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );
    document.querySelectorAll(".fade-in").forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [posts]);

  // Fetch published marketing posts
  useEffect(() => {
    fetch("/api/marketing/posts")
      .then((r) => (r.ok ? r.json() : []))
      .then((data: Post[]) => setPosts(Array.isArray(data) ? data : []))
      .catch(() => setPosts([]));
  }, []);

  const closeMenu = useCallback(() => setMobileOpen(false), []);

  const toggleFaq = (idx: number) =>
    setOpenFaq((prev) => (prev === idx ? null : idx));

  const fmtDate = (iso: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
  };

  const filteredPosts =
    activeTab === "전체"
      ? posts
      : posts.filter((p) => p.category === activeTab);

  const FAQS = [
    {
      q: "어떤 업무를 상담할 수 있나요?",
      a: "체류자격 연장·변경, 외국인등록, 사증(비자) 발급, 국적·귀화 등 출입국관리법 관련 민원 업무 전반에 대해 상담 가능합니다.",
    },
    {
      q: "방문 전에 무엇을 준비해야 하나요?",
      a: "여권, 외국인등록증 사본, 현재 체류자격 관련 서류를 준비해 주시면 상담이 원활합니다. 구체적인 준비 서류는 전화 상담 시 안내해 드립니다.",
    },
    {
      q: "비용은 어떻게 되나요?",
      a: "업무 종류와 난이도에 따라 다르므로, 상담 시 구체적인 비용을 안내해 드립니다. 상담 자체는 부담 없이 문의해 주시면 됩니다.",
    },
    {
      q: "중국어 상담도 가능한가요?",
      a: "네, 중국어 의사소통이 가능합니다. 중국 국적 의뢰인도 편하게 상담받으실 수 있습니다.",
    },
    {
      q: "기존에 업무를 의뢰한 경우 어떻게 확인하나요?",
      a: "기존 의뢰인은 상단의 '로그인' 버튼을 통해 업무 관리 시스템에 접속하여 진행 상황을 확인하실 수 있습니다.",
    },
  ];

  const CATEGORIES = [
    { key: "전체", label: "전체" },
    { key: "공지사항", label: "공지사항" },
    { key: "업무 안내", label: "업무 안내" },
    { key: "제도 변경", label: "제도 변경" },
    { key: "기타", label: "기타" },
  ];

  return (
    <>
      {/* NAV */}
      <nav className="nav" ref={navRef} role="navigation" aria-label="메인 내비게이션">
        <div className="nav-inner">
          <a href="#" className="nav-logo">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/hanwoori-logo-new.png" alt="한우리행정사사무소 로고" />
            <div className="nav-logo-text">
              한우리행정사사무소<span>출입국·체류·사증 전문</span>
            </div>
          </a>
          <div className="nav-links">
            <a href="#about">사무소 소개</a>
            <a href="#services">업무 분야</a>
            <a href="#board">업무 안내</a>
            <a href="#faq">FAQ</a>
            <a href="#contact">상담 문의</a>
            <Link href="/login" className="nav-login">로그인 →</Link>
          </div>
          <button
            className="nav-mobile-toggle"
            aria-label="메뉴 열기"
            onClick={() => setMobileOpen((v) => !v)}
          >
            <span /><span /><span />
          </button>
        </div>
      </nav>

      {/* MOBILE MENU */}
      <div className={`mobile-menu${mobileOpen ? " open" : ""}`}>
        <a href="#about" onClick={closeMenu}>사무소 소개</a>
        <a href="#services" onClick={closeMenu}>업무 분야</a>
        <a href="#board" onClick={closeMenu}>업무 안내</a>
        <a href="#faq" onClick={closeMenu}>FAQ</a>
        <a href="#contact" onClick={closeMenu}>상담 문의</a>
        <Link href="/login" style={{ color: "var(--gold-600)" }} onClick={closeMenu}>
          로그인 →
        </Link>
      </div>

      {/* HERO */}
      <header className="hero" role="banner">
        <div className="container">
          <div className="hero-badge">출입국 · 체류 · 사증 전문 행정사사무소</div>
          <h1>
            정확한 실무,<br /><em>체계적인 진행.</em>
          </h1>
          <p className="hero-sub">
            한우리행정사사무소는 출입국·체류자격·사증 관련 업무를<br />
            서류 검토부터 진행 관리까지 체계적으로 처리합니다.
          </p>
          <div className="hero-buttons">
            <a href="#contact" className="btn-primary">
              <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
              </svg>
              상담 문의
            </a>
            <Link href="/login" className="btn-secondary">
              <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" />
              </svg>
              기존 사용자 로그인
            </Link>
          </div>
          <div className="hero-trust">
            <span className="hero-trust-item">체류자격 연장·변경</span>
            <span className="hero-trust-sep">|</span>
            <span className="hero-trust-item">외국인등록·사증 업무</span>
            <span className="hero-trust-sep">|</span>
            <span className="hero-trust-item">서류 검토·진행 관리</span>
          </div>
        </div>
      </header>

      {/* ABOUT */}
      <section id="about" className="section-alt" aria-labelledby="about-title">
        <div className="container">
          <div className="about-grid">
            <div className="about-text fade-in">
              <p className="section-label">About</p>
              <h2 className="section-title" id="about-title">
                출입국 실무 중심의<br />행정사사무소입니다
              </h2>
              <p className="section-desc">
                한우리행정사사무소는 외국인의 체류자격, 사증, 국적 관련 업무를
                전문적으로 다루는 행정사사무소입니다.
                단순 서류 대행이 아니라, 출입국관리법에 기반한 절차 이해와
                정확한 서류 검토, 일정 관리까지 체계적으로 진행합니다.
              </p>
              <div className="about-highlights">
                <div className="about-highlight">
                  <div className="about-highlight-icon">📋</div>
                  <div>
                    <h4>법령 기반 실무</h4>
                    <p>출입국관리법과 시행규칙에 근거한 정확한 업무 처리</p>
                  </div>
                </div>
                <div className="about-highlight">
                  <div className="about-highlight-icon">🌐</div>
                  <div>
                    <h4>중국어 상담 가능</h4>
                    <p>중국어 의사소통이 가능하여 중국 국적 의뢰인 대응에 강점</p>
                  </div>
                </div>
                <div className="about-highlight">
                  <div className="about-highlight-icon">⚙️</div>
                  <div>
                    <h4>디지털 업무 프로세스</h4>
                    <p>자체 업무관리 시스템을 활용한 체계적 진행과 누락 방지</p>
                  </div>
                </div>
              </div>
            </div>
            <div className="about-visual fade-in">
              <h3>정식 등록 행정사사무소</h3>
              <p>
                행정사법에 따라 등록된 정식 행정사사무소로서,<br />
                법적 책임 하에 업무를 수행합니다.<br /><br />
                소재지: 경기도 시흥시<br />
                전화: 031-488-8862
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES */}
      <section id="services" aria-labelledby="services-title">
        <div className="container">
          <p className="section-label fade-in">Services</p>
          <h2 className="section-title fade-in" id="services-title">주요 업무 분야</h2>
          <p className="section-desc fade-in">출입국·체류·사증 관련 주요 민원 업무를 전문적으로 처리합니다.</p>
          <div className="services-grid">
            {[
              { icon: "📄", title: "체류자격 연장", desc: "체류기간 만료 전 연장 신청 대행. 필요 서류 검토부터 접수까지 체계적으로 진행합니다." },
              { icon: "🔄", title: "체류자격 변경", desc: "현재 체류자격에서 다른 자격으로의 변경 신청. 요건 검토와 서류 준비를 지원합니다." },
              { icon: "🪪", title: "외국인등록", desc: "최초 외국인등록, 변경신고, 체류지 변경 등 외국인등록 관련 업무를 처리합니다." },
              { icon: "✈️", title: "사증(비자) 관련", desc: "사증발급인정서, 사증발급 신청 등 사증 관련 민원 업무를 대행합니다." },
              { icon: "🇰🇷", title: "국적·귀화", desc: "일반귀화, 간이귀화, 특별귀화, 국적회복 등 국적 관련 절차를 안내하고 진행합니다." },
              { icon: "📑", title: "서류 준비 및 행정 대응", desc: "각종 출입국 관련 소명자료, 추가 제출 서류 준비 및 행정기관 대응을 지원합니다." },
            ].map((svc) => (
              <article key={svc.title} className="service-card fade-in">
                <div className="service-icon">{svc.icon}</div>
                <h3>{svc.title}</h3>
                <p>{svc.desc}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* STRENGTHS */}
      <section id="strengths" className="section-alt" aria-labelledby="strengths-title">
        <div className="container">
          <p className="section-label fade-in">Why Us</p>
          <h2 className="section-title fade-in" id="strengths-title">한우리행정사사무소의 차별점</h2>
          <p className="section-desc fade-in">형식적인 서류 접수가 아니라, 실질적인 업무 완결을 목표로 합니다.</p>
          <div className="strengths-grid">
            {[
              { num: "01", title: "정식 행정사 사무소", desc: "행정사법에 따라 등록된 사무소에서 법적 책임 하에 업무를 처리합니다." },
              { num: "02", title: "출입국 실무 기준", desc: "출입국관리법 기준으로 서류를 검토하고, 실무 절차에 맞게 진행합니다." },
              { num: "03", title: "체계적 진행 관리", desc: "일정, 서류, 진행 상황을 시스템으로 관리하여 누락과 지연을 방지합니다." },
              { num: "04", title: "정확성과 대응력", desc: "추가 서류 요청, 보완 통보 등 돌발 상황에 빠르게 대응합니다." },
            ].map((s) => (
              <div key={s.num} className="strength-item fade-in">
                <div className="strength-num">{s.num}</div>
                <h4>{s.title}</h4>
                <p>{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PROCESS */}
      <section id="process" aria-labelledby="process-title">
        <div className="container">
          <p className="section-label fade-in">Process</p>
          <h2 className="section-title fade-in" id="process-title">업무 진행 방식</h2>
          <p className="section-desc fade-in">상담부터 완료까지 체계적인 절차로 진행합니다.</p>
          <div className="process-grid">
            {[
              { step: "STEP 01", title: "상담 및 요건 확인", desc: "의뢰인의 체류 상황과 목적을 파악하고, 필요한 절차와 요건을 안내합니다." },
              { step: "STEP 02", title: "서류 검토 및 준비", desc: "필요 서류를 확인하고, 누락이나 오류 없이 준비될 수 있도록 검토합니다." },
              { step: "STEP 03", title: "접수 및 진행 관리", desc: "접수 후 진행 상황을 관리하고, 추가 요청이나 보완 사항에 대응합니다." },
              { step: "STEP 04", title: "결과 확인 및 안내", desc: "결과를 확인하고 의뢰인에게 안내합니다. 후속 조치가 필요한 경우 함께 안내합니다." },
            ].map((p) => (
              <div key={p.step} className="process-step fade-in">
                <div className="process-step-num">{p.step}</div>
                <h4>{p.title}</h4>
                <p>{p.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* BOARD */}
      <section id="board" className="section-alt" aria-labelledby="board-title">
        <div className="container">
          <p className="section-label fade-in">Notice</p>
          <h2 className="section-title fade-in" id="board-title">업무 안내</h2>
          <p className="section-desc fade-in">
            출입국·체류 관련 주요 안내사항과 업무 정보를 정리하여 제공합니다.
          </p>
          <div className="board-tabs fade-in">
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                className={`board-tab${activeTab === c.key ? " active" : ""}`}
                onClick={() => setActiveTab(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="board-list fade-in">
            {filteredPosts.length === 0 ? (
              <div className="board-empty">등록된 게시물이 없습니다.</div>
            ) : (
              filteredPosts.map((post) => (
                <Link
                  key={post.id}
                  href={`/board/${post.id}`}
                  className="board-item"
                  style={{ textDecoration: "none", color: "inherit", display: "block" }}
                >
                  <div className="board-item-row">
                    <span className="board-category">{post.category || "공지"}</span>
                    <span className="board-title">{post.title}</span>
                    <span className="board-date">{fmtDate(post.updated_at || post.created_at)}</span>
                    <span className="board-chevron">→</span>
                  </div>
                  {post.summary && (
                    <p className="board-summary-preview">{post.summary}</p>
                  )}
                </Link>
              ))
            )}
          </div>
          {filteredPosts.length > 0 && (
            <div className="fade-in" style={{ textAlign: "center", marginTop: 28 }}>
              <Link href="/board" className="board-more-link">
                전체 안내 보기 →
              </Link>
            </div>
          )}
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" aria-labelledby="faq-title">
        <div className="container">
          <p className="section-label fade-in">FAQ</p>
          <h2 className="section-title fade-in" id="faq-title">자주 묻는 질문</h2>
          <p className="section-desc fade-in">업무 의뢰 전 자주 문의하시는 내용을 정리했습니다.</p>
          <div className="faq-list">
            {FAQS.map((item, idx) => {
              const isOpen = openFaq === idx;
              return (
                <div key={idx} className="faq-item">
                  <button
                    className="faq-question"
                    onClick={() => toggleFaq(idx)}
                    aria-expanded={isOpen}
                  >
                    {item.q}
                    <span style={{
                      fontSize: "1.2rem", color: "var(--gold-400)",
                      fontWeight: 400, flexShrink: 0, marginLeft: 12,
                      lineHeight: 1,
                    }}>
                      {isOpen ? "−" : "+"}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="faq-answer" role="region">
                      {item.a}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA / CONTACT */}
      <section id="contact" className="cta-section" aria-labelledby="contact-title">
        <div className="container">
          <p className="section-label fade-in">Contact</p>
          <h2 className="section-title fade-in" id="contact-title">상담 및 문의</h2>
          <p className="section-desc fade-in">
            출입국·체류 관련 업무에 대해 궁금한 점이 있으시면<br />
            부담 없이 연락해 주세요.
          </p>
          <div className="hero-buttons fade-in">
            <a href="tel:031-488-8862" className="btn-primary">
              <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
              </svg>
              전화 상담하기
            </a>
          </div>
          <div className="cta-info fade-in">
            <div className="cta-info-item">
              <div className="cta-info-label">전화번호</div>
              <div className="cta-info-value">031-488-8862</div>
            </div>
            <div className="cta-info-item">
              <div className="cta-info-label">소재지</div>
              <div className="cta-info-value">경기도 시흥시</div>
            </div>
            <div className="cta-info-item">
              <div className="cta-info-label">상담 가능 시간</div>
              <div className="cta-info-value">평일 09:00 ~ 18:00</div>
            </div>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer role="contentinfo">
        <div className="footer-inner">
          <div>
            <div className="footer-brand-area">
              <div className="footer-brand">한우리<span>행정사사무소</span></div>
            </div>
            <p className="footer-desc">
              출입국·체류자격·사증 관련 업무를 전문적으로 처리하는 행정사사무소입니다.<br />
              행정사법에 따라 등록된 정식 사무소에서 법적 책임 하에 업무를 수행합니다.
            </p>
            <p className="footer-desc" style={{ fontSize: "0.73rem", opacity: 0.5 }}>
              사업자등록번호: 213-12-37464<br />
              &copy; 2026 한우리행정사사무소. All rights reserved.
            </p>
          </div>
          <div className="footer-col">
            <h4>바로가기</h4>
            <a href="#about">사무소 소개</a>
            <a href="#services">업무 분야</a>
            <a href="#board">업무 안내</a>
            <a href="#faq">자주 묻는 질문</a>
            <a href="#contact">상담 문의</a>
          </div>
          <div className="footer-col">
            <h4>기타</h4>
            <Link href="/login">로그인 (기존 사용자)</Link>
            <a href="tel:031-488-8862">전화 문의: 031-488-8862</a>
          </div>
        </div>
        <div className="footer-bottom">
          <span>한우리행정사사무소 · 경기도 시흥시</span>
          <span>사업자등록번호: 213-12-37464</span>
        </div>
      </footer>
    </>
  );
}
