# K.ID SaaS 설치 및 실행 가이드 (초심자용)

> 이 문서는 처음 설치하는 분들을 위해 하나하나 순서대로 설명합니다.
> 모르는 부분은 그냥 복사-붙여넣기만 하시면 됩니다.

---

## 전체 흐름 이해하기

기존: 컴퓨터에서 Streamlit 앱 직접 실행
새 버전: 백엔드(Python) + 프론트엔드(웹사이트) 두 개를 실행

```
[백엔드] Python FastAPI 서버 (포트 8000) ←→ [프론트엔드] Next.js 웹사이트 (포트 3000)
           ↕
    Google Sheets (데이터 저장, 기존과 동일)
```

개발할 때는 내 컴퓨터에서 둘 다 실행하면 됩니다.
완성되면 인터넷에 올려서 어디서든 접속 가능하게 됩니다.

---

## STEP 1. 필요한 프로그램 확인

PowerShell을 열고 아래 명령어를 하나씩 입력해서 확인합니다.
(시작 버튼 → "PowerShell" 검색 → 실행)

```powershell
python --version
```
→ `Python 3.12.x` 이런 식으로 나오면 OK

```powershell
node --version
```
→ `v20.x.x` 이런 식으로 나오면 OK
→ 없으면 https://nodejs.org 에서 "LTS" 버전 설치

```powershell
npm --version
```
→ `10.x.x` 이런 식으로 나오면 OK

---

## STEP 2. 백엔드 Python 패키지 설치

PowerShell에서 아래 명령어를 **그대로 복사해서** 실행합니다.

```powershell
pip install -r "C:\Users\66885\Documents\K.ID 출입국업무관리\backend\requirements.txt"
```

설치가 끝날 때까지 기다립니다. (수분 소요, 중간에 뭔가 많이 출력되는 건 정상)

완료되면 이렇게 나옵니다:
```
Successfully installed fastapi-0.x.x uvicorn-0.x.x ...
```

---

## STEP 3. 프론트엔드 Node.js 패키지 설치

PowerShell에서 아래 명령어를 실행합니다.

```powershell
cd "C:\Users\66885\Documents\K.ID 출입국업무관리\frontend"
npm install
```

설치가 끝날 때까지 기다립니다. (수분 소요)

완료되면 이렇게 나옵니다:
```
added 500 packages in 30s
```

---

## STEP 4. 환경 변수 파일 만들기

### 4-1. 프론트엔드 환경 변수

`C:\Users\66885\Documents\K.ID 출입국업무관리\frontend\` 폴더에
`.env.local` 이라는 파일을 만들고 아래 내용을 붙여넣으세요.

(메모장으로 새 파일 만들기 → 내용 입력 → 파일명을 `.env.local` 로 저장)

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

> **주의**: 파일명이 `.env.local` 입니다. (앞에 점이 있어요)
> 메모장에서 저장할 때 "파일 형식"을 "모든 파일"로 바꾸고 저장해야 합니다.

### 4-2. 백엔드 환경 변수

백엔드는 기존 앱과 같은 구글 서비스 계정 키를 그대로 사용합니다.
별도 설정 필요 없이 기존 파일(`hanwoory-9eaa1a4c54d7.json`)이 있으면 됩니다.

---

## STEP 5. 백엔드 실행하기

PowerShell 창을 **새로 하나** 열고 아래 명령어를 실행합니다.
(이 창은 백엔드 전용으로 계속 열어두세요)

```powershell
cd "C:\Users\66885\Documents\K.ID 출입국업무관리"
uvicorn backend.main:app --reload --port 8000
```

아래처럼 나오면 성공입니다:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Application startup complete.
```

> 브라우저에서 http://localhost:8000/docs 접속하면
> API 목록을 볼 수 있습니다. (정상 작동 확인용)

---

## STEP 6. 프론트엔드 실행하기

PowerShell 창을 **또 하나 새로** 열고 아래 명령어를 실행합니다.
(이 창도 계속 열어두세요)

```powershell
cd "C:\Users\66885\Documents\K.ID 출입국업무관리\frontend"
npm run dev
```

