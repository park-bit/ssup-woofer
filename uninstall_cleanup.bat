@echo off
title SsupWoofer Cleanup Tool
echo ====================================================
echo        SsupWoofer Uninstaller and Cleanup Tool     
echo ====================================================
echo.
echo This tool will help you revert your Windows audio settings back to normal
echo and remove the SsupWoofer project files safely.
echo.
echo It will NOT touch your NVIDIA Broadcast or Acer Purified Voice settings.
echo.

set /p UserConfirm="Are you sure you want to revert changes and remove SsupWoofer? (Y/N): "
if /I "%UserConfirm%" NEQ "Y" (
    echo Cleanup aborted.
    pause
    exit /b
)

echo.
echo [Step 1] SsupWoofer files are located in %~dp0
echo You can manually delete this folder now if you like, or leave it.
echo (We will not forcefully delete your code folder to be safe).

echo.
echo [Step 2] REVERTING DEFAULT AUDIO DEVICE
echo Since Windows commandline does not natively switch audio output easily,
echo you MUST manually switch the default playback device back to your laptop speakers!
echo.
echo Opening Windows Sound Settings for you now...
start ms-settings:sound

echo.
echo ---> Please select your regular Laptop Speakers under "Choose your output device".
echo ---> If you installed VB-Cable just for this app, you can uninstall it from "Add or remove programs".
echo.
echo You're all set! NVIDIA Broadcast / Acer devices will continue routing normally.
pause
