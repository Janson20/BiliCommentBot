@echo off
chcp 65001 >nul
title B站评论机器人 - 一键启动器

echo.
echo ================================================
echo   B站评论机器人 - 一键启动器
echo ================================================
echo.

python "%~dp0auto_launcher.py"

pause
