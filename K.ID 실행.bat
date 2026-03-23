@echo off
chcp 65001 >nul
setlocal

set "ROOT=C:\Users\66885\Documents\K.ID 출입국업무관리 실험"
set "FRONTEND=%ROOT%\frontend"

if not exist "%ROOT%" (
    echo [오류] 프로젝트 폴더를 찾을 수 없습니다.
    echo %ROOT%
    pause
    exit /b 1
)

if not exist "%ROOT%\backend\main.py" (
    echo [오류] backend\main.py 를 찾을 수 없습니다.
    pause
    exit /b 1
)

if not exist "%ROOT%\.venv\Scripts\activate.bat" (
    echo [오류] 가상환경 activate.bat 를 찾을 수 없습니다.
    echo %ROOT%\.venv\Scripts\activate.bat
    pause
    exit /b 1
)

if not exist "%FRONTEND%\package.json" (
    echo [오류] frontend\package.json 을 찾을 수 없습니다.
    pause
    exit /b 1
)

echo [1/3] 백엔드 실행...
start "K.ID Backend" cmd /k "cd /d \"%ROOT%\" && call \".venv\Scripts\activate.bat\" && python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"

timeout /t 2 /nobreak >nul

echo [2/3] 프론트엔드 실행...
start "K.ID Frontend" cmd /k "cd /d \"%FRONTEND%\" && npm run dev"

timeout /t 8 /nobreak >nul

echo [3/3] 브라우저 열기...
start "" "http://localhost:3000"

exit /b 0