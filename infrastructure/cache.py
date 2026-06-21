"""
Production-Grade Redis Caching Layer
Implements intelligent caching for LLM responses, API calls, and database queries
"""

import redis
import json
import hashlib
from typing import Optional, Any, Callable, Dict
from datetime import timedelta, datetime
from functools import wraps
import pickle
from config.settings import settings


class RedisCache:
    """Production Redis caching with intelligent key management"""
    
    def __init__(self):
        """Initialize Redis connection"""
        self.redis = redis.Redis.from_url(
            getattr(settings, 'redis_url', 'redis://localhost:6379/0'),
            decode_responses=False,  # Keep bytes for pickle
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from arguments"""
        # Create a stable hash of arguments
        key_data = json.dumps({
            "args": args,
            "kwargs": kwargs
        }, sort_keys=True)
        
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"{prefix}:{key_hash}"
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = self.redis.get(key)
            if value:
                return pickle.loads(value)
            return None
        except Exception as e:
            print(f"Redis GET error: {e}")
            return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache with optional TTL"""
        try:
            serialized = pickle.dumps(value)
            if ttl:
                return bool(self.redis.setex(key, ttl, serialized))
            else:
                return bool(self.redis.set(key, serialized))
        except Exception as e:
            print(f"Redis SET error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        try:
            return int(self.redis.delete(key)) > 0  # type: ignore[arg-type]
        except Exception as e:
            print(f"Redis DELETE error: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        try:
            keys = self.redis.keys(pattern)
            if keys:
                return int(self.redis.delete(*keys))  # type: ignore[arg-type]
            return 0
        except Exception as e:
            print(f"Redis DELETE PATTERN error: {e}")
            return 0
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            return int(self.redis.exists(key)) > 0  # type: ignore[arg-type]
        except Exception as e:
            print(f"Redis EXISTS error: {e}")
            return False
    
    def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter"""
        try:
            return int(self.redis.incrby(key, amount))  # type: ignore[arg-type]
        except Exception as e:
            print(f"Redis INCREMENT error: {e}")
            return 0
    
    def get_ttl(self, key: str) -> int:
        """Get remaining TTL for key"""
        try:
            return int(self.redis.ttl(key))  # type: ignore[arg-type]
        except Exception as e:
            print(f"Redis TTL error: {e}")
            return -1


# Global cache instance — lazy singleton, connects only when first used
_cache_instance = None

def get_cache() -> "RedisCache":
    global _cache_instance
    if _cache_instance is None:
        try:
            _cache_instance = RedisCache()
        except Exception:
            _cache_instance = RedisCache.__new__(RedisCache)
            _cache_instance.redis = None  # type: ignore[assignment]
    return _cache_instance

class _LazyCache:
    def __getattr__(self, name):
        return getattr(get_cache(), name)

cache = _LazyCache()


class CacheTTL:
    """Cache TTL constants (in seconds)"""
    MINUTE = 60
    HOUR = 3600
    DAY = 86400
    WEEK = 604800
    
    # Specific caching policies
    LLM_RESPONSE = HOUR * 24  # 24 hours for LLM responses
    JOB_SEARCH = HOUR  # 1 hour for job search results
    RESUME_GENERATION = DAY  # 1 day for generated resumes
    USER_PROFILE = HOUR * 6  # 6 hours for user profiles
    API_RESPONSE = MINUTE * 15  # 15 minutes for API responses


def cached(
    prefix: str,
    ttl: int = CacheTTL.HOUR,
    key_func: Optional[Callable] = None
):
    """
    Decorator for caching function results
    
    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
        key_func: Optional function to generate custom cache key
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache._generate_key(prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            cache.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


class LLMCache:
    """Specialized cache for LLM responses to save costs"""
    
    @staticmethod
    def _create_prompt_hash(prompt: str, model: str) -> str:
        """Create hash from prompt and model"""
        content = f"{model}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    @classmethod
    def get_response(cls, prompt: str, model: str) -> Optional[Dict[str, Any]]:
        """Get cached LLM response"""
        cache_key = f"llm:{cls._create_prompt_hash(prompt, model)}"
        return cache.get(cache_key)
    
    @classmethod
    def set_response(
        cls,
        prompt: str,
        model: str,
        response: str,
        cost_usd: float = 0.0
    ) -> bool:
        """Cache LLM response"""
        cache_key = f"llm:{cls._create_prompt_hash(prompt, model)}"
        
        cached_data = {
            "response": response,
            "model": model,
            "cost_usd": cost_usd,
            "cached_at": str(datetime.now())
        }
        
        # Track cost savings
        cost_key = f"llm_cost_saved:{model}"
        cache.increment(cost_key, int(cost_usd * 1000))  # Store in millidollars
        
        return cache.set(cache_key, cached_data, CacheTTL.LLM_RESPONSE)
    
    @classmethod
    def get_cost_savings(cls, model: str) -> float:
        """Get total cost saved from caching"""
        cost_key = f"llm_cost_saved:{model}"
        millidollars = cache.get(cost_key) or 0
        return millidollars / 1000.0


class JobSearchCache:
    """Specialized cache for job search results"""
    
    @classmethod
    def get_jobs(
        cls,
        query: str,
        location: str,
        remote: bool,
        limit: int
    ) -> Optional[list]:
        """Get cached job search results"""
        cache_key = cache._generate_key(
            "jobs",
            query=query,
            location=location,
            remote=remote,
            limit=limit
        )
        return cache.get(cache_key)
    
    @classmethod
    def set_jobs(
        cls,
        query: str,
        location: str,
        remote: bool,
        limit: int,
        jobs: list
    ) -> bool:
        """Cache job search results"""
        cache_key = cache._generate_key(
            "jobs",
            query=query,
            location=location,
            remote=remote,
            limit=limit
        )
        return cache.set(cache_key, jobs, CacheTTL.JOB_SEARCH)


class RateLimitCache:
    """Redis-based rate limiting (production-grade)"""
    
    @classmethod
    def check_rate_limit(
        cls,
        user_id: str,
        limit: int,
        window: int
    ) -> tuple[bool, int]:
        """
        Check if user is within rate limit
        
        Returns:
            (allowed, remaining): Tuple of whether request is allowed and remaining quota
        """
        key = f"ratelimit:{user_id}"
        current = cache.redis.get(key)
        
        if current is None:
            # First request in window
            cache.redis.setex(key, window, 1)
            return True, limit - 1
        
        current_count = int(current)
        
        if current_count >= limit:
            # Rate limit exceeded
            ttl = cache.get_ttl(key)
            return False, 0
        
        # Increment counter
        cache.redis.incr(key)
        return True, limit - current_count - 1


class SessionCache:
    """Cache for user sessions and temporary data"""
    
    @classmethod
    def set_session(cls, session_id: str, data: dict, ttl: int = 3600) -> bool:
        """Store session data"""
        key = f"session:{session_id}"
        return cache.set(key, data, ttl)
    
    @classmethod
    def get_session(cls, session_id: str) -> Optional[dict]:
        """Get session data"""
        key = f"session:{session_id}"
        return cache.get(key)
    
    @classmethod
    def delete_session(cls, session_id: str) -> bool:
        """Delete session"""
        key = f"session:{session_id}"
        return cache.delete(key)


# Cache monitoring
class CacheMetrics:
    """Track cache performance metrics"""
    
    @classmethod
    def record_hit(cls, cache_type: str):
        """Record cache hit"""
        cache.increment(f"cache_hits:{cache_type}")
    
    @classmethod
    def record_miss(cls, cache_type: str):
        """Record cache miss"""
        cache.increment(f"cache_misses:{cache_type}")
    
    @classmethod
    def get_hit_rate(cls, cache_type: str) -> float:
        """Calculate cache hit rate"""
        hits = cache.get(f"cache_hits:{cache_type}") or 0
        misses = cache.get(f"cache_misses:{cache_type}") or 0
        
        total = hits + misses
        if total == 0:
            return 0.0
        
        return (hits / total) * 100.0
