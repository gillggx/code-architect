"""
Authentication and rate limiting for Code Architect API

Provides API key authentication, rate limiting, and request throttling.

Version: 1.0
"""

import time
import hashlib
import hmac
from typing import Optional, Dict, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, status
from .errors import AuthenticationError, RateLimitError


class APIKeyManager:
    """Manages API key validation and tracking
    
    Simple in-memory API key management for development.
    Production should use database-backed solution.
    """
    
    def __init__(self, default_key: str = "test-key-12345"):
        """Initialize API key manager
        
        Args:
            default_key: Default API key for development
        """
        self.valid_keys: Dict[str, str] = {
            default_key: "default",  # key: description
        }
        self.key_usage: Dict[str, int] = defaultdict(int)
    
    def add_key(self, api_key: str, description: str) -> None:
        """Add new API key
        
        Args:
            api_key: API key to add
            description: Key description/purpose
        """
        self.valid_keys[api_key] = description
    
    def validate_key(self, api_key: Optional[str]) -> Tuple[bool, str]:
        """Validate API key
        
        Args:
            api_key: API key to validate
        
        Returns:
            Tuple[is_valid, description]
        """
        if not api_key:
            return False, "Missing API key"
        
        if api_key not in self.valid_keys:
            return False, "Invalid API key"
        
        return True, self.valid_keys[api_key]
    
    def record_usage(self, api_key: str) -> None:
        """Record API key usage
        
        Args:
            api_key: API key that was used
        """
        self.key_usage[api_key] += 1


class RateLimiter:
    """Rate limiter using sliding window algorithm
    
    Tracks request counts per client/key and enforces rate limits.
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
    ):
        """Initialize rate limiter
        
        Args:
            requests_per_minute: Max requests per minute
            requests_per_hour: Max requests per hour
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # Track requests: key -> list of timestamps
        self.request_history: Dict[str, list] = defaultdict(list)
    
    def _cleanup_old_requests(self, key: str) -> None:
        """Remove requests outside rate limit windows
        
        Args:
            key: Client/API key
        """
        now = time.time()
        
        # Keep only requests from last hour
        cutoff = now - 3600
        if key in self.request_history:
            self.request_history[key] = [
                ts for ts in self.request_history[key]
                if ts > cutoff
            ]
    
    def is_allowed(self, key: str) -> Tuple[bool, Optional[int]]:
        """Check if request is allowed for key
        
        Args:
            key: Client/API key
        
        Returns:
            Tuple[is_allowed, retry_after_seconds]
        """
        self._cleanup_old_requests(key)
        now = time.time()
        
        # Check per-minute limit
        minute_ago = now - 60
        recent_requests = [
            ts for ts in self.request_history[key]
            if ts > minute_ago
        ]
        
        if len(recent_requests) >= self.requests_per_minute:
            retry_after = int(
                recent_requests[0] + 60 - now
            ) + 1
            return False, retry_after
        
        # Check per-hour limit
        hour_ago = now - 3600
        hourly_requests = [
            ts for ts in self.request_history[key]
            if ts > hour_ago
        ]
        
        if len(hourly_requests) >= self.requests_per_hour:
            retry_after = int(
                hourly_requests[0] + 3600 - now
            ) + 1
            return False, retry_after
        
        # Record this request
        self.request_history[key].append(now)
        return True, None
    
    def get_stats(self, key: str) -> Dict[str, int]:
        """Get rate limit stats for key
        
        Args:
            key: Client/API key
        
        Returns:
            Stats dict with request counts
        """
        self._cleanup_old_requests(key)
        now = time.time()
        
        minute_ago = now - 60
        hour_ago = now - 3600
        
        recent_minute = len([
            ts for ts in self.request_history[key]
            if ts > minute_ago
        ])
        recent_hour = len([
            ts for ts in self.request_history[key]
            if ts > hour_ago
        ])
        
        return {
            "requests_last_minute": recent_minute,
            "requests_per_minute_limit": self.requests_per_minute,
            "requests_last_hour": recent_hour,
            "requests_per_hour_limit": self.requests_per_hour,
        }


