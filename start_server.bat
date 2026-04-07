@echo off
cd /d "C:\Users\佐藤淳\OneDrive\Desktop\store-support"

start "まるなげ店長-Flask" cmd /k "cd /d C:\Users\佐藤淳\OneDrive\Desktop\store-support && venv\Scripts\python.exe wsgi.py"
start "まるなげ店長-ngrok" cmd /k "cd /d C:\Users\佐藤淳\OneDrive\Desktop\store-support && npx ngrok http 5000"
