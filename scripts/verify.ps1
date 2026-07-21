# verify.ps1 — 통합 로컬 검증 (Windows / PowerShell 7+)
#
# 운영 배포·migration 을 실행하지 않는다. 순수 검증만 수행하고 단계별 성공/실패를 집계한다.
#   - git 상태
#   - python compileall (backend)
#   - pytest (backend/tests) — SQLite 기반, 운영 DB 불필요
#   - alembic 단일 head (파일 기준, DB 접속 없음)
#   - frontend: npm 설치 상태 / tsc / lint / build
#
# 사용: 프로젝트 루트에서  .\scripts\verify.ps1
# 종료코드: 하나라도 실패하면 1, 모두 통과하면 0.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 파이썬 실행기 선택(.venv 우선).
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$results = [ordered]@{}

function Invoke-Step {
    param([string]$Name, [scriptblock]$Action)
    Write-Host ""
    Write-Host "===== $Name =====" -ForegroundColor Cyan
    & $Action
    $ok = ($LASTEXITCODE -eq 0)
    $script:results[$Name] = $ok
    if ($ok) { Write-Host "[PASS] $Name" -ForegroundColor Green }
    else     { Write-Host "[FAIL] $Name (exit $LASTEXITCODE)" -ForegroundColor Red }
}

# ── git 상태(정보용 — 실패로 치지 않음) ──
Write-Host "===== git status =====" -ForegroundColor Cyan
git status --short --branch
git diff --stat

# ── 백엔드 ──
Invoke-Step "backend: compileall" { & $py -m compileall backend -q }
Invoke-Step "backend: pytest" { & $py -m pytest backend/tests -q }
Invoke-Step "backend: alembic single head" {
    & $py -c "from alembic.config import Config; from alembic.script import ScriptDirectory; h=ScriptDirectory.from_config(Config('alembic.ini')).get_heads(); print('heads:', h); import sys; sys.exit(0 if len(h)==1 else 1)"
}

# ── 프론트엔드 ──
Push-Location (Join-Path $root "frontend")
if (-not (Test-Path "node_modules")) {
    Invoke-Step "frontend: npm ci" { npm ci }
} else {
    Write-Host "===== frontend: node_modules present (skip npm ci) =====" -ForegroundColor DarkGray
}
Invoke-Step "frontend: tsc" { npx tsc --noEmit }
Invoke-Step "frontend: lint" { npm run lint }
Invoke-Step "frontend: build" { npm run build }
Pop-Location

# ── 요약 ──
Write-Host ""
Write-Host "================ VERIFY SUMMARY ================" -ForegroundColor Cyan
$failed = @()
foreach ($k in $results.Keys) {
    $v = $results[$k]
    $tag = if ($v) { "PASS" } else { "FAIL" }
    $color = if ($v) { "Green" } else { "Red" }
    Write-Host ("{0,-32} {1}" -f $k, $tag) -ForegroundColor $color
    if (-not $v) { $failed += $k }
}
Write-Host "==============================================="
if ($failed.Count -gt 0) {
    Write-Host ("실패 단계: {0}" -f ($failed -join ", ")) -ForegroundColor Red
    exit 1
}
Write-Host "모든 단계 통과" -ForegroundColor Green
exit 0
