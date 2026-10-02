@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
  start "" "http://127.0.0.1:8765/"
  echo Chord Follower is already running at http://127.0.0.1:8765/
  echo Close the server window to stop it.
  pause
  exit /b 0
)
echo Starting Chord Follower at http://127.0.0.1:8765/
echo Close this window to stop.
start "" powershell -NoProfile -WindowStyle Hidden -Command "$deadline = (Get-Date).AddSeconds(15); while ((Get-Date) -lt $deadline) { try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); Start-Process 'http://127.0.0.1:8765/'; exit 0 } catch { Start-Sleep -Milliseconds 200 } }"
python -m mdchord serve
if errorlevel 1 pause
