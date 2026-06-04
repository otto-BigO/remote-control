@echo off
REM Build the server as a Windows .exe. Run on Windows with Python 3 installed.
REM Output: dist\rc-server.exe
cd /d "%~dp0"

pip install pyinstaller pynput mss pillow
pyinstaller --noconfirm --onefile --name rc-server server.py

echo.
echo Built: dist\rc-server.exe
echo Put an rc_config.json next to it (see rc_config.example.json), then run it.
