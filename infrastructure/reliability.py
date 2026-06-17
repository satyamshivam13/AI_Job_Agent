"""
Production-Grade Reliability System
Implements circuit breakers, retry logic, idempotency, and graceful degradation
"""

from typing import Callable, Any, Optional
from datetime import datetime, timedelta, timezone
from functools import wraps
import asyncio
import hashlib
from enum import Enum
import time
from infrastructure.cache import cache
from infrastructure.monitoring import structured_logger, system_errors_total


# ==================== CIRCUIT BREAKER ====================

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern implementation
    Prevents cascading failures by stopping requests to failing services
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: type = Exception
    ):
        """
        Args:
            name: Circuit breaker name
            failure_threshold: Number of failures before opening
            timeout: Seconds to wait before trying again (half-open)
            expected_exception: Exception type to catch
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator for circuit breaker"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if self.state == CircuitState.OPEN:
                # Check if timeout expired
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    structured_logger.log_error(
                        error_type="circuit_breaker",
                        component=self.name,
                        message=f"Circuit breaker {self.name} entering HALF_OPEN state"
                    )
                else:
                    raise Exception(f"Circuit breaker {self.name} is OPEN")
            
            try:
                result = await func(*args, **kwargs)
                self._on_success()
                return result
                
            except self.expected_exception as e:
                self._on_failure()
                raise e
        
        return wrapper
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should try to reset the circuit"""
        if self.last_failure_time is None:
            return True
        
        return (datetime.now(timezone.utc) - self.last_failure_time).total_seconds() >= self.timeout
    
    def _on_success(self):
        """Handle successful request"""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            structured_logger.log_error(
                error_type="circuit_breaker",
                component=self.name,
                message=f"Circuit breaker {self.name} CLOSED (recovered)"
            )
    
    def _on_failure(self):
        """Handle failed request"""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            structured_logger.log_error(
                error_type="circuit_breaker",
                component=self.name,
                message=f"Circuit breaker {self.name} OPEN (too many failures)"
            )
            
            # Update Prometheus metric
            system_errors_total.labels(
                error_type="circuit_breaker_open",
                component=self.name
            ).inc()


# ==================== RETRY LOGIC ====================

class RetryStrategy:
    """Retry strategies"""
    
    @staticmethod
    def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
        """Exponential backoff: 1s, 2s, 4s, 8s, ..."""
        delay = min(base_delay * (2 ** attempt), max_delay)
        return delay
    
    @staticmethod
    def linear_backoff(attempt: int, delay: float = 1.0) -> float:
        """Linear backoff: 1s, 2s, 3s, 4s, ..."""
        return delay * (attempt + 1)
    
    @staticmethod
    def fibonacci_backoff(attempt: int, base_delay: float = 1.0) -> float:
        """Fibonacci backoff: 1s, 1s, 2s, 3s, 5s, 8s, ..."""
        def fib(n):
            if n <= 1:
                return n
            return fib(n-1) + fib(n-2)
        
        return base_delay * fib(attempt)


