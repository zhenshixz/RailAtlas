@echo off
setlocal
set "rail_exit=0"
cd /d "%~dp0"
title RailAtlas - China Railway Map
where python >nul 2>nul
if errorlevel 1 goto no_python
where node >nul 2>nul
if errorlevel 1 goto no_node
python -c "import sys; assert sys.version_info >= (3,9), 'Python 3.9+ required'"
if errorlevel 1 goto failed
node -e "const v=process.versions.node.split('.').map(Number); if(v[0]<22||(v[0]===22&&v[1]<12))process.exit(1)"
if errorlevel 1 goto old_node
if exist node_modules\vite\bin\vite.js goto installed
echo Installing dependencies...
call npm install --no-audit --no-fund
if errorlevel 1 goto failed
:installed
echo Checking backend syntax...
python -m py_compile server.py scripts\sync_data.py scripts\auto_repair.py
if errorlevel 1 goto failed
if "%~1"=="--check" goto done
python -c "import urllib.request,json; r=json.load(urllib.request.urlopen('http://127.0.0.1:8790/api/health',timeout=2)); exit(0 if r.get('name')=='RailAtlas' else 1)" >nul 2>nul
if not errorlevel 1 goto running
echo Building frontend...
call npm run build
if errorlevel 1 goto failed
echo Starting server. Local and LAN addresses appear below.
python -u server.py --port 8790
if errorlevel 1 goto failed
goto done
:running
echo RailAtlas is already running. Open one of these addresses:
python -c "from server import addresses; print('\n'.join(addresses(8790)))"
goto done
:no_python
set "rail_exit=1"
echo ERROR: Python 3.9 or newer is required.
goto done
:no_node
set "rail_exit=1"
echo ERROR: Node.js 22.12 or newer is required.
goto done
:old_node
set "rail_exit=1"
echo ERROR: Please update Node.js to 22.12 or newer.
goto done
:failed
set "rail_exit=1"
echo ERROR: Startup failed. Review the messages above.
:done
if "%~1"=="--check" exit /b %rail_exit%
echo.
pause
endlocal
