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

echo Building Kitajimacro...
dotnet publish "windows\KeyMacro.csproj" -c Release --no-self-contained --nologo -p:OutputPath=obj/QuickBuild/ -o "%STAGE%"
if errorlevel 1 goto :failed

start "" /wait "%STAGE%\Kitajimacro.exe" --exit
if errorlevel 1 goto :failed

powershell.exe -NoLogo -NoProfile -NonInteractive -Command ^
    "$session = [Diagnostics.Process]::GetCurrentProcess().SessionId; $running = ('Kitajimacro', 'KeyMacro' | ForEach-Object { [Diagnostics.Process]::GetProcessesByName($_) }) | Where-Object SessionId -eq $session; if ($running) { try { Wait-Process -InputObject $running -Timeout 10 -ErrorAction Stop } catch { Write-Error $_; exit 1 } }; exit 0"
if errorlevel 1 (
    echo Close Kitajimacro from the notification area and run this file again.
    goto :failed
)

robocopy "%STAGE%" "%INSTALL%" Kitajimacro.exe Kitajimacro.dll Kitajimacro.deps.json Kitajimacro.runtimeconfig.json /R:0 /W:0 /NFL /NDL /NJH /NJS /NP
if errorlevel 8 goto :failed

rem Keep previously created shortcuts working after the executable rename.
if exist "%INSTALL%\KeyMacro.exe" (
    copy /y "%INSTALL%\Kitajimacro.exe" "%INSTALL%\KeyMacro.exe" >nul
    if errorlevel 1 goto :failed
)

echo Starting Kitajimacro...
cmd /d /c exit 0
start "" "%INSTALL%\Kitajimacro.exe"
if errorlevel 1 goto :failed
popd
exit /b 0

:failed
echo Build or launch failed. See the message above.
popd
if /i not "%~1"=="--no-pause" pause
exit /b 1
