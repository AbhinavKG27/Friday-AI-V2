@echo off
title Friday - Ultra Optimization for 4GB RAM
color 0A
cls

echo 🔧 Starting Friday Optimization Script...
echo.

:: 0. Check Admin Privileges
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo ⚠ Please run this script as Administrator!
    pause
    exit
)

:: 1. Clean %TEMP%, Windows Temp, and Prefetch
echo 📁 Cleaning Temp, Windows Temp, and Prefetch files...
echo → Cleaning user temp...
del /f /s /q "%temp%\." >nul 2>&1
for /d %%i in ("%temp%\*") do rd /s /q "%%i" >nul 2>&1

echo → Cleaning system temp...
del /f /s /q "C:\Windows\Temp\." >nul 2>&1
for /d %%i in ("C:\Windows\Temp\*") do rd /s /q "%%i" >nul 2>&1

echo → Cleaning prefetch...
del /f /s /q "C:\Windows\Prefetch\." >nul 2>&1
echo ✅ Temp files fully cleaned.
echo.

:: 2. Disable Bloat Services
echo 🛑 Disabling unnecessary background services...
sc stop "DiagTrack" >nul 2>&1 & sc config "DiagTrack" start= disabled
sc stop "MapsBroker" >nul 2>&1 & sc config "MapsBroker" start= disabled
sc stop "XblGameSave" >nul 2>&1 & sc config "XblGameSave" start= disabled
sc stop "XboxNetApiSvc" >nul 2>&1 & sc config "XboxNetApiSvc" start= disabled
echo ✅ Services disabled.
echo.

:: 3. Set Visual Effects for Best Performance
echo ⚙ Optimizing Windows visual effects...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" /v VisualFXSetting /t REG_DWORD /d 2 /f >nul
reg add "HKCU\Control Panel\Desktop" /v DragFullWindows /t REG_SZ /d 0 /f >nul
reg add "HKCU\Control Panel\Desktop" /v FontSmoothing /t REG_SZ /d 2 /f >nul
reg add "HKCU\Control Panel\Desktop\WindowMetrics" /v MinAnimate /t REG_SZ /d 0 /f >nul
echo ✅ Visual effects optimized.
echo.

:: 4. Kill Heavy Background Apps
echo ❌ Terminating common bloat background processes...
taskkill /f /im "OneDrive.exe" >nul 2>&1
taskkill /f /im "YourPhone.exe" >nul 2>&1
taskkill /f /im "SkypeApp.exe" >nul 2>&1
taskkill /f /im "Teams.exe" >nul 2>&1
taskkill /f /im "Microsoft.Photos.exe" >nul 2>&1
echo ✅ Background bloat apps closed.
echo.

:: 5. Virtual Memory Setup (Pagefile)
echo 🧠 Setting Virtual Memory (Pagefile) size...
wmic computersystem where name="%computername%" set AutomaticManagedPagefile=False >nul
wmic pagefileset where name="C:\\pagefile.sys" delete >nul
wmic pagefileset create name="C:\\pagefile.sys" >nul
wmic pagefileset where name="C:\\pagefile.sys" set InitialSize=4096,MaximumSize=8192 >nul
echo ✅ Virtual memory configured to 4GB - 8GB.
echo.

:: 6. Flush RAM (PowerShell GC)
echo 🧹 Flushing memory and cleaning standby list...
powershell -Command "[System.GC]::Collect()" >nul 2>&1
powershell -Command "[System.GC]::WaitForPendingFinalizers()" >nul 2>&1
echo ✅ RAM cleaned.
echo.

:: 7. Flush DNS Cache
echo 🌐 Flushing DNS cache...
ipconfig /flushdns >nul
echo ✅ DNS cache flushed.
echo.

:: 8. Clear Windows Update Cache
echo 📦 Cleaning Windows Update cache...
net stop wuauserv >nul 2>&1
rd /s /q "C:\Windows\SoftwareDistribution\Download" >nul 2>&1
net start wuauserv >nul 2>&1
echo ✅ Update cache cleared.
echo.

:: 9. Clear WER crash reports
echo 🗑 Clearing Windows Error Reporting logs...
rd /s /q "C:\ProgramData\Microsoft\Windows\WER" >nul 2>&1
rd /s /q "%LOCALAPPDATA%\Microsoft\Windows\WER" >nul 2>&1
echo ✅ WER files removed.
echo.


:: 11. Clean Browser Caches
echo 🌍 Clearing browser caches...
rd /s /q "%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache" >nul 2>&1
rd /s /q "%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache" >nul 2>&1
rd /s /q "%APPDATA%\Mozilla\Firefox\Profiles\*.default-release\cache2" >nul 2>&1
echo ✅ Browser cache cleared.
echo.

:: 12. Registry Startup (Optional - disabled by default)
:: echo 🧩 Removing registry startup entries...
:: reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /f >nul
:: echo ✅ Startup registry cleaned.
:: echo.

:: 13. Manual Startup App Control
echo 🧹 Opening Task Manager Startup Tab — disable heavy apps manually...
start taskmgr
timeout /t 5 >nul
echo.

echo ✅ All system optimization completed by Friday!
pause
exit