아래처럼 나오면 성공입니다:
```
  ▲ Next.js 14.x.x
  - Local:        http://localhost:3000
  - Ready in 2.1s
```

---

## STEP 7. 접속 확인

브라우저(크롬 등)에서 http://localhost:3000 으로 접속합니다.

로그인 화면이 나오면 성공입니다! 🎉

기존 아이디/비밀번호로 로그인하면 됩니다.

---

## 매일 실행할 때는?

컴퓨터를 켤 때마다 PowerShell 2개를 열고:

**창 1 (백엔드):**
```powershell
cd "C:\Users\66885\Documents\K.ID 출입국업무관리"
uvicorn backend.main:app --reload --port 8000
```

**창 2 (프론트엔드):**
```powershell
cd "C:\Users\66885\Documents\K.ID 출입국업무관리\frontend"
npm run dev
```

그 다음 http://localhost:3000 접속.

---

## 오류가 날 때 확인사항

### "uvicorn을 찾을 수 없습니다" 오류
→ STEP 2 (pip install)가 제대로 안 된 것입니다. 다시 실행하세요.

### "포트 8000이 이미 사용 중" 오류
→ 이미 백엔드가 실행 중입니다. 기존 PowerShell 창에서 Ctrl+C로 종료 후 다시 실행.

### "포트 3000이 이미 사용 중" 오류
→ 마찬가지로 프론트엔드가 이미 실행 중입니다.

### 로그인이 안 될 때
→ 백엔드(포트 8000)가 실행 중인지 확인하세요.
→ http://localhost:8000/health 접속했을 때 `{"status":"ok"}` 나오면 정상.

### 구글 시트 연결 오류
→ `hanwoory-9eaa1a4c54d7.json` 파일이 프로젝트 폴더에 있는지 확인하세요.

---

## 나중에 인터넷에 올리고 싶을 때 (선택사항)

로컬에서 잘 돌아가는 것을 확인한 후에 진행합니다.

### 백엔드 → Railway (무료)
1. https://railway.app 가입 (구글 계정으로 간편 가입)
2. "New Project" → "Deploy from GitHub" 클릭
3. 이 프로젝트 GitHub에 올린 후 연결
4. Settings → Environment Variables에 아래 추가:
   - `JWT_SECRET_KEY` = 아무 긴 영문 문자열 (예: `mySecretKey123456789abcdef`)
   - `HANWOORY_ENV` = `server`
5. Settings → "Add Secret File" → `/etc/secrets/hanwoory-9eaa1a4c54d7.json` 에 키 파일 내용 붙여넣기
6. 배포 완료 후 URL 복사 (예: `https://kid-app.railway.app`)

### 프론트엔드 → Vercel (무료)
1. https://vercel.com 가입 (구글 계정으로 간편 가입)
2. "New Project" → GitHub 저장소 선택
3. **Root Directory** 칸에 `frontend` 입력 (중요!)
4. Environment Variables에 추가:
   - `NEXT_PUBLIC_API_URL` = Railway에서 받은 백엔드 URL
5. Deploy 클릭

배포 완료 후 Vercel이 주는 URL(예: `https://kid-app.vercel.app`)로 어디서든 접속 가능!

---

## 폴더 구조 참고

```
K.ID 출입국업무관리/
│
├── app.py              ← 기존 Streamlit 앱 (그대로 유지됨)
├── config.py           ← 설정 (공용)
├── core/               ← 구글 시트 연결 코드 (공용)
│
├── backend/            ← 새로운 백엔드 (여기를 uvicorn으로 실행)
│   ├── main.py
│   ├── requirements.txt
│   └── routers/
│
└── frontend/           ← 새로운 웹 화면 (여기를 npm으로 실행)
    ├── package.json
    └── app/
        ├── (auth)/login/    ← 로그인 화면
        └── (main)/
            ├── dashboard/   ← 홈 화면
            ├── tasks/       ← 업무 관리
            ├── customers/   ← 고객 관리
            ├── daily/       ← 일일 결산
            ├── memos/       ← 메모장
            ├── board/       ← 게시판
            ├── scan/        ← OCR 스캔
            └── admin/       ← 계정 관리 (관리자만)
```
