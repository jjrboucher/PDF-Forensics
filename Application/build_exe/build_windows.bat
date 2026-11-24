@echo off
REM Builds the one-folder version as Application\PDF_Forensics_Suite\ and removes
REM every temporary build artefact. Requires Python 3.9+ on PATH.
setlocal
cd /d "%~dp0\.."
python -m venv .build-venv || goto :err
call .build-venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller psutil || goto :err
pyinstaller build_exe\pdf_forensics.spec --noconfirm --clean || goto :err
call deactivate
if not exist dist\PDF_Forensics_Suite\PDF_Forensics_Suite.exe goto :err
if exist PDF_Forensics_Suite rmdir /s /q PDF_Forensics_Suite
move /Y dist\PDF_Forensics_Suite PDF_Forensics_Suite >nul
REM ---- clean up ----
rmdir /s /q .build-venv build dist 2>nul
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo.
echo Built: %CD%\PDF_Forensics_Suite\PDF_Forensics_Suite.exe
PDF_Forensics_Suite\PDF_Forensics_Suite.exe --version
echo SHA-256:
certutil -hashfile PDF_Forensics_Suite\PDF_Forensics_Suite.exe SHA256
goto :eof
:err
echo BUILD FAILED. Temporary files were left in place for troubleshooting.
exit /b 1
