@echo off
cd /d "%~dp0"
"C:\Users\vegas\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe" -u "%~dp0main.py" >> "%~dp0reader_log.txt" 2>&1
