# 🚀 Deployment Guide
## Production Deployment Options for AI Job Agent

---

## Overview

This guide covers deploying the AI Job Agent to various cloud platforms:
- Railway (Recommended - Easy)
- Render (Good alternative)
- AWS (Full control)
- Google Cloud Run (Serverless)
- Self-hosted VPS (Complete control)

---

## Option 1: Railway (Recommended) ⭐

**Why Railway:**
- ✅ Easiest deployment
- ✅ Free $5/month credit
- ✅ Auto-scaling
- ✅ Built-in PostgreSQL
- ✅ Zero DevOps required

### Step-by-Step Deployment

#### 1. Prerequisites
```bash
# Install Railway CLI
npm install -g @railway/cli

# Or using Homebrew (Mac)
brew install railway
```

#### 2. Initialize Project
```bash
# Login to Railway
railway login

# Initialize in your project directory
cd ai-job-agent
railway init

# Select: "Create new project"
# Name: ai-job-agent
```

#### 3. Add PostgreSQL
```bash
# Add PostgreSQL database
railway add postgresql

# Railway will automatically set DATABASE_URL
```

#### 4. Set Environment Variables
```bash
# Set all required variables
railway variables set GROQ_API_KEY=gsk_your_key
railway variables set VOYAGE_API_KEY=pa_your_key
railway variables set LINKEDIN_EMAIL=your_email
railway variables set LINKEDIN_PASSWORD=your_password

# Set application config
railway variables set ENVIRONMENT=production
railway variables set LOG_LEVEL=INFO
railway variables set HEADLESS_BROWSER=true
railway variables set MAX_APPLICATIONS_PER_DAY=50
```

#### 5. Deploy
```bash
# Deploy to Railway
railway up

# Your app will be live at: https://your-app.railway.app
```

#### 6. Setup Scheduled Jobs
```bash
# Railway supports cron jobs
# Go to Railway dashboard
# Add new service: "Scheduler"
# Set command: python main.py --mode auto
# Set schedule: 0 9 * * * (daily at 9 AM)
```

#### 7. Monitor
```bash
# View logs
railway logs

# Check status
railway status
```

**Cost Estimate:**
- Free tier: $5/month credit
- Typical usage: $10-20/month
- With scaling: $30-50/month

---

## Option 2: Render

**Why Render:**
- ✅ Simple deployment
- ✅ Free tier available
- ✅ Auto-deploy from GitHub
- ✅ Managed PostgreSQL

### Deployment Steps

#### 1. Create Account
- Go to https://render.com
- Sign up with GitHub

#### 2. Create PostgreSQL Database
- Dashboard → New → PostgreSQL
- Name: ai-job-agent-db
- Plan: Free or Starter ($7/month)
- Save connection string

#### 3. Create Web Service
- Dashboard → New → Web Service
- Connect GitHub repo
- Name: ai-job-agent-api
- Environment: Docker
- Plan: Starter ($7/month)

#### 4. Environment Variables
Add in Render dashboard:
```
DATABASE_URL=<from_postgresql_service>
GROQ_API_KEY=gsk_xxx
VOYAGE_API_KEY=pa_xxx
LINKEDIN_EMAIL=xxx
LINKEDIN_PASSWORD=xxx
ENVIRONMENT=production
```

#### 5. Create Background Worker
- Dashboard → New → Background Worker
- Same repo
- Command: `python main.py --mode auto`
- Plan: Starter ($7/month)

#### 6. Setup Cron Job
- Dashboard → New → Cron Job
- Command: `python main.py --mode search`
- Schedule: `0 9 * * *` (daily 9 AM)

**Cost Estimate:**
- API: $7/month
- Worker: $7/month
- PostgreSQL: $7/month
- Total: ~$21/month

---

## Option 3: AWS (Full Control)

**Why AWS:**
- ✅ Complete control
- ✅ Best for large scale
- ✅ Professional-grade
- ✅ Integrates with other AWS services

### Architecture
```
- EC2: Application server
- RDS: PostgreSQL database
- S3: File storage
- CloudWatch: Logging
- EventBridge: Scheduled jobs
```

### Deployment Steps

#### 1. Launch EC2 Instance
```bash
# Instance type: t3.medium (2 vCPU, 4GB RAM)
# OS: Ubuntu 22.04 LTS
# Security group: Allow ports 22, 8000

# SSH into instance
ssh -i your-key.pem ubuntu@your-ec2-ip
```

#### 2. Install Dependencies
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

#### 3. Clone Repository
```bash
git clone https://github.com/yourusername/ai-job-agent.git
cd ai-job-agent
```

#### 4. Setup RDS PostgreSQL
- AWS Console → RDS → Create Database
- Engine: PostgreSQL 15
- Template: Free tier or Production
- Instance: db.t3.micro (free tier) or db.t3.medium
- Note connection endpoint

#### 5. Configure Environment
```bash
# Create .env file
cp .env.example .env
nano .env

# Fill in:
DATABASE_URL=postgresql://user:pass@rds-endpoint:5432/dbname
# ... other variables
```

#### 6. Deploy with Docker
```bash
# Build and start
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

#### 7. Setup Cron (EventBridge)
- AWS Console → EventBridge → Rules
- Create rule: daily-job-search
- Schedule: cron(0 9 * * ? *)
- Target: ECS task or Lambda
- Command: `python main.py --mode search`

#### 8. Setup Monitoring
```bash
# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# Configure logging
# Logs will appear in CloudWatch console
```

**Cost Estimate:**
- EC2 t3.medium: $30/month
- RDS db.t3.micro: $15/month
- Data transfer: $5/month
- Total: ~$50/month

---

## Option 4: Google Cloud Run (Serverless)

**Why Cloud Run:**
- ✅ Serverless (pay per use)
- ✅ Auto-scaling
- ✅ Good for burst workloads

### Deployment Steps

#### 1. Setup GCP Project
```bash
# Install gcloud CLI
curl https://sdk.cloud.google.com | bash

