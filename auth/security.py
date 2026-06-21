"""
Production-Grade Authentication & Authorization System
Implements JWT, OAuth2, RBAC, and API security
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import Request,  Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
import secrets
from sqlalchemy.orm import Session

# Security Configuration
import os

def _load_secret_key() -> str:
    """Load JWT secret key from environment. Fail fast if missing."""
    key = os.environ.get("JWT_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if not key:
        # Dev fallback with a loud warning — never silently generate
        import warnings
        key = "dev-insecure-key-set-JWT_SECRET_KEY-in-production"
        warnings.warn(
            "JWT_SECRET_KEY not set — using insecure dev key. "
            "Set JWT_SECRET_KEY environment variable before deploying.",
            RuntimeWarning, stacklevel=2
        )
    if len(key) < 32:
        raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
    return key

SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# API Key scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class TokenData(BaseModel):
    """JWT token payload"""
    user_id: str
    username: str
    roles: List[str]
    exp: datetime


class UserRole:
    """Role-Based Access Control (RBAC)"""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"
    API_CLIENT = "api_client"




def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Extract and validate current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        roles: List[str] = payload.get("roles", [])
        
        exp_ts = payload.get("exp")
        if user_id is None or exp_ts is None:
            raise credentials_exception

        token_data = TokenData(
            user_id=user_id,
            username=username,
            roles=roles,
            exp=datetime.fromtimestamp(float(exp_ts), tz=timezone.utc)
        )
        
    except JWTError:
        raise credentials_exception
    
    return token_data

class PermissionChecker:
    """Permission-based access control"""
    
    def __init__(self, required_roles: List[str]):
        self.required_roles = required_roles
    
    def __call__(self, token_data: TokenData = Depends(get_current_user)):
        """Check if user has required role"""
        if not any(role in token_data.roles for role in self.required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {self.required_roles}"
            )
        return token_data

async def get_current_active_user(
    current_user: TokenData = Depends(get_current_user)
) -> TokenData:
    """Validate user is active (not disabled)"""
    # In production, check user.is_active from database
    return current_user


def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """Verify API key for programmatic access"""
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )
    
    # In production, validate against database
    # For now, check against environment variable
    from config.settings import settings
    
    valid_keys = settings.API_KEYS if hasattr(settings, 'API_KEYS') else []
    
    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return True


class RateLimiter:
    """Rate limiting to prevent API abuse"""
    
    def __init__(self, calls: int, period: int):
        """
        Args:
            calls: Number of allowed calls
            period: Time period in seconds
        """
        self.calls = calls
        self.period = period
        self.cache = {}  # In production, use Redis
    
    async def __call__(self, user: TokenData = Depends(get_current_user)):
        """Check rate limit for user"""
        now = datetime.now(timezone.utc)
        user_key = f"ratelimit:{user.user_id}"
        
        # Get user's request history
        if user_key not in self.cache:
            self.cache[user_key] = []
        
        # Remove old requests outside the window
        self.cache[user_key] = [
            req_time for req_time in self.cache[user_key]
            if (now - req_time).total_seconds() < self.period
        ]
        
        # Check if limit exceeded
        if len(self.cache[user_key]) >= self.calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Max {self.calls} requests per {self.period}s"
            )
        
        # Add current request
        self.cache[user_key].append(now)
        
        return user


# Common rate limiters
rate_limit_strict = RateLimiter(calls=10, period=60)  # 10 req/min
rate_limit_normal = RateLimiter(calls=100, period=60)  # 100 req/min
rate_limit_relaxed = RateLimiter(calls=1000, period=60)  # 1000 req/min


# Permission shortcuts
require_admin = PermissionChecker([UserRole.ADMIN])
require_user = PermissionChecker([UserRole.USER, UserRole.ADMIN])
require_readonly = PermissionChecker([UserRole.READONLY, UserRole.USER, UserRole.ADMIN])


class IPRateLimiter:
    """IP-based rate limiter for unauthenticated endpoints."""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._store: dict = {}
    async def __call__(self, request: Request):
        from datetime import timezone as _tz
        ip = getattr(request.client, "host", "unknown")
        key = f"ip_rl:{ip}"
        import time as _t
        now = _t.time()
        self._store[key] = [t for t in self._store.get(key, []) if t > now - self.window_seconds]
        if len(self._store[key]) >= self.max_requests:
            raise HTTPException(status_code=429, detail=f"Too many requests. Max {self.max_requests} per {self.window_seconds}s.",
                headers={"Retry-After": str(self.window_seconds)})
        self._store[key].append(now)

login_rate_limiter = IPRateLimiter(max_requests=10, window_seconds=60)
strict_ip_limiter = IPRateLimiter(max_requests=30, window_seconds=60)
