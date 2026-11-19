@echo off
setlocal
if "%NOVA_HOME%"=="" set NOVA_HOME=%USERPROFILE%\nova
python "%~dp0app\nova\cli.py" %*
