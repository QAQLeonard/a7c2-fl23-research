@echo off
call "%~dp0dev\windows\bootstrap.cmd" fl23 %*
exit /b %errorlevel%
