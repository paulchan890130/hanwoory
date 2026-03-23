import os
import sys
import time
import subprocess
import webbrowser

ROOT     = os.path.dirname(os.path.abspath(__file__))
BACKEND  = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")

CREATE_NEW_CONSOLE = 0x00000010   # Windows 전용 플래그

def start_window(title, cmd, cwd):
    """새 콘솔 창을 열고 cmd 실행. 창은 프로세스가 살아있는 동안 유지."""
    full_cmd = f'cmd /k "title {title} && {cmd}"'
    subprocess.Popen(
        full_cmd,
        cwd=cwd,
        shell=True,
        creationflags=CREATE_NEW_CONSOLE,
    )

print("=" * 40)
print("  K.ID 출입국업무관리 - 서버 구동")
print("=" * 40)
print(f"  루트  : {ROOT}")
print(f"  백엔드: {BACKEND}")
print(f"  프론트: {FRONTEND}")
print()

# 경로 존재 확인
if not os.path.isdir(BACKEND):
    print(f"[오류] backend 폴더를 찾을 수 없습니다:\n  {BACKEND}")
    input("엔터를 누르면 종료합니다...")
    sys.exit(1)

if not os.path.isdir(FRONTEND):
    print(f"[오류] frontend 폴더를 찾을 수 없습니다:\n  {FRONTEND}")
    input("엔터를 누르면 종료합니다...")
    sys.exit(1)

print("[1/3] 백엔드 서버 시작 (FastAPI :8000)...")
start_window(
    "K.ID Backend :8000",
    "python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000",
    BACKEND,
)

print("[2/3] 프론트엔드 서버 시작 (Next.js :3000)...")
start_window(
    "K.ID Frontend :3000",
    "npm run dev",
    FRONTEND,
)

print("[3/3] 서버 준비 대기 중... (10초)")
for i in range(10, 0, -1):
    print(f"  {i}초 후 브라우저 열림...", end="\r")
    time.sleep(1)

print()
print("  브라우저 열기: http://localhost:3000/login")
webbrowser.open("http://localhost:3000/login")

print()
print("=" * 40)
print("  백엔드  : http://localhost:8000")
print("  프론트  : http://localhost:3000")
print("  종료    : 각 터미널 창을 닫으세요")
print("=" * 40)
input("\n이 창은 닫아도 됩니다. [엔터] ")
