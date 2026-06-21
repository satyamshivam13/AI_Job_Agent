"""
Configuration settings for AI Job Agent
Loads environment variables and provides typed settings
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import List, Optional
from enum import Enum
import os


class Environment(str, Enum):
    """Environment types"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LLMProvider(str, Enum):
    """Supported LLM providers"""
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    TOGETHER = "together"


class VectorDBType(str, Enum):
    """Supported vector databases"""
    CHROMADB = "chromadb"
    PINECONE = "pinecone"
    FAISS = "faiss"


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )
    
    # =============================================================================
    # LLM PROVIDERS
    # =============================================================================
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    together_api_key: Optional[str] = Field(default=None, alias="TOGETHER_API_KEY")
    
    # Primary LLM provider
    llm_provider: LLMProvider = Field(default=LLMProvider.GROQ)
    
    # =============================================================================
    # EMBEDDINGS
    # =============================================================================
    voyage_api_key: Optional[str] = Field(default=None, alias="VOYAGE_API_KEY")
    use_openai_embeddings: bool = Field(default=False)
    
    # =============================================================================
    # DATABASE
    # =============================================================================
    database_url: str = Field(default="sqlite:///./dev.db", alias="DATABASE_URL")
    supabase_url: Optional[str] = Field(default=None, alias="SUPABASE_URL")
    supabase_key: Optional[str] = Field(default=None, alias="SUPABASE_KEY")
    
    # =============================================================================
    # VECTOR DATABASE
    # =============================================================================
    vector_db_type: VectorDBType = Field(default=VectorDBType.CHROMADB)
    chroma_db_path: str = Field(default="./data/chroma")
    pinecone_api_key: Optional[str] = Field(default=None, alias="PINECONE_API_KEY")
    pinecone_environment: str = Field(default="us-east-1")
    
    # =============================================================================
    # JOB PLATFORM CREDENTIALS
    # =============================================================================
    linkedin_email: Optional[str] = Field(default=None, alias="LINKEDIN_EMAIL")
    linkedin_password: Optional[str] = Field(default=None, alias="LINKEDIN_PASSWORD")
    
    indeed_email: Optional[str] = Field(default=None, alias="INDEED_EMAIL")
    indeed_password: Optional[str] = Field(default=None, alias="INDEED_PASSWORD")
    
    glassdoor_email: Optional[str] = Field(default=None, alias="GLASSDOOR_EMAIL")
    glassdoor_password: Optional[str] = Field(default=None, alias="GLASSDOOR_PASSWORD")
    
    wellfound_email: Optional[str] = Field(default=None, alias="WELLFOUND_EMAIL")
    wellfound_password: Optional[str] = Field(default=None, alias="WELLFOUND_PASSWORD")
    
    naukri_email: Optional[str] = Field(default=None, alias="NAUKRI_EMAIL")
    naukri_password: Optional[str] = Field(default=None, alias="NAUKRI_PASSWORD")
    
    # =============================================================================
    # BROWSER AUTOMATION
    # =============================================================================
    headless_browser: bool = Field(default=True)
    use_proxy: bool = Field(default=False)
    proxy_url: Optional[str] = Field(default=None, alias="PROXY_URL")
    
    # =============================================================================
    # CAPTCHA
    # =============================================================================
    two_captcha_api_key: Optional[str] = Field(default=None, alias="TWO_CAPTCHA_API_KEY")
    enable_captcha_solver: bool = Field(default=False)
    
    # =============================================================================
    # EMAIL NOTIFICATIONS
    # =============================================================================
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    smtp_username: Optional[str] = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    notification_email: Optional[str] = Field(default=None, alias="NOTIFICATION_EMAIL")
    
    # =============================================================================
    # SLACK NOTIFICATIONS
    # =============================================================================
    slack_webhook_url: Optional[str] = Field(default=None, alias="SLACK_WEBHOOK_URL")
    
    # =============================================================================
    # MONITORING
    # =============================================================================
    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    enable_sentry: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    
    # =============================================================================
    # APPLICATION SETTINGS
    # =============================================================================
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    max_applications_per_day: int = Field(default=50)
    max_applications_per_platform: int = Field(default=20)
    
    # Automation delays (milliseconds)
    min_delay_between_actions: int = Field(default=1000)
    max_delay_between_actions: int = Field(default=3000)
    
    # Retry settings
    max_retries: int = Field(default=3)
    retry_delay: int = Field(default=5)
    
    # =============================================================================
    # USER PROFILE
    # =============================================================================
    user_name: str = Field(default="Satyam Shivam")
    user_email: str = Field(default="shivamsatyam35@gmail.com")
    user_phone: str = Field(default="+919852015381")
    user_location: str = Field(default="New Delhi, India")
    
    # =============================================================================
    # API SERVER
    # =============================================================================
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_workers: int = Field(default=4)
    
    jwt_secret_key: str = Field(default="change-this-to-random-secret-key")
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30)
    
    # =============================================================================
    # REDIS
    # =============================================================================
    redis_url: str = Field(default="redis://localhost:6379/0")
    
    # =============================================================================
    # SCHEDULING
    # =============================================================================
    daily_run_time: str = Field(default="09:00")
    timezone: str = Field(default="Asia/Kolkata")
    
    # =============================================================================
    # FEATURE FLAGS
    # =============================================================================
    enable_auto_apply: bool = Field(default=True)
    enable_resume_tailoring: bool = Field(default=True)
    enable_cover_letter_generation: bool = Field(default=True)
    enable_duplicate_detection: bool = Field(default=True)
    enable_analytics: bool = Field(default=True)
    
    require_human_approval: bool = Field(default=False)
    enable_screenshot_capture: bool = Field(default=True)
    enable_application_preview: bool = Field(default=True)
    
    # =============================================================================
    # DEVELOPMENT
    # =============================================================================
    debug: bool = Field(default=False)
    reload: bool = Field(default=True)
    test_mode: bool = Field(default=False)
    
    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, v):
        """Validate environment value"""
        if isinstance(v, str):
            return Environment(v.lower())
        return v
    
    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment == Environment.PRODUCTION
    
    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment == Environment.DEVELOPMENT
    
    @property
    def is_testing(self) -> bool:
        """Check if running in testing"""
        return self.environment == Environment.TESTING
    
    def get_llm_api_key(self) -> Optional[str]:
        """Get API key for the configured LLM provider"""
        if self.llm_provider == LLMProvider.GROQ:
            return self.groq_api_key
        elif self.llm_provider == LLMProvider.OPENAI:
            return self.openai_api_key
        elif self.llm_provider == LLMProvider.ANTHROPIC:
            return self.anthropic_api_key
        elif self.llm_provider == LLMProvider.TOGETHER:
            return self.together_api_key
        return None
    
    def validate_required_settings(self) -> List[str]:
        """Validate that required settings are present"""
        errors = []
        
        # Check LLM provider
        if not self.get_llm_api_key():
            errors.append(f"Missing API key for LLM provider: {self.llm_provider}")
        
        # Check embeddings
        if not self.use_openai_embeddings and not self.voyage_api_key:
            errors.append("Missing embedding provider (Voyage API or OpenAI)")
        
        # Check database
        if not self.database_url:
            errors.append("Missing DATABASE_URL")
        
        return errors


# Create global settings instance
settings = Settings()

# Validate settings on startup
validation_errors = settings.validate_required_settings()
if validation_errors and not settings.is_testing:
    print("[WARN] Configuration errors found:")
    for error in validation_errors:
        print(f"  - {error}")
    print("\nPlease check your .env file and ensure all required variables are set.")
    print("See .env.example for reference.")