class AuthMiddleware:
    """Middleware for API authentication and rate limiting
    
    Extracts and validates API key from headers, enforces rate limits.
    """
    
    def __init__(
        self,
        api_key_manager: APIKeyManager,
        rate_limiter: RateLimiter,
        require_auth: bool = False,
    ):
        """Initialize auth middleware
        
        Args:
            api_key_manager: API key manager instance
            rate_limiter: Rate limiter instance
            require_auth: Whether auth is required (can be disabled for testing)
        """
        self.api_key_manager = api_key_manager
        self.rate_limiter = rate_limiter
        self.require_auth = require_auth
    
    async def __call__(self, request: Request) -> Tuple[str, str]:
        """Process request authentication
        
        Args:
            request: FastAPI request
        
        Returns:
            Tuple[api_key, key_description]
        
        Raises:
            AuthenticationError: If auth fails
            RateLimitError: If rate limit exceeded
        """
        # Extract API key from header
        api_key = request.headers.get("X-API-Key")
        
        # Check if auth is required
        if self.require_auth and not api_key:
            raise AuthenticationError("X-API-Key header required")
        
        # If no key but auth not required, use default
        if not api_key:
            api_key = "anonymous"
        
        # Validate API key (if auth required)
        if self.require_auth:
            is_valid, description = self.api_key_manager.validate_key(api_key)
            if not is_valid:
                raise AuthenticationError(description)
        else:
            # Even if not required, track valid keys
            is_valid, description = self.api_key_manager.validate_key(api_key)
            if is_valid:
                self.api_key_manager.record_usage(api_key)
        
        # Check rate limit
        is_allowed, retry_after = self.rate_limiter.is_allowed(api_key)
        if not is_allowed:
            raise RateLimitError(
                f"Rate limit exceeded. Retry after {retry_after} seconds.",
                retry_after=retry_after,
            )
        
        return api_key, description


# Global singleton instances
_api_key_manager: Optional[APIKeyManager] = None
_rate_limiter: Optional[RateLimiter] = None
_auth_middleware: Optional[AuthMiddleware] = None


def init_auth(
    default_key: str = "test-key-12345",
    requests_per_minute: int = 60,
    requests_per_hour: int = 1000,
    require_auth: bool = False,
) -> Tuple[APIKeyManager, RateLimiter, AuthMiddleware]:
    """Initialize authentication system
    
    Args:
        default_key: Default API key
        requests_per_minute: Rate limit per minute
        requests_per_hour: Rate limit per hour
        require_auth: Whether to require authentication
    
    Returns:
        Tuple[api_key_manager, rate_limiter, middleware]
    """
    global _api_key_manager, _rate_limiter, _auth_middleware
    
    _api_key_manager = APIKeyManager(default_key=default_key)
    _rate_limiter = RateLimiter(
        requests_per_minute=requests_per_minute,
        requests_per_hour=requests_per_hour,
    )
    _auth_middleware = AuthMiddleware(
        _api_key_manager,
        _rate_limiter,
        require_auth=require_auth,
    )
    
    return _api_key_manager, _rate_limiter, _auth_middleware


def get_auth_middleware() -> AuthMiddleware:
    """Get global auth middleware instance
    
    Returns:
        AuthMiddleware instance
    """
    global _auth_middleware
    if _auth_middleware is None:
        init_auth()
    return _auth_middleware


def get_api_key_manager() -> APIKeyManager:
    """Get global API key manager
    
    Returns:
        APIKeyManager instance
    """
    global _api_key_manager
    if _api_key_manager is None:
        init_auth()
    return _api_key_manager


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter
    
    Returns:
        RateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        init_auth()
    return _rate_limiter
