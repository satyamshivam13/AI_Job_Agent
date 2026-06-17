# 🚀 Complete Setup Guide for Beginners
## AI Job Application System - Step-by-Step Installation

This guide assumes you're starting from scratch with limited technical knowledge.

---

## 📋 Prerequisites

Before starting, ensure you have:
- A computer (Windows, Mac, or Linux)
- Internet connection
- About 2-3 hours for complete setup
- An email address
- Willingness to create free accounts

---

## Step 1: Install Python (15 minutes)

### Windows:
1. Go to https://www.python.org/downloads/
2. Download Python 3.11 or higher
3. **IMPORTANT:** Check "Add Python to PATH" during installation
4. Click "Install Now"
5. Verify installation:
   ```bash
   python --version
   ```
   Should show: `Python 3.11.x`

### Mac:
```bash
# Install Homebrew first (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.11

# Verify
python3 --version
```

### Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
python3 --version
```

---

## Step 2: Install Git (10 minutes)

### Windows:
1. Download from https://git-scm.com/download/win
2. Install with default settings
3. Verify:
   ```bash
   git --version
   ```

### Mac:
```bash
# Usually pre-installed, or install via Homebrew
brew install git
```

### Linux:
```bash
sudo apt install git
```

---

## Step 3: Clone the Project (5 minutes)

Open terminal (Command Prompt on Windows, Terminal on Mac/Linux):

```bash
# Navigate to where you want the project
cd Desktop  # or any folder you prefer

# Clone the repository
git clone https://github.com/yourusername/ai-job-agent.git

# Enter the directory
cd ai-job-agent
```

---

## Step 4: Create Virtual Environment (5 minutes)

This keeps project dependencies isolated.

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

# You should see (venv) in your terminal prompt
```

**Important:** Always activate the virtual environment before working on the project.

---

## Step 5: Install Dependencies (10-15 minutes)

```bash
# Install all required packages
pip install -r requirements.txt

# This will take 5-10 minutes - be patient!
```

If you get errors:
- Make sure virtual environment is activated
- Try: `pip install --upgrade pip` first
- On Windows, you might need Microsoft C++ Build Tools

---

## Step 6: Install Playwright Browsers (5 minutes)

```bash
# Install browser automation tools
playwright install chromium

# This downloads Chromium browser (~200MB)
```

---

## Step 7: Get API Keys (20-30 minutes)

### 7.1 Groq API (FREE - Required)

1. Go to https://console.groq.com/
2. Sign up with Google/GitHub
3. Click "Create API Key"
4. Copy the key (starts with `gsk_...`)
5. Save it - you'll need it soon

### 7.2 Voyage AI (FREE - Required for embeddings)

1. Go to https://www.voyageai.com/
2. Sign up
3. Go to Settings → API Keys
4. Create new key
5. Copy and save

### 7.3 Supabase (FREE - Required for database)

1. Go to https://supabase.com/
2. Sign up
3. Create new project
   - Name: `ai-job-agent`
   - Database Password: (create a strong one)
   - Region: Choose closest to you
4. Wait 2-3 minutes for project setup
5. Go to Settings → Database
6. Copy "Connection string" (URI format)
7. Replace `[YOUR-PASSWORD]` with your actual password

### 7.4 OpenAI (Optional - Better quality)

1. Go to https://platform.openai.com/
2. Add payment method
3. Create API key
4. Costs: ~$0.10-0.50 per day

---

## Step 8: Configure Environment (10 minutes)

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` in any text editor (Notepad, VS Code, etc.)

3. Fill in your API keys:
   ```bash
   # Paste your actual keys
   GROQ_API_KEY=gsk_your_actual_key_here
   VOYAGE_API_KEY=pa_your_actual_key_here
   DATABASE_URL=postgresql://postgres:your_password@db.xxxxx.supabase.co:5432/postgres
   SUPABASE_URL=https://xxxxx.supabase.co
   SUPABASE_KEY=your_supabase_anon_key
   ```

4. (Optional) Add job platform credentials:
   ```bash
   LINKEDIN_EMAIL=your_email@gmail.com
   LINKEDIN_PASSWORD=your_password
   
   INDEED_EMAIL=your_email@gmail.com
   INDEED_PASSWORD=your_password
   ```

5. Save and close

**⚠️ IMPORTANT:** Never share your `.env` file or commit it to GitHub!

---

## Step 9: Initialize Database (5 minutes)

```bash
# Create database tables
python scripts/init_db.py init

# You should see:
# ✓ Created 6 tables:
#   - jobs
#   - applications
#   - resume_versions
#   - user_profiles
#   - activity_logs
#   - analytics
# ✓ Created user profile for Satyam Shivam
```

If you get connection errors:
- Check your DATABASE_URL is correct
- Ensure Supabase project is running
- Verify password doesn't have special characters that need escaping

---

## Step 10: Test Your Setup (10 minutes)

### Test 1: Check Configuration
```bash
python -c "from config.settings import settings; print('✓ Config loaded')"
```

### Test 2: Test Database
```bash
python scripts/init_db.py stats
```
Should show database statistics.

### Test 3: Test Scraper (dry run)
```bash
python services/scraper/indeed.py
```
Should scrape a few test jobs.

### Test 4: Test AI Agents
```bash
python agents/crew.py
```
Should process a sample job.

---

## Step 11: Run Your First Job Search (15 minutes)

```bash
# Search for jobs (won't auto-apply yet)
python main.py --mode search

