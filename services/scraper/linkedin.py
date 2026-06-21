"""
LinkedIn Job Scraper
Uses Playwright for modern, reliable scraping
"""

from playwright.async_api import async_playwright, Page, Browser
from typing import List, Dict, Optional
import asyncio
import random
from datetime import datetime, timezone
import re
from urllib.parse import quote_plus

from config.settings import settings
from utils.logger import logger


class LinkedInScraper:
    """
    LinkedIn job scraper using Playwright
    Handles authentication, search, and job detail extraction
    """
    
    def __init__(self):
        self.platform = "linkedin"
        self.base_url = "https://www.linkedin.com"
        self.jobs_url = f"{self.base_url}/jobs/search"
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
    async def initialize(self):
        """Initialize browser and login"""
        logger.info("🔧 Initializing LinkedIn scraper...")
        
        playwright = await async_playwright().start()
        
        # Launch browser with stealth mode
        self.browser = await playwright.chromium.launch(
            headless=settings.headless_browser,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        # Create context with realistic fingerprint
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        self.page = await context.new_page()
        
        # Login if credentials provided
        if settings.linkedin_email and settings.linkedin_password:
            await self._login()
        else:
            logger.warning("⚠️ No LinkedIn credentials provided - limited results")
    
    async def _login(self):
        """Login to LinkedIn"""
        try:
            logger.info("🔑 Logging into LinkedIn...")
            
            await self.page.goto(f"{self.base_url}/login", wait_until="domcontentloaded", timeout=30000)
            
            # Fill login form
            await self.page.fill('input#username', settings.linkedin_email)
            await self.page.fill('input#password', settings.linkedin_password)
            
            # Human-like delay
            await asyncio.sleep(random.uniform(1, 2))
            
            # Click login
            await self.page.click('button[type="submit"]')
            
            # Wait for redirect
            await self.page.wait_for_url('**/feed/**', timeout=15000)
            
            logger.info("✓ Successfully logged into LinkedIn")
            
        except Exception as e:
            logger.error(f"✗ LinkedIn login failed: {str(e)}")
            raise
    
    async def search_jobs(self, 
                         keywords: str,
                         location: str = "Remote",
                         easy_apply: bool = True,
                         max_results: int = 50) -> List[Dict]:
        """
        Search for jobs on LinkedIn
        
        Args:
            keywords: Search keywords (e.g., "AI Engineer")
            location: Job location (e.g., "Remote", "New York")
            easy_apply: Filter for Easy Apply jobs only
            max_results: Maximum number of jobs to scrape
        
        Returns:
            List of job dictionaries
        """
        logger.info(f"🔍 Searching LinkedIn: {keywords} in {location}")
        
        jobs = []
        
        # Build search URL
        search_params = {
            'keywords': keywords,
            'location': location,
            'f_AL': 'true' if easy_apply else None,  # Easy Apply filter
            'f_TPR': 'r604800',  # Past week
            'f_WT': '2',  # Remote jobs
        }
        
        # Construct URL
        params_str = '&'.join(f"{k}={quote_plus(str(v))}" for k, v in search_params.items() if v)
        search_url = f"{self.jobs_url}?{params_str}"
        
        await self.page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await self._random_delay()
        
        # Scroll to load more jobs
        for i in range(max_results // 25 + 1):
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
        
        # Extract job cards
        job_cards = await self.page.query_selector_all('.jobs-search__results-list li')
        
        logger.info(f"Found {len(job_cards)} job listings")
        
        for card in job_cards[:max_results]:
            try:
                job_data = await self._extract_job_from_card(card)
                if job_data:
                    jobs.append(job_data)
                    
                    # Rate limiting
                    await self._random_delay()
                    
            except Exception as e:
                logger.error(f"Error extracting job: {str(e)}")
                continue
        
        logger.info(f"✓ Scraped {len(jobs)} jobs from LinkedIn")
        return jobs
    
    async def _extract_job_from_card(self, card) -> Optional[Dict]:
        """Extract job data from a job card element"""
        try:
            # Click card to load details
            await card.click()
            await asyncio.sleep(1)
            
            # Extract basic info from card
            title_elem = await card.query_selector('.job-card-list__title')
            title = await title_elem.inner_text() if title_elem else "Unknown"
            
            company_elem = await card.query_selector('.job-card-container__company-name')
            company = await company_elem.inner_text() if company_elem else "Unknown"
            
            location_elem = await card.query_selector('.job-card-container__metadata-item')
            location = await location_elem.inner_text() if location_elem else "Unknown"
            
            # Get job URL
            link_elem = await card.query_selector('a.job-card-list__title')
            job_url = await link_elem.get_attribute('href') if link_elem else None
            
            if not job_url:
                return None
            
            # Extract job ID from URL
            job_id_match = re.search(r'/jobs/view/(\d+)', job_url)
            job_id = job_id_match.group(1) if job_id_match else None
            
            # Extract detailed description from right panel
            description_elem = await self.page.query_selector('.jobs-description__content')
            description = await description_elem.inner_text() if description_elem else ""
            
            # Extract salary if available
            salary_elem = await self.page.query_selector('.salary-main-rail__salary-info')
            salary_text = await salary_elem.inner_text() if salary_elem else None
            
            # Parse salary
            salary_min, salary_max = self._parse_salary(salary_text) if salary_text else (None, None)
            
            # Check if Easy Apply
            easy_apply_button = await self.page.query_selector('button.jobs-apply-button--top-card')
            is_easy_apply = easy_apply_button is not None
            
            # Detect remote
            is_remote = any(keyword in location.lower() for keyword in ['remote', 'anywhere'])
            
            job_data = {
                'platform': 'linkedin',
                'platform_job_id': job_id,
                'title': title.strip(),
                'company': company.strip(),
                'location': location.strip(),
                'url': f"{self.base_url}{job_url}",
                'description': description.strip(),
                'salary_min': salary_min,
                'salary_max': salary_max,
                'currency': 'USD',
                'remote': is_remote,
                'easy_apply': is_easy_apply,
                'scraped_at': datetime.now(timezone.utc),
                'posted_date': None,  # Could extract from "Posted X days ago"
            }
            
            return job_data
            
        except Exception as e:
            logger.error(f"Error parsing job card: {str(e)}")
            return None
    
    def _parse_salary(self, salary_text: str) -> tuple[Optional[int], Optional[int]]:
        """Parse salary string to min/max integers"""
        try:
            # Example: "$80,000 - $120,000/yr"
            numbers = re.findall(r'\$?([\d,]+)', salary_text)
            if len(numbers) >= 2:
                salary_min = int(numbers[0].replace(',', ''))
                salary_max = int(numbers[1].replace(',', ''))
                
                # Convert to annual if needed
                if 'hr' in salary_text.lower():
                    salary_min *= 2080  # hours per year
                    salary_max *= 2080
                
                return salary_min, salary_max
            elif len(numbers) == 1:
                salary = int(numbers[0].replace(',', ''))
                if 'hr' in salary_text.lower():
                    salary *= 2080
                return salary, salary
                
        except Exception as e:
            logger.error(f"Error parsing salary: {str(e)}")
        
        return None, None
    
    async def _random_delay(self, min_ms: int = None, max_ms: int = None):
        """Add random human-like delay"""
        min_ms = min_ms or settings.min_delay_between_actions
        max_ms = max_ms or settings.max_delay_between_actions
        
        delay = random.uniform(min_ms / 1000, max_ms / 1000)
        await asyncio.sleep(delay)
    
    async def close(self):
        """Close browser"""
        if self.browser:
            await self.browser.close()
            logger.info("✓ Browser closed")


async def main():
    """Test the scraper"""
    scraper = LinkedInScraper()
    
    try:
        await scraper.initialize()
        
        # Test search
        jobs = await scraper.search_jobs(
            keywords="AI Engineer",
            location="Remote",
            easy_apply=True,
            max_results=10
        )
        
        print(f"\n✓ Found {len(jobs)} jobs")
        
        for job in jobs[:3]:
            print(f"\n📋 {job['title']} at {job['company']}")
            print(f"   Location: {job['location']}")
            print(f"   Remote: {job['remote']}")
            print(f"   URL: {job['url']}")
        
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
