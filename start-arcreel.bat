@echo off
REM ArcReel 本地启动器：后端 1241 + 前端 15173（各开一个独立控制台窗口，关窗口即停服务）
start "ArcReel Backend" /D "d:\self111\ArcReel-main" powershell -NoProfile -Command "uv run uvicorn server.app:app --port 1241 --host 127.0.0.1 --loop none"
start "ArcReel Frontend" /D "d:\self111\ArcReel-main\frontend" powershell -NoProfile -Command "pnpm dev"
echo ArcReel 后端(1241) 与前端(15173) 已在各自窗口启动。
