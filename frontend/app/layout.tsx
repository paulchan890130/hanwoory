import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";

export const metadata: Metadata = {
  title: {
    default: "한우리행정사사무소 | 출입국·체류·사증 전문",
    template: "%s | 한우리행정사사무소",
  },
  description:
    "출입국·체류자격·사증 관련 업무를 전문적으로 처리하는 행정사사무소입니다. 체류자격 연장·변경, 외국인등록, 사증 발급, 국적·귀화 업무 대행.",
  openGraph: {
    title: "한우리행정사사무소 | 출입국·체류·사증 전문",
    description:
      "체류자격 연장·변경, 외국인등록, 사증 업무 전문 행정사사무소. 경기도 시흥시.",
    type: "website",
    locale: "ko_KR",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <head>
        <link
          rel="stylesheet"
          as="style"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css"
        />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&family=Noto+Serif+KR:wght@500;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <Providers>
          {children}
          <Toaster richColors position="top-right" />
        </Providers>
      </body>
    </html>
  );
}
