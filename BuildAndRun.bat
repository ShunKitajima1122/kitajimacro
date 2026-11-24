@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "STAGE=%CD%\obj\QuickPublish"
set "INSTALL=%LOCALAPPDATA%\KeyMacro\App"

where dotnet.exe >nul 2>&1
if errorlevel 1 (
    echo .NET 10 SDK is required. Install it from https://dotnet.microsoft.com/download/dotnet/10.0
    goto :failed
)

echo Building KeyMacro...
dotnet publish KeyMacro.csproj -c Release --no-self-contained --nologo -p:OutputPath=obj/QuickBuild/ -o "%STAGE%"
if errorlevel 1 goto :failed

start "" /wait "%STAGE%\KeyMacro.exe" --exit
if errorlevel 1 goto :failed

powershell.exe -NoLogo -NoProfile -NonInteractive -Command ^
    "$session = [Diagnostics.Process]::GetCurrentProcess().SessionId; $running = [Diagnostics.Process]::GetProcessesByName('KeyMacro') | Where-Object SessionId -eq $session; if ($running) { try { Wait-Process -InputObject $running -Timeout 10 -ErrorAction Stop } catch { Write-Error $_; exit 1 } }; exit 0"
if errorlevel 1 (
    echo Close KeyMacro from the notification area and run this file again.
    goto :failed
)

robocopy "%STAGE%" "%INSTALL%" KeyMacro.exe KeyMacro.dll KeyMacro.deps.json KeyMacro.runtimeconfig.json /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
if errorlevel 8 goto :failed

echo Starting KeyMacro...
cmd /d /c exit 0
start "" "%INSTALL%\KeyMacro.exe"
if errorlevel 1 goto :failed
popd
exit /b 0

:failed
echo Build or launch failed. See the message above.
popd
if /i not "%~1"=="--no-pause" pause
exit /b 1