def retry(
    max_attempts: int = 3,
    backoff_strategy: Callable[[int], float] = RetryStrategy.exponential_backoff,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    Retry decorator with configurable backoff
    
    Args:
        max_attempts: Maximum number of retry attempts
        backoff_strategy: Function to calculate delay between retries
        exceptions: Tuple of exceptions to catch
        on_retry: Callback function called on each retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts - 1:
                        delay = backoff_strategy(attempt)
                        
                        structured_logger.log_error(
                            error_type="retry_attempt",
                            component=func.__name__,
                            message=f"Attempt {attempt + 1}/{max_attempts} failed, retrying in {delay}s",
                            exception=e
                        )
                        
                        if on_retry:
                            on_retry(attempt, e)
                        
                        await asyncio.sleep(delay)
                    else:
                        structured_logger.log_error(
                            error_type="retry_exhausted",
                            component=func.__name__,
                            message=f"All {max_attempts} attempts failed",
                            exception=e
                        )
            
            # All retries exhausted
            raise last_exception
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts - 1:
                        delay = backoff_strategy(attempt)
                        
                        if on_retry:
                            on_retry(attempt, e)
                        
                        time.sleep(delay)
            
            raise last_exception
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# ==================== IDEMPOTENCY ====================

class IdempotencyManager:
    """
    Manage idempotent operations to prevent duplicate processing
    Critical for job applications - don't apply twice!
    """
    
    @staticmethod
    def generate_key(operation: str, *args, **kwargs) -> str:
        """Generate idempotency key from operation and parameters"""
        # Create stable hash from arguments
        data = f"{operation}:{str(args)}:{str(sorted(kwargs.items()))}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    @staticmethod
    def check_processed(key: str) -> bool:
        """Check if operation was already processed"""
        cache_key = f"idempotency:{key}"
        return cache.exists(cache_key)
    
    @staticmethod
    def mark_processed(key: str, result: Any, ttl: int = 86400):
        """Mark operation as processed and store result"""
        cache_key = f"idempotency:{key}"
        cache.set(cache_key, {
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "result": result
        }, ttl=ttl)
    
    @staticmethod
    def get_result(key: str) -> Optional[Any]:
        """Get cached result if operation was already processed"""
        cache_key = f"idempotency:{key}"
        cached = cache.get(cache_key)
        if cached:
            return cached.get("result")
        return None


def idempotent(operation_name: str, ttl: int = 86400):
    """
    Decorator to make operations idempotent
    
    Args:
        operation_name: Name of the operation
        ttl: How long to remember this operation (seconds)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate idempotency key
            key = IdempotencyManager.generate_key(operation_name, *args, **kwargs)
            
            # Check if already processed
            if IdempotencyManager.check_processed(key):
                structured_logger.log_error(
                    error_type="idempotency_skip",
                    component=operation_name,
                    message=f"Operation {operation_name} already processed, returning cached result"
                )
                
                cached_result = IdempotencyManager.get_result(key)
                if cached_result is not None:
                    return cached_result
            
            # Process operation
            result = await func(*args, **kwargs)
            
            # Mark as processed
            IdempotencyManager.mark_processed(key, result, ttl)
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = IdempotencyManager.generate_key(operation_name, *args, **kwargs)
            
            if IdempotencyManager.check_processed(key):
                cached_result = IdempotencyManager.get_result(key)
                if cached_result is not None:
                    return cached_result
            
            result = func(*args, **kwargs)
            IdempotencyManager.mark_processed(key, result, ttl)
            
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# ==================== GRACEFUL DEGRADATION ====================

class FallbackHandler:
    """Handle graceful degradation when services fail"""
    
    @staticmethod
    def with_fallback(fallback_value: Any):
        """Decorator to provide fallback value on failure"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    structured_logger.log_error(
                        error_type="fallback_used",
                        component=func.__name__,
                        message=f"Function failed, using fallback value",
                        exception=e
                    )
                    return fallback_value
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    structured_logger.log_error(
                        error_type="fallback_used",
                        component=func.__name__,
                        message=f"Function failed, using fallback value",
                        exception=e
                    )
                    return fallback_value
            
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        
        return decorator


# ==================== TIMEOUT HANDLING ====================

def timeout(seconds: float):
    """Decorator to add timeout to async functions"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=seconds
                )
            except asyncio.TimeoutError:
                structured_logger.log_error(
                    error_type="timeout",
                    component=func.__name__,
                    message=f"Function timed out after {seconds}s"
                )
                raise TimeoutError(f"{func.__name__} timed out after {seconds}s")
        
        return wrapper
    return decorator


# ==================== RATE LIMITING WITH GRACEFUL DEGRADATION ====================

class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts limits based on system load
    """
    
    def __init__(self, base_limit: int, window: int):
        self.base_limit = base_limit
        self.window = window
        self.current_limit = base_limit
    
    def adjust_limit(self, load_factor: float):
        """
        Adjust rate limit based on system load
        
        Args:
            load_factor: 0.0-1.0, where 1.0 = full capacity
        """
        if load_factor > 0.9:
            # Reduce limit by 50% under heavy load
            self.current_limit = int(self.base_limit * 0.5)
        elif load_factor > 0.7:
            # Reduce limit by 25%
            self.current_limit = int(self.base_limit * 0.75)
        else:
            # Normal operation
            self.current_limit = self.base_limit
        
        structured_logger.log_error(
            error_type="rate_limit_adjusted",
            component="adaptive_rate_limiter",
            message=f"Rate limit adjusted to {self.current_limit} (load: {load_factor:.2f})"
        )


# ==================== BULKHEAD PATTERN ====================

class Bulkhead:
    """
    Bulkhead pattern to isolate resources
    Prevents one failing component from consuming all resources
    """
    
    def __init__(self, name: str, max_concurrent: int):
        self.name = name
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_count = 0
    
    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with self.semaphore:
                self.active_count += 1
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    self.active_count -= 1
        
        return wrapper


# ==================== EXAMPLES ====================

# Circuit breaker for external API calls
api_circuit_breaker = CircuitBreaker(
    name="external_api",
    failure_threshold=5,
    timeout=60
)

# Circuit breaker for database
db_circuit_breaker = CircuitBreaker(
    name="database",
    failure_threshold=3,
    timeout=30
)

# Bulkhead for job scraping (limit concurrent scrapers)
scraping_bulkhead = Bulkhead(
    name="job_scraping",
    max_concurrent=10
)

# Bulkhead for LLM requests (limit concurrent LLM calls)
llm_bulkhead = Bulkhead(
    name="llm_requests",
    max_concurrent=5
)