# Login
gcloud auth login

# Create project
gcloud projects create ai-job-agent
gcloud config set project ai-job-agent
```

#### 2. Enable APIs
```bash
gcloud services enable run.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
```

#### 3. Create Cloud SQL (PostgreSQL)
```bash
gcloud sql instances create ai-job-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

# Create database
gcloud sql databases create ai_job_agent \
  --instance=ai-job-db

# Get connection string
gcloud sql instances describe ai-job-db
```

#### 4. Build Container
```bash
# Build and push to Container Registry
gcloud builds submit --tag gcr.io/ai-job-agent/app

# Deploy to Cloud Run
gcloud run deploy ai-job-agent \
  --image gcr.io/ai-job-agent/app \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars DATABASE_URL=$DATABASE_URL,GROQ_API_KEY=$GROQ_API_KEY
```

#### 5. Setup Cloud Scheduler
```bash
# Create daily job
gcloud scheduler jobs create http daily-job-search \
  --schedule="0 9 * * *" \
  --uri="https://your-app.run.app/trigger-search" \
  --http-method=POST
```

**Cost Estimate:**
- Cloud Run: $5-15/month (pay per use)
- Cloud SQL: $10/month
- Total: ~$15-25/month

---

## Option 5: Self-Hosted VPS

**Recommended Providers:**
- DigitalOcean: $12/month (2GB RAM)
- Linode: $12/month (2GB RAM)
- Vultr: $12/month (2GB RAM)
- Hetzner: $5/month (2GB RAM, Europe)

### Setup Guide

#### 1. Create Droplet/Server
- OS: Ubuntu 22.04
- RAM: Minimum 2GB
- Storage: 50GB SSD

#### 2. Initial Setup
```bash
# SSH into server
ssh root@your-server-ip

# Create non-root user
adduser jobagent
usermod -aG sudo jobagent
su - jobagent

# Setup firewall
sudo ufw allow 22
sudo ufw allow 8000
sudo ufw enable
```

#### 3. Install Docker
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker jobagent
```

#### 4. Clone and Deploy
```bash
git clone https://github.com/yourusername/ai-job-agent.git
cd ai-job-agent

# Setup .env
cp .env.example .env
nano .env

# Deploy
docker-compose up -d
```

#### 5. Setup Nginx Reverse Proxy
```bash
sudo apt install nginx

# Create config
sudo nano /etc/nginx/sites-available/ai-job-agent

# Add:
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# Enable
sudo ln -s /etc/nginx/sites-available/ai-job-agent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 6. SSL Certificate (Free)
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

#### 7. Setup Automatic Updates
```bash
# Create update script
nano ~/update.sh

# Add:
#!/bin/bash
cd ~/ai-job-agent
git pull
docker-compose down
docker-compose build
docker-compose up -d

# Make executable
chmod +x ~/update.sh

# Add to cron for weekly updates
crontab -e
# Add: 0 3 * * 0 ~/update.sh
```

**Cost Estimate:**
- VPS: $12/month
- Domain: $12/year
- Total: ~$13/month

---

## Post-Deployment Checklist

### ✅ Verify Deployment
```bash
# Health check
curl https://your-domain.com/

# Check API
curl https://your-domain.com/api/jobs

# Check logs
docker-compose logs -f

# Test job search
curl -X POST https://your-domain.com/api/trigger-search
```

### ✅ Setup Monitoring
- Enable application monitoring (Sentry, DataDog)
- Setup uptime monitoring (UptimeRobot, Pingdom)
- Configure alerts for errors
- Setup backup strategy

### ✅ Security Hardening
- Change all default passwords
- Enable 2FA on all accounts
- Setup firewall rules
- Enable SSL/TLS
- Regular security updates
- Rotate API keys monthly

### ✅ Backup Strategy
```bash
# Database backups
# Add to cron:
0 2 * * * pg_dump $DATABASE_URL > backup-$(date +\%Y\%m\%d).sql
0 2 * * * aws s3 cp backup-$(date +\%Y\%m\%d).sql s3://your-backup-bucket/
```

---

## Troubleshooting

### Common Issues

**Issue: Application won't start**
```bash
# Check logs
docker-compose logs app

# Common causes:
# - Missing environment variables
# - Database connection failed
# - Port already in use
```

**Issue: Database connection error**
```bash
# Test connection
psql $DATABASE_URL

# If fails, check:
# - Correct connection string
# - Database is running
# - Firewall allows connection
```

**Issue: Out of memory**
```bash
# Check memory usage
free -h

# Increase swap if needed
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## Scaling Recommendations

### When to Scale

**Low Volume (< 1000 apps/month):**
- Single VPS: $12/month
- Total: ~$15/month

**Medium Volume (1000-5000 apps/month):**
- Railway/Render: $20-30/month
- Or AWS t3.medium: $50/month

**High Volume (> 5000 apps/month):**
- AWS with auto-scaling: $100-200/month
- Multiple workers
- Dedicated database
- CDN for assets

---

## Support

For deployment help:
- GitHub Issues: github.com/yourusername/ai-job-agent/issues
- Email: shivamsatyam35@gmail.com
- Documentation: Full docs in `/docs` folder

**Success!** Your AI Job Agent is now deployed and running 24/7! 🎉
