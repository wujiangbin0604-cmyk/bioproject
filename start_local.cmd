@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if exist ".venv-local\Scripts\python.exe" (
  ".venv-local\Scripts\python.exe" genescope.py %*
  goto finish
)
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" genescope.py %*
  goto finish
)
py -3.14 --version >nul 2>&1
if not errorlevel 1 (
  py -3.14 genescope.py %*
  goto finish
)
python genescope.py %*
:finish
if errorlevel 1 (
  echo.
  echo See docs/LOCAL_USE.md for setup instructions.
  pause
)
endlocal
