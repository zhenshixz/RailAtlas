@echo off
setlocal
cd /d "%~dp0"
title RailAtlas - Official Data Sync
where python >nul 2>nul
if errorlevel 1 goto no_python
python -m py_compile scripts\sync_data.py
if errorlevel 1 goto failed
echo Syncing public 12306 G/D/C trains and stops. Cached requests are resumed.
echo Enter date YYYY-MM-DD, or press Enter for today's date:
set "rail_date="
set /p "rail_date=Date: "
if not defined rail_date goto today
python -u scripts\sync_data.py --date "%rail_date%"
if errorlevel 1 goto failed
goto done
:today
python -u scripts\sync_data.py
if errorlevel 1 goto failed
goto done
:no_python
echo ERROR: Python 3.9 or newer is required.
goto done
:failed
echo ERROR: Sync incomplete. Cached data has been preserved. Run again to resume.
:done
pause
endlocal
