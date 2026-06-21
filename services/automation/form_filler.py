"""
Browser Automation Engine
Handles form filling and application submission using Playwright
"""

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from typing import Dict, Optional, List, Any
import asyncio
import random
from datetime import datetime, timezone
from pathlib import Path

from config.settings import settings
from utils.logger import logger


class FormFillingEngine:
    """
    Intelligent form filling engine
    Handles various application form types across platforms
    """
    
    # Common form field mappings
    FIELD_MAPPINGS = {
        'name': ['name', 'full_name', 'fullname', 'firstname', 'first_name', 
                 'lastname', 'last_name', 'applicant_name'],
        'email': ['email', 'email_address', 'e-mail', 'mail'],
        'phone': ['phone', 'telephone', 'mobile', 'phone_number', 'contact'],
        'location': ['location', 'city', 'address', 'current_location'],
        'linkedin': ['linkedin', 'linkedin_url', 'linkedin_profile'],
        'github': ['github', 'github_url', 'github_profile'],
        'portfolio': ['portfolio', 'website', 'personal_website', 'portfolio_url'],
        'resume': ['resume', 'cv', 'upload_resume', 'attach_resume'],
        'cover_letter': ['cover_letter', 'coverletter', 'letter', 'message'],
        'salary': ['salary', 'expected_salary', 'salary_expectation', 'compensation'],
        'start_date': ['start_date', 'availability', 'available_from', 'join_date'],
        'work_auth': ['work_authorization', 'work_auth', 'visa', 'authorization'],
        'sponsorship': ['sponsorship', 'visa_sponsorship', 'require_sponsorship'],
        'remote': ['remote', 'remote_work', 'work_from_home'],
        'relocate': ['relocate', 'relocation', 'willing_to_relocate']
    }
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.screenshots_dir = Path("screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)
        
    async def initialize(self):
        """Initialize browser with anti-detection measures"""
        logger.info("🔧 Initializing browser automation engine...")
        
        playwright = await async_playwright().start()
        
        # Launch browser with stealth
        self.browser = await playwright.chromium.launch(
            headless=settings.headless_browser,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--no-sandbox'
            ]
        )
        
        # Create context with realistic fingerprint
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York'
        )
        
        # Add stealth scripts
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        self.page = await self.context.new_page()
        
        logger.info("✓ Browser initialized")
    
    async def fill_application_form(self, 
                                   job_url: str,
                                   user_data: Dict,
                                   resume_path: str,
                                   cover_letter_text: str) -> Dict:
        """
        Fill and submit job application form
        
        Args:
            job_url: URL of job application page
            user_data: User profile data
            resume_path: Path to tailored resume
            cover_letter_text: Cover letter text
        
        Returns:
            Dictionary with submission status and metadata
        """
        logger.info(f"📝 Filling application form: {job_url}")
        
        result = {
            'status': 'pending',
            'url': job_url,
            'timestamp': datetime.now(timezone.utc),
            'screenshots': [],
            'errors': [],
            'fields_filled': []
        }
        
        try:
            assert self.page is not None
            # Navigate to job page
            await self.page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await self._random_delay(2000, 4000)

            # Take screenshot of initial page
            screenshot_path = await self._take_screenshot('initial_page')
            result['screenshots'].append(screenshot_path)

            # Detect and click "Apply" button
            apply_button = await self._find_apply_button()

            if not apply_button:
                result['status'] = 'failed'
                result['errors'].append('Could not find Apply button')
                return result

            await apply_button.click()
            await asyncio.sleep(2)

            # Wait for form to load
            await self.page.wait_for_load_state('domcontentloaded')
            
            # Detect form fields
            fields = await self._detect_form_fields()
            logger.info(f"Detected {len(fields)} form fields")
            
            # Fill fields intelligently
            for field_type, selectors in fields.items():
                for selector in selectors:
                    try:
                        filled = await self._fill_field(
                            selector,
                            field_type,
                            user_data,
                            resume_path,
                            cover_letter_text
                        )
                        
                        if filled:
                            result['fields_filled'].append(field_type)
                            await self._random_delay(500, 1500)
                        
                    except Exception as e:
                        logger.debug(f"Could not fill {field_type}: {str(e)}")
                        continue
            
            # Take screenshot before submission
            screenshot_path = await self._take_screenshot('before_submit')
            result['screenshots'].append(screenshot_path)
            
            # Check for CAPTCHA
            if await self._detect_captcha():
                logger.warning("⚠️ CAPTCHA detected")
                result['status'] = 'captcha_required'
                result['errors'].append('CAPTCHA detected - requires human intervention')
                return result
            
            # Validate before submission
            validation_errors = await self._validate_form()
            
            if validation_errors:
                result['status'] = 'validation_failed'
                result['errors'].extend(validation_errors)
                return result
            
            # Submit form
            if not settings.test_mode:
                submit_button = await self._find_submit_button()
                
                if submit_button:
                    await submit_button.click()
                    await asyncio.sleep(3)
                    
                    # Wait for confirmation
                    await self.page.wait_for_load_state('domcontentloaded', timeout=10000)
                    
                    # Take confirmation screenshot
                    screenshot_path = await self._take_screenshot('confirmation')
                    result['screenshots'].append(screenshot_path)
                    
                    # Check for success message
                    if await self._check_success_confirmation():
                        result['status'] = 'success'
                        logger.info("✓ Application submitted successfully")
                    else:
                        result['status'] = 'uncertain'
                        result['errors'].append('Could not confirm submission')
                else:
                    result['status'] = 'failed'
                    result['errors'].append('Could not find Submit button')
            else:
                logger.info("🧪 Test mode - skipping actual submission")
                result['status'] = 'test_mode'
            
            return result
            
        except Exception as e:
            logger.error(f"Error filling form: {str(e)}")
            result['status'] = 'error'
            result['errors'].append(str(e))
            
            # Take error screenshot
            screenshot_path = await self._take_screenshot('error')
            result['screenshots'].append(screenshot_path)
            
            return result
    
    async def _detect_form_fields(self) -> Dict[str, List[str]]:
        """Detect form fields on the page"""
        assert self.page is not None
        detected_fields = {}

        # Get all input, select, and textarea elements
        elements = await self.page.query_selector_all('input, select, textarea')
        
        for element in elements:
            # Get field identifiers
            name = await element.get_attribute('name') or ''
            id_attr = await element.get_attribute('id') or ''
            placeholder = await element.get_attribute('placeholder') or ''
            label_text = ''
            
            # Try to find associated label
            try:
                label = await element.evaluate('''
                    el => {
                        let label = el.closest('label');
                        if (!label) {
                            const id = el.id;
                            if (id) label = document.querySelector(`label[for="${id}"]`);
                        }
                        return label ? label.innerText : '';
                    }
                ''')
                label_text = label or ''
            except:
                pass
            
            # Combine all text for matching
            field_text = f"{name} {id_attr} {placeholder} {label_text}".lower()
            
            # Match to field types
            for field_type, keywords in self.FIELD_MAPPINGS.items():
                if any(keyword in field_text for keyword in keywords):
                    selector = f'#{id_attr}' if id_attr else f'[name="{name}"]'
                    
                    if field_type not in detected_fields:
                        detected_fields[field_type] = []
                    detected_fields[field_type].append(selector)
        
        return detected_fields
    
    async def _fill_field(self, selector: str, field_type: str,
                         user_data: Dict, resume_path: str,
                         cover_letter_text: str) -> bool:
        """Fill a specific form field"""
        assert self.page is not None
        element = await self.page.query_selector(selector)
        
        if not element:
            return False
        
        # Get element type
        tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
        input_type = await element.get_attribute('type') or 'text'
        
        try:
            # Handle different field types
            if field_type == 'name':
                await element.fill(user_data.get('name', ''))
            
            elif field_type == 'email':
                await element.fill(user_data.get('email', ''))
            
            elif field_type == 'phone':
                await element.fill(user_data.get('phone', ''))
            
            elif field_type == 'location':
                await element.fill(user_data.get('location', ''))
            
            elif field_type == 'linkedin':
                await element.fill(user_data.get('linkedin', ''))
            
            elif field_type == 'github':
                await element.fill(user_data.get('github', ''))
            
            elif field_type == 'portfolio':
                await element.fill(user_data.get('portfolio', ''))
            
            elif field_type == 'resume' and input_type == 'file':
                await element.set_input_files(resume_path)
            
            elif field_type == 'cover_letter':
                await element.fill(cover_letter_text)
            
            elif field_type == 'salary':
                # Provide range, not exact number
                salary_range = f"${user_data.get('salary_min', 80000)} - ${user_data.get('salary_max', 120000)}"
                await element.fill(salary_range)
            
            elif field_type == 'start_date':
                if tag_name == 'select':
                    await element.select_option('2-weeks')
                else:
                    await element.fill('2 weeks notice')
            
            elif field_type == 'work_auth':
                if tag_name == 'select':
                    await element.select_option('authorized')
                else:
                    await element.click()  # Checkbox
            
            elif field_type == 'sponsorship':
                # Answer based on user profile
                needs_sponsorship = user_data.get('visa_sponsorship_required', False)
                if input_type == 'checkbox':
                    if needs_sponsorship:
                        await element.click()
                elif tag_name == 'select':
                    value = 'yes' if needs_sponsorship else 'no'
                    await element.select_option(value)
            
            elif field_type == 'remote':
                # If asking about remote preference
                if input_type == 'checkbox':
                    await element.click()  # Yes to remote
            
            elif field_type == 'relocate':
                willing = len(user_data.get('willing_to_relocate', [])) > 0
                if input_type == 'checkbox' and willing:
                    await element.click()
            
            return True
            
        except Exception as e:
            logger.debug(f"Error filling {field_type}: {str(e)}")
            return False
    
    async def _find_apply_button(self) -> Optional[Any]:
        """Find and return the Apply button"""
        assert self.page is not None
        # Common apply button patterns
        patterns = [
            'button:has-text("Apply")',
            'a:has-text("Apply")',
            'button:has-text("Easy Apply")',
            'button:has-text("Submit Application")',
            '[data-testid="apply-button"]',
            '.apply-button',
            '#apply-button'
        ]

        for pattern in patterns:
            button = await self.page.query_selector(pattern)
            if button:
                return button
        
        return None
    
    async def _find_submit_button(self) -> Optional[Any]:
        """Find submit button"""
        assert self.page is not None
        patterns = [
            'button[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Submit Application")',
            'button:has-text("Send Application")',
            'input[type="submit"]'
        ]

        for pattern in patterns:
            button = await self.page.query_selector(pattern)
            if button:
                return button
        
        return None
    
    async def _detect_captcha(self) -> bool:
        """Detect if CAPTCHA is present"""
        assert self.page is not None
        captcha_indicators = [
            'iframe[src*="recaptcha"]',
            'iframe[src*="hcaptcha"]',
            '.g-recaptcha',
            '.h-captcha',
            '[data-captcha]'
        ]

        for indicator in captcha_indicators:
            element = await self.page.query_selector(indicator)
            if element:
                return True
        
        return False
    
    async def _validate_form(self) -> List[str]:
        """Validate form before submission"""
        assert self.page is not None
        errors = []

        # Check for required unfilled fields
        required_fields = await self.page.query_selector_all('[required]:not([disabled])')
        
        for field in required_fields:
            value = await field.evaluate('el => el.value')
            if not value or value.strip() == '':
                name = await field.get_attribute('name') or 'unknown field'
                errors.append(f'Required field "{name}" is empty')
        
        return errors
    
    async def _check_success_confirmation(self) -> bool:
        """Check for success confirmation message"""
        assert self.page is not None
        success_indicators = [
            'text=Application submitted',
            'text=Thank you for applying',
            'text=Successfully submitted',
            'text=Application received',
            '.success-message',
            '[data-test="success"]'
        ]

        for indicator in success_indicators:
            element = await self.page.query_selector(indicator)
            if element:
                return True
        
        return False
    
    async def _take_screenshot(self, name: str) -> str:
        """Take screenshot for verification"""
        assert self.page is not None
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"{name}_{timestamp}.png"
        filepath = self.screenshots_dir / filename

        await self.page.screenshot(path=str(filepath), full_page=True)
        
        return str(filepath)
    
    async def _random_delay(self, min_ms: Optional[int] = None, max_ms: Optional[int] = None):
        """Human-like delay"""
        min_ms = min_ms or settings.min_delay_between_actions
        max_ms = max_ms or settings.max_delay_between_actions
        
        delay = random.uniform(min_ms / 1000, max_ms / 1000)
        await asyncio.sleep(delay)
    
    async def close(self):
        """Close browser"""
        if self.browser:
            await self.browser.close()
            logger.info("✓ Browser closed")


# Example usage
if __name__ == "__main__":
    async def test():
        engine = FormFillingEngine()
        await engine.initialize()
        
        user_data = {
            'name': 'Satyam Shivam',
            'email': 'shivamsatyam35@gmail.com',
            'phone': '+91 9852015381',
            'location': 'New Delhi, India',
            'salary_min': 80000,
            'salary_max': 120000,
            'visa_sponsorship_required': True
        }
        
        # Test form filling (dry run)
        result = await engine.fill_application_form(
            job_url='https://example.com/job',
            user_data=user_data,
            resume_path='/tmp/resume.docx',
            cover_letter_text='Dear Hiring Manager...'
        )
        
        print(f"Result: {result['status']}")
        print(f"Fields filled: {result['fields_filled']}")
        
        await engine.close()
    
    asyncio.run(test())
