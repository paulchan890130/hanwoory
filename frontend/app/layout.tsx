import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";

export const metadata: Metadata = {
  title: {
    default: "한우리행정사사무소 | 시흥·정왕 출입국 행정사",
    template: "%s | 한우리행정사사무소",
  },
  description:
    "경기도 시흥시 정왕동 인근 한우리행정사사무소입니다. 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 가족초청, 중국 공증·아포스티유 업무를 안내합니다.",
  openGraph: {
    title: "한우리행정사사무소 | 시흥·정왕 출입국 행정사",
    description:
      "경기도 시흥시 정왕동 인근 한우리행정사사무소입니다. 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 가족초청, 중국 공증·아포스티유 업무를 안내합니다.",
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
