@echo off
rem Builds dist\FluidWorx and FluidWorx-<version>-windows-x64-portable.zip
cd /d "%~dp0\.."
python -m PyInstaller packaging\fluidworx.spec --noconfirm --distpath dist --workpath build || exit /b 1
copy LICENSE dist\FluidWorx\ >nul
for /f %%v in ('python -c "import fluidworx; print(fluidworx.__version__)"') do set VERSION=%%v
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\FluidWorx -DestinationPath dist\FluidWorx-%VERSION%-windows-x64-portable.zip" || exit /b 1
