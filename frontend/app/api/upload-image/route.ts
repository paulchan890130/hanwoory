/**
 * Next.js API Route — 이미지 업로드 프록시
 * rewrites()를 통한 multipart 포워딩이 불안정하므로
 * 이 라우트에서 FormData를 명시적으로 파싱 후 FastAPI로 재전송한다.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const authHeader = request.headers.get("Authorization");
    if (!authHeader) {
      return Response.json({ detail: "인증이 필요합니다." }, { status: 401 });
    }

    let formData: FormData;
    try {
      formData = await request.formData();
    } catch {
      return Response.json({ detail: "FormData 파싱 실패 — 이미지 파일을 확인하세요." }, { status: 400 });
    }

    const file = formData.get("file") as File | null;
    if (!file) {
      return Response.json({ detail: "file 필드가 없습니다." }, { status: 400 });
    }

    const backendUrl = process.env.API_URL || "http://127.0.0.1:8000";

    const outbound = new FormData();
    outbound.append("file", file, file.name);

    const res = await fetch(`${backendUrl}/api/marketing/admin/upload-image`, {
      method: "POST",
      headers: { Authorization: authHeader },
      body: outbound,
    });

    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (e) {
    console.error("[upload-image] proxy error:", e);
    return Response.json({ detail: "업로드 처리 중 서버 오류가 발생했습니다." }, { status: 500 });
  }
}
