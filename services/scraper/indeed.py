"""
Indeed Job Scraper
More permissive than LinkedIn, no login required
"""

from playwright.async_api import async_playwright, Page, Browser
from typing import List, Dict, Optional
import asyncio
import random
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import quote_plus

from config.settings import settings
from utils.logger import logger


class IndeedScraper:
    """
    Indeed job scraper using Playwright
    No authentication required - public job listings
    """
    
    def __init__(self):
        self.platform = "indeed"
        self.base_url = "https://www.indeed.com"
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
    async def initialize(self):
        """Initialize browser"""
        logger.info("🔧 Initializing Indeed scraper...")
        
        playwright = await async_playwright().start()
        
        self.browser = await playwright.chromium.launch(
            headless=settings.headless_browser,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        self.page = await context.new_page()
        logger.info("✓ Indeed scraper initialized")
    
    async def search_jobs(self,
                         keywords: str,
                         location: str = "Remote",
                         max_results: int = 50,
                         remote_only: bool = True) -> List[Dict]:
        """
        Search for jobs on Indeed
        
        Args:
            keywords: Job search terms
            location: Location or "Remote"
            max_results: Max jobs to scrape
            remote_only: Filter for remote jobs
        
        Returns:
            List of job dictionaries
        """
        logger.info(f"🔍 Searching Indeed: {keywords} in {location}")
        
        jobs = []
        
        # Build search URL
        search_url = f"{self.base_url}/jobs"
        params = {
            'q': keywords,
            'l': location,
            'sc': '0kf:attr(DSQF7);' if remote_only else '',  # Remote filter
            'sort': 'date',  # Sort by date
            'fromage': '7'  # Last 7 days
        }
        
        params_str = '&'.join(f"{k}={quote_plus(str(v))}" for k, v in params.items() if v)
        full_url = f"{search_url}?{params_str}"
        
        await self.page.goto(full_url, wait_until="domcontentloaded", timeout=60000)
        await self._random_delay()
        
        # Pagination
        page_num = 0
        while len(jobs) < max_results and page_num < 5:  # Max 5 pages
            # Extract job cards
            job_cards = await self.page.query_selector_all('.job_seen_beacon')
            
            logger.info(f"Page {page_num + 1}: Found {len(job_cards)} listings")
            
            for card in job_cards:
                if len(jobs) >= max_results:
                    break
                
                try:
                    job_data = await self._extract_job_from_card(card)
                    if job_data:
                        jobs.append(job_data)
                        await self._random_delay(500, 1000)
                        
                except Exception as e:
                    logger.error(f"Error extracting job: {str(e)}")
                    continue
            
            # Try to go to next page
            next_button = await self.page.query_selector('a[data-testid="pagination-page-next"]')
            if next_button and len(jobs) < max_results:
                await next_button.click()
                await asyncio.sleep(2)
                page_num += 1
            else:
                break
        
        logger.info(f"✓ Scraped {len(jobs)} jobs from Indeed")
        return jobs
    
    async def _extract_job_from_card(self, card) -> Optional[Dict]:
        """Extract job data from job card"""
        try:
            # Extract title
            title_elem = await card.query_selector('h2.jobTitle')
            if not title_elem:
                return None
            title = await title_elem.inner_text()
            
            # Extract company
            company_elem = await card.query_selector('[data-testid="company-name"]')
            company = await company_elem.inner_text() if company_elem else "Unknown"
            
            # Extract location
            location_elem = await card.query_selector('[data-testid="text-location"]')
            location = await location_elem.inner_text() if location_elem else "Unknown"
            
            # Get job URL and ID
            link_elem = await card.query_selector('a.jcs-JobTitle')
            if not link_elem:
                return None
            
            job_url_path = await link_elem.get_attribute('href')
            job_url = f"{self.base_url}{job_url_path}" if job_url_path else None
            
            if not job_url:
                return None
            
            # Extract job key (Indeed's ID)
            job_id_match = re.search(r'jk=([a-f0-9]+)', job_url)
            job_id = job_id_match.group(1) if job_id_match else None
            
            # Extract salary
            salary_elem = await card.query_selector('[data-testid="attribute_snippet_testid"]')
            salary_text = await salary_elem.inner_text() if salary_elem else None
            salary_min, salary_max = self._parse_salary(salary_text) if salary_text else (None, None)
            
            # Extract job snippet/description
            snippet_elem = await card.query_selector('[data-testid="job-snippet"]')
            snippet = await snippet_elem.inner_text() if snippet_elem else ""
            
            # Get full description by visiting job page
            description = await self._get_full_description(job_url)
            
            # Detect remote
            location_lower = location.lower()
            is_remote = any(keyword in location_lower for keyword in ['remote', 'work from home', 'anywhere'])
            
            # Parse posted date
            date_elem = await card.query_selector('.date')
            posted_date = await self._parse_posted_date(date_elem) if date_elem else None
            
            job_data = {
                'platform': 'indeed',
                'platform_job_id': job_id,
                'title': title.strip(),
                'company': company.strip(),
                'location': location.strip(),
                'url': job_url,
                'description': description or snippet.strip(),
                'salary_min': salary_min,
                'salary_max': salary_max,
                'currency': 'USD',
                'remote': is_remote,
                'scraped_at': datetime.now(timezone.utc),
                'posted_date': posted_date,
            }
            
            return job_data
            
        except Exception as e:
            logger.error(f"Error parsing job card: {str(e)}")
            return None
    
    async def _get_full_description(self, job_url: str) -> Optional[str]:
        """Visit job page to get full description"""
        try:
            # Open in new page to avoid losing search results
            new_page = await self.browser.new_page()
            await new_page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
            
            # Extract description
            desc_elem = await new_page.query_selector('#jobDescriptionText')
            description = await desc_elem.inner_text() if desc_elem else None
            
            await new_page.close()
            return description
            
        except Exception as e:
            logger.debug(f"Could not get full description: {str(e)}")
            return None
    
    def _parse_salary(self, salary_text: str) -> tuple[Optional[int], Optional[int]]:
        """Parse salary from Indeed format"""
        try:
            # Examples: "$80,000 - $120,000 a year", "$50 an hour", "$5,000 a month"
            
            # Extract all numbers
            numbers = re.findall(r'\$?([\d,]+)', salary_text)
            
            if not numbers:
                return None, None
            
            # Convert to integers
            nums = [int(n.replace(',', '')) for n in numbers]
            
            # Determine period and convert to annual
            text_lower = salary_text.lower()
            
            if 'hour' in text_lower:
                # Hourly to annual (40 hrs/week, 52 weeks)
                nums = [n * 2080 for n in nums]
            elif 'month' in text_lower:
                # Monthly to annual
                nums = [n * 12 for n in nums]
            elif 'week' in text_lower:
                # Weekly to annual
                nums = [n * 52 for n in nums]
            
            # Return range or single value
            if len(nums) >= 2:
                return nums[0], nums[1]
            elif len(nums) == 1:
                return nums[0], nums[0]
            
        except Exception as e:
            logger.error(f"Error parsing salary '{salary_text}': {str(e)}")
        
        return None, None
    
    async def _parse_posted_date(self, date_elem) -> Optional[datetime]:
        """Parse 'Posted X days ago' into datetime"""
        try:
            date_text = await date_elem.inner_text()
            
            # Extract number
            match = re.search(r'(\d+)', date_text)
            if not match:
                # "Just posted" or "Today"
                return datetime.now(timezone.utc)
            
            days_ago = int(match.group(1))
            
            if 'hour' in date_text.lower():
                return datetime.now(timezone.utc) - timedelta(hours=days_ago)
            else:  # days
                return datetime.now(timezone.utc) - timedelta(days=days_ago)
                
        except Exception:
            return None
    
    async def _random_delay(self, min_ms: int = None, max_ms: int = None):
        """Add random delay"""
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
    """Test Indeed scraper"""
    scraper = IndeedScraper()
    
    try:
        await scraper.initialize()
        
        jobs = await scraper.search_jobs(
            keywords="AI Engineer",
            location="Remote",
            max_results=10,
            remote_only=True
        )
        
        print(f"\n✓ Found {len(jobs)} jobs")
        
        for job in jobs[:3]:
            print(f"\n📋 {job['title']} at {job['company']}")
            print(f"   Location: {job['location']}")
            print(f"   Salary: ${job['salary_min']:,} - ${job['salary_max']:,}" if job['salary_min'] else "   Salary: Not listed")
            print(f"   URL: {job['url']}")
        
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