# This will:
# 1. Search LinkedIn and Indeed
# 2. Score jobs with AI
# 3. Generate tailored resumes
# 4. Save to database
```

Watch the terminal for progress logs. You should see:
- 🔍 Searching job platforms
- 🤖 Scoring jobs with AI
- 📄 Generating applications
- ✓ Pipeline completed

---

## Step 12: View Results (5 minutes)

### Option A: Check Database
```bash
python scripts/init_db.py stats
```

### Option B: Start API Server
```bash
# In one terminal:
python api/main.py

# Visit in browser:
http://localhost:8000/api/jobs
```

You'll see JSON data of found jobs.

---

## 🎯 Daily Automation Setup

### Option 1: Manual Daily Runs
```bash
# Activate virtual environment
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Run daily search
python main.py --mode search
```

### Option 2: Scheduled Automation (Windows)

1. Open Task Scheduler
2. Create Basic Task
3. Name: "AI Job Agent"
4. Trigger: Daily at 9:00 AM
5. Action: Start a program
   - Program: `C:\path\to\venv\Scripts\python.exe`
   - Arguments: `C:\path\to\ai-job-agent\main.py --mode search`
6. Finish

### Option 3: Scheduled Automation (Mac/Linux)

```bash
# Edit cron jobs
crontab -e

# Add this line (runs daily at 9 AM)
0 9 * * * cd /path/to/ai-job-agent && /path/to/venv/bin/python main.py --mode search

# Save and exit
```

---

## 🔧 Troubleshooting Common Issues

### Issue: "Module not found"
**Solution:**
```bash
# Make sure virtual environment is activated
# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: "Database connection failed"
**Solution:**
- Check your DATABASE_URL in .env
- Verify Supabase project is running
- Test connection: `psql <DATABASE_URL>`

### Issue: "API rate limit exceeded"
**Solution:**
- Groq free tier: 100 requests/min
- Wait a minute and try again
- Or upgrade to paid tier

### Issue: "Playwright browser not found"
**Solution:**
```bash
playwright install chromium
```

### Issue: "Permission denied" (Linux/Mac)
**Solution:**
```bash
chmod +x main.py
chmod +x scripts/*.py
```

---

## 📊 Monitoring Your Applications

### View Application Status
```bash
# Check today's stats
python -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.settings import settings
from models.database import Application
import datetime

engine = create_engine(settings.database_url)
Session = sessionmaker(bind=engine)
session = Session()

today = datetime.datetime.utcnow().date()
count = session.query(Application).filter(
    Application.applied_at >= today
).count()

print(f'Applications today: {count}')
"
```

### Start API Dashboard
```bash
# Terminal 1: Start API
python api/main.py

# Terminal 2: Check endpoints
curl http://localhost:8000/api/dashboard/stats
```

---

## 🚀 Next Steps

### Increase Application Volume
1. Edit `config/user_profile.json`
2. Increase `max_applications_per_day`
3. Add more platforms

### Improve Resume Quality
1. Review generated resumes in `/tmp/resumes/`
2. Adjust prompts in `config/prompts.py`
3. Test different variants

### Enable Auto-Apply
```bash
# In .env, set:
ENABLE_AUTO_APPLY=true

# ⚠️ Warning: This will actually submit applications
# Test thoroughly first!
```

### Monitor Success
```bash
# Check interview rate weekly
python -c "
from api.main import get_analytics
import asyncio
result = asyncio.run(get_analytics(days=7, db=next(get_db())))
print(f'Interview rate: {result.interview_rate}%')
"
```

---

## 📧 Get Help

### Common Questions

**Q: How much does this cost?**
A: $0-5/month with free tiers. Or $70-80/month for production setup.

**Q: Will this work on my old laptop?**
A: Yes, minimum requirements:
- 4GB RAM
- 10GB free space
- Python 3.11+

**Q: Is this legal?**
A: Yes, but check each platform's Terms of Service. Some prohibit automation.

**Q: How many jobs can I apply to per day?**
A: Start with 10-20. Scale to 50-100 after testing.

**Q: What if I get banned?**
A: Use rate limiting, rotate sessions, and don't be too aggressive.

---

## 🎓 Learning Resources

### Python Basics
- https://www.python.org/about/gettingstarted/
- https://www.codecademy.com/learn/learn-python-3

### Git & GitHub
- https://git-scm.com/book/en/v2
- https://guides.github.com/

### Playwright Automation
- https://playwright.dev/python/docs/intro

### CrewAI (Multi-Agent)
- https://docs.crewai.com/

---

## ✅ Setup Complete!

You now have:
- ✓ Fully working AI job agent
- ✓ Automated job searching
- ✓ AI-powered resume tailoring
- ✓ Application tracking
- ✓ Analytics dashboard

**Start applying to jobs and track your success! 🎉**

---

## 🔄 Daily Workflow

1. **Morning:** Check yesterday's results
   ```bash
   python scripts/init_db.py stats
   ```

2. **Midday:** Run search if not automated
   ```bash
   python main.py --mode search
   ```

3. **Evening:** Review applications
   - Check email for responses
   - Update application status in database
   - Adjust settings based on results

4. **Weekly:** Analyze performance
   - Which platforms work best?
   - Which resume variants perform best?
   - What's your interview rate?

---

**Need Help?** Open an issue on GitHub or email shivamsatyam35@gmail.com
