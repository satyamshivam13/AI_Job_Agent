@echo off
REM AI Job Agent - Automated Setup Script for Windows
REM Run this script to set up the entire system automatically

echo ========================================
echo AI Job Agent - Automated Setup
echo ========================================
echo.

REM Check Python
echo Step 1: Checking prerequisites...
echo --------------------------------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

echo [OK] Python found
python --version

REM Check Git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Git not found. Install from https://git-scm.com/
)

echo.
echo Step 2: Creating virtual environment...
echo ---------------------------------------

REM Create virtual environment
if not exist "venv" (
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [WARNING] Virtual environment already exists
)

REM Activate virtual environment
call venv\Scripts\activate.bat
echo [OK] Virtual environment activated

echo.
echo Step 3: Installing dependencies...
echo ----------------------------------

REM Upgrade pip
python -m pip install --upgrade pip >nul 2>&1
echo [OK] pip upgraded

REM Install requirements
echo [INFO] Installing Python packages (this may take 5-10 minutes)...
pip install -r requirements.txt
echo [OK] Python dependencies installed

REM Install Playwright browsers
echo [INFO] Installing Playwright browsers...
playwright install chromium
echo [OK] Playwright browsers installed

echo.
echo Step 4: Configuration...
echo ------------------------

REM Create .env file
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] .env file created from template
    echo [WARNING] Please edit .env file with your API keys
    echo.
    echo Opening .env in Notepad...
    notepad .env
) else (
    echo [WARNING] .env file already exists
)

echo.
echo Step 5: Database setup...
echo -------------------------

findstr /C:"DATABASE_URL=postgresql" .env >nul
if %errorlevel% equ 0 (
    echo [INFO] Initializing database...
    python scripts\init_db.py init
    echo [OK] Database initialized
) else (
    echo [WARNING] DATABASE_URL not configured in .env
    echo [INFO] Skipping database initialization
)

echo.
echo Step 6: Testing configuration...
echo --------------------------------

python -c "from config.settings import settings; print('Config OK')"
if %errorlevel% equ 0 (
    echo [OK] Configuration test passed
) else (
    echo [ERROR] Configuration test failed
    pause
    exit /b 1
)

echo.
echo Step 7: Creating necessary directories...
echo -----------------------------------------

if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "screenshots" mkdir screenshots
if not exist "tmp\resumes" mkdir tmp\resumes
echo [OK] Directories created

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Next steps:
echo.
echo 1. Configure your API keys in .env file:
echo    - GROQ_API_KEY (required)
echo    - VOYAGE_API_KEY (required)
echo    - DATABASE_URL (required)
echo    - Platform credentials (optional)
echo.
echo 2. Test the system:
echo    python main.py --mode search
echo.
echo 3. Start the API server:
echo    python api\main.py
echo.
echo 4. View documentation:
echo    - Setup Guide: docs\SETUP_GUIDE.md
echo    - Deployment: docs\DEPLOYMENT.md
echo    - Summary: docs\PROJECT_SUMMARY.md
echo.
echo Good luck with your job search!
echo.
pause
