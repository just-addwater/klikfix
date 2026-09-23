@echo off
rem Build dist\KlikFix.exe (one file, no console).
rem Needs Python 3.10+ and: py -3 -m pip install pyinstaller
setlocal
set HERE=%~dp0
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "KlikFix" --icon "%HERE%icon.ico" ^
  --add-data "%HERE%icon.ico;." ^
  --distpath "%HERE%dist" --workpath "%HERE%build" --specpath "%HERE%build" ^
  "%HERE%klikfix.pyw" || exit /b 1
echo Built: %HERE%dist\KlikFix.exe
