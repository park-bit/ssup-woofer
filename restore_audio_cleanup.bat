@echo off
title SsupWoofer Emergency Cleanup
echo ====================================================
echo        SsupWoofer Audio Restore Tool     
echo ====================================================
echo.
echo This tool reverts your Windows audio back to your laptop speakers
echo in case the app closed unexpectedly.
echo.
echo NOTE: It will NOT interfere with NVIDIA Broadcast or Acer Purified Voice.
echo.
pause

if exist "nircmdc.exe" (
    echo Attempting automatic restore using NirCmd...
    echo We will try to set "Speakers" or "Realtek" as default.
    nircmdc.exe setdefaultsounddevice "Speakers"
    nircmdc.exe setdefaultsounddevice "Realtek"
    echo Done. Check your sound icon in the taskbar.
) else (
    echo NirCmd not found. Opening Windows Sound Settings...
    start ms-settings:sound
    echo Please select your primary Laptop Speakers manually from the list.
)

echo.
echo All cleanup finished! 
pause
