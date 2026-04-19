@echo off
chcp 65001 >nul
echo ====================================
echo   Milkteainfo Bot - Khoi dong...
echo ====================================
cd /d "%~dp0"
echo Dang kiem tra port...
python -m bot.main
pause
