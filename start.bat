@echo off
setlocal
cd /d "%~dp0"

echo [1/2] Building frontend...
pushd frontend
call npm run build
if errorlevel 1 (
    echo Frontend build failed.
    popd
    exit /b 1
)
popd

echo [2/2] Starting backend in production mode...
set APP_ENV=prod
pushd backend
python run.py
popd
