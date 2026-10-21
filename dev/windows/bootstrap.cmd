@echo off
setlocal
set "PYTHONUTF8=1"
set "A7C2_ROOT=%~dp0..\.."
if defined A7C2_PYTHON goto explicit_python
if exist "%A7C2_ROOT%\.venv\Scripts\python.exe" goto local_python
py -3 -c "import sys,struct; sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto py_launcher
python -c "import sys,struct; sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto python_path
echo Python 3.10+ 64-bit was not found. Install Python with the Windows launcher.
echo Or set A7C2_PYTHON to the full path of python.exe.
exit /b 1
:explicit_python
"%A7C2_PYTHON%" "%A7C2_ROOT%\src\launcher.py" %*
exit /b %errorlevel%
:local_python
"%A7C2_ROOT%\.venv\Scripts\python.exe" "%A7C2_ROOT%\src\launcher.py" %*
exit /b %errorlevel%
:py_launcher
py -3 "%A7C2_ROOT%\src\launcher.py" %*
exit /b %errorlevel%
:python_path
python "%A7C2_ROOT%\src\launcher.py" %*
exit /b %errorlevel%
