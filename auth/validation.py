"""
Production-Grade Input Validation & Sanitization
Prevents SQL injection, XSS, and other injection attacks
"""

from typing import Optional, List, Any, Annotated
from pydantic import BaseModel, validator, Field, field_validator, model_validator
from fastapi import HTTPException, status
import re
import bleach
from datetime import datetime


class InputValidator:
    """Centralized input validation and sanitization"""
    
    # Regex patterns for validation
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    URL_PATTERN = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    PHONE_PATTERN = re.compile(r'^\+?1?\d{9,15}$')
    
    # SQL injection patterns to block
    SQL_INJECTION_PATTERNS = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b)",
        r"(--|#|\/\*|\*\/)",
        r"(\bOR\b.*=.*)",
        r"(\bAND\b.*=.*)",
        r"(UNION.*SELECT)",
        r"(;.*DROP)",
    ]
    
    # XSS patterns to block
    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"onerror=",
        r"onload=",
        r"onclick=",
    ]
    
    @classmethod
    def sanitize_string(cls, value: str, allow_html: bool = False) -> str:
        """Sanitize string input to prevent XSS"""
        if not value:
            return value
        
        if not allow_html:
            # Strip all HTML tags
            value = bleach.clean(value, tags=[], strip=True)
        else:
            # Allow only safe HTML tags
            value = bleach.clean(
                value,
                tags=['p', 'br', 'strong', 'em', 'u', 'a', 'ul', 'ol', 'li'],
                attributes={'a': ['href', 'title']},
                strip=True
            )
        
        return value.strip()
    
    @classmethod
    def check_sql_injection(cls, value: str) -> None:
        """Check for SQL injection patterns"""
        if not value:
            return
        
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid input: potential SQL injection detected"
                )
    
    @classmethod
    def check_xss(cls, value: str) -> None:
        """Check for XSS patterns"""
        if not value:
            return
        
        for pattern in cls.XSS_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid input: potential XSS attack detected"
                )
    
    @classmethod
    def validate_email(cls, email: str) -> str:
        """Validate email format"""
        if not cls.EMAIL_PATTERN.match(email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format"
            )
        return email.lower()
    
    @classmethod
    def validate_url(cls, url: str) -> str:
        """Validate URL format"""
        if not cls.URL_PATTERN.match(url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid URL format"
            )
        return url
    
    @classmethod
    def validate_phone(cls, phone: str) -> str:
        """Validate phone number format"""
        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        if not cls.PHONE_PATTERN.match(cleaned):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid phone number format"
            )
        return cleaned


# Validated Pydantic models for API requests

class JobSearchRequest(BaseModel):
    """Validated job search request"""
    query: Annotated[str, Field(min_length=1, max_length=200, description="Search query")]
    location: Optional[Annotated[str, Field(max_length=100)]] = Field(None, description="Job location")
    remote: Optional[bool] = Field(
        False,
        description="Remote jobs only"
    )
    experience_level: Optional[Annotated[str, Field(max_length=50)]] = None
    limit: Optional[int] = Field(
        50,
        ge=1,
        le=100,
        description="Max results"
    )
    
    @field_validator('query')
    def validate_query(cls, v):
        """Validate search query"""
        v = InputValidator.sanitize_string(v)
        InputValidator.check_sql_injection(v)
        InputValidator.check_xss(v)
        return v
    
    @field_validator('location')
    def validate_location(cls, v):
        """Validate location"""
        if v:
            v = InputValidator.sanitize_string(v)
            InputValidator.check_sql_injection(v)
        return v


class ResumeGenerationRequest(BaseModel):
    """Validated resume generation request"""
    job_id: Annotated[str, Field(min_length=1, max_length=100)]
    variant: Optional[Annotated[str, Field(max_length=50)]] = "balanced"
    custom_skills: Optional[List[Annotated[str, Field(max_length=100)]]] = None
    
    @field_validator('job_id')
    def validate_job_id(cls, v):
        """Validate job ID"""
        InputValidator.check_sql_injection(v)
        InputValidator.check_xss(v)
        return v
    
    @field_validator('custom_skills')
    def validate_skills(cls, v):
        """Validate each skill"""
        if v:
            v = InputValidator.sanitize_string(v)
            InputValidator.check_xss(v)
        return v


class ApplicationRequest(BaseModel):
    """Validated application submission request"""
    job_id: Annotated[str, Field(min_length=1, max_length=100)]
    resume_id: Annotated[str, Field(min_length=1, max_length=100)]
    cover_letter_id: Optional[Annotated[str, Field(max_length=100)]] = None
    additional_info: Optional[Annotated[str, Field(max_length=1000)]] = None
    
    @field_validator('job_id', 'resume_id', 'cover_letter_id')
    def validate_ids(cls, v):
        """Validate IDs"""
        if v:
            InputValidator.check_sql_injection(v)
            InputValidator.check_xss(v)
        return v
    
    @field_validator('additional_info')
    def validate_additional_info(cls, v):
        """Validate additional info"""
        if v:
            v = InputValidator.sanitize_string(v, allow_html=False)
            InputValidator.check_sql_injection(v)
            InputValidator.check_xss(v)
        return v


class UserProfileUpdate(BaseModel):
    """Validated user profile update"""
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[Annotated[str, Field(max_length=100)]] = None
    skills: Optional[List[Annotated[str, Field(max_length=100)]]] = None
    experience_years: Optional[int] = Field(None, ge=0, le=50)
    
    @field_validator('email')
    def validate_email(cls, v):
        """Validate email"""
        if v:
            return InputValidator.validate_email(v)
        return v
    
    @field_validator('phone')
    def validate_phone(cls, v):
        """Validate phone"""
        if v:
            return InputValidator.validate_phone(v)
        return v
    
    @field_validator('location')
    def validate_location(cls, v):
        """Validate location"""
        if v:
            v = InputValidator.sanitize_string(v)
            InputValidator.check_sql_injection(v)
        return v
    
    @field_validator('skills')
    def validate_skills(cls, v):
        """Validate each skill"""
        if v:
            v = InputValidator.sanitize_string(v)
            InputValidator.check_xss(v)
        return v


class PaginationParams(BaseModel):
    """Validated pagination parameters"""
    page: int = Field(1, ge=1, le=1000, description="Page number")
    page_size: int = Field(50, ge=1, le=100, description="Items per page")
    sort_by: Optional[Annotated[str, Field(max_length=50)]] = None
    sort_order: Optional[Annotated[str, Field(max_length=4)]] = "desc"
    
    @field_validator('sort_by')
    def validate_sort_by(cls, v):
        """Validate sort field"""
        if v:
            # Only allow alphanumeric and underscore
            if not re.match(r'^[a-zA-Z0-9_]+$', v):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid sort field"
                )
        return v
    
    @field_validator('sort_order')
    def validate_sort_order(cls, v):
        """Validate sort order"""
        if v and v.lower() not in ['asc', 'desc']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sort order must be 'asc' or 'desc'"
            )
        return v.lower() if v else v
