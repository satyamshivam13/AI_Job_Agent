#!/bin/bash

# AI Job Agent - Automated Setup Script
# Run this script to set up the entire system automatically

set -e  # Exit on error

echo "🚀 AI Job Agent - Automated Setup"
echo "=================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "ℹ $1"
}

# Check prerequisites
echo "Step 1: Checking prerequisites..."
echo "--------------------------------"

# Check Python version
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    
    if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
        print_success "Python $PYTHON_VERSION found"
    else
        print_error "Python 3.11+ required. Found: $PYTHON_VERSION"
        exit 1
    fi
else
    print_error "Python not found. Please install Python 3.11+"
    exit 1
fi

# Check Git
if command -v git &> /dev/null; then
    print_success "Git found"
else
    print_error "Git not found. Please install Git"
    exit 1
fi

echo ""
echo "Step 2: Creating virtual environment..."
echo "---------------------------------------"

# Create virtual environment
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_success "Virtual environment created"
else
    print_warning "Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate
print_success "Virtual environment activated"

echo ""
echo "Step 3: Installing dependencies..."
echo "----------------------------------"

# Upgrade pip
pip install --upgrade pip > /dev/null 2>&1
print_success "pip upgraded"

# Install requirements
print_info "Installing Python packages (this may take 5-10 minutes)..."
pip install -r requirements.txt > /dev/null 2>&1
print_success "Python dependencies installed"

# Install Playwright browsers
print_info "Installing Playwright browsers..."
playwright install chromium > /dev/null 2>&1
print_success "Playwright browsers installed"

echo ""
echo "Step 4: Configuration..."
echo "------------------------"

# Create .env file if not exists
if [ ! -f ".env" ]; then
    cp .env.example .env
    print_success ".env file created from template"
    print_warning "Please edit .env file with your API keys"
    
    # Try to open .env in default editor
    if command -v nano &> /dev/null; then
        print_info "Opening .env in nano editor..."
        read -p "Press Enter to edit .env file (or Ctrl+C to skip)..."
        nano .env
    fi
else
    print_warning ".env file already exists"
fi

echo ""
echo "Step 5: Database setup..."
echo "-------------------------"

# Check if DATABASE_URL is set
if grep -q "DATABASE_URL=postgresql" .env; then
    print_info "Initializing database..."
    python scripts/init_db.py init
    print_success "Database initialized"
else
    print_warning "DATABASE_URL not configured in .env"
    print_info "Skipping database initialization"
fi

echo ""
echo "Step 6: Testing configuration..."
echo "--------------------------------"

# Test imports
python -c "from config.settings import settings; print('Config OK')" 2>&1
if [ $? -eq 0 ]; then
    print_success "Configuration test passed"
else
    print_error "Configuration test failed"
    exit 1
fi

echo ""
echo "Step 7: Creating necessary directories..."
echo "-----------------------------------------"

mkdir -p logs data screenshots tmp/resumes
print_success "Directories created"

echo ""
echo "=================================="
echo "✅ Setup Complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Configure your API keys in .env file:"
echo "   - GROQ_API_KEY (required)"
echo "   - VOYAGE_API_KEY (required)"
echo "   - DATABASE_URL (required)"
echo "   - Platform credentials (optional)"
echo ""
echo "2. Test the system:"
echo "   python main.py --mode search"
echo ""
echo "3. Start the API server:"
echo "   python api/main.py"
echo ""
echo "4. View documentation:"
echo "   - Setup Guide: docs/SETUP_GUIDE.md"
echo "   - Deployment: docs/DEPLOYMENT.md"
echo "   - Summary: docs/PROJECT_SUMMARY.md"
echo ""
echo "For help: https://github.com/yourusername/ai-job-agent"
echo ""
echo "Good luck with your job search! 🚀"
