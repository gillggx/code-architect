"""
Custom exception classes for Code Architect API

Provides structured error handling with proper HTTP status codes and response formats.

Version: 1.0
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException, status


class APIError(HTTPException):
    """Base API error class
    
    Attributes:
        status_code: HTTP status code
        detail: Error message
        error_code: Application-specific error code
        context: Additional context for debugging
    """
    
    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail: str = "Internal server error",
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize API error
        
        Args:
            status_code: HTTP status code (default 500)
            detail: Error message
            error_code: Application error code (e.g., "ANALYSIS_FAILED")
            context: Additional debugging context
        """
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code or "API_ERROR"
        self.context = context or {}


class ValidationError(APIError):
    """Validation error (400 Bad Request)
    
    Raised when request validation fails (invalid schema, missing fields, etc.)
    """
    
    def __init__(
        self,
        detail: str = "Validation error",
        field: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize validation error
        
        Args:
            detail: Error message
            field: Field that failed validation
            context: Additional context
        """
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="VALIDATION_ERROR",
            context={**(context or {}), "field": field},
        )


class AuthenticationError(APIError):
    """Authentication error (401 Unauthorized)
    
    Raised when authentication fails or is missing.
    """
    
    def __init__(
        self,
        detail: str = "Authentication required",
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize authentication error
        
        Args:
            detail: Error message
            context: Additional context
        """
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="AUTHENTICATION_ERROR",
            context=context,
        )


class RateLimitError(APIError):
    """Rate limit exceeded (429 Too Many Requests)
    
    Raised when rate limit is exceeded.
    """
    
    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize rate limit error
        
        Args:
            detail: Error message
            retry_after: Seconds to wait before retry
            context: Additional context
        """
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            error_code="RATE_LIMIT_EXCEEDED",
            context={**(context or {}), "retry_after": retry_after},
        )
        self.retry_after = retry_after


class NotFoundError(APIError):
    """Resource not found (404)
    
    Raised when requested resource doesn't exist.
    """
    
    def __init__(
        self,
        detail: str = "Resource not found",
        resource_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize not found error
        
        Args:
            detail: Error message
            resource_type: Type of resource (e.g., "project")
            context: Additional context
        """
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            error_code="NOT_FOUND",
            context={**(context or {}), "resource_type": resource_type},
        )


class AnalysisError(APIError):
    """Analysis failed error (422 Unprocessable Entity)
    
    Raised when project analysis fails.
    """
    
    def __init__(
        self,
        detail: str = "Analysis failed",
        reason: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize analysis error
        
        Args:
            detail: Error message
            reason: Reason for failure
            context: Additional context
        """
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            error_code="ANALYSIS_ERROR",
            context={**(context or {}), "reason": reason},
        )


class TimeoutError(AnalysisError):
    """Analysis timeout error
    
    Raised when analysis exceeds time limit.
    """
    
    def __init__(
        self,
        detail: str = "Analysis timeout",
        timeout_seconds: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize timeout error
        
        Args:
            detail: Error message
            timeout_seconds: Timeout value
            context: Additional context
        """
        super().__init__(
            detail=detail,
            reason="timeout",
            context={**(context or {}), "timeout_seconds": timeout_seconds},
        )


class InternalError(APIError):
    """Internal server error (500)
    
    Raised for unexpected internal errors.
    """
    
    def __init__(
        self,
        detail: str = "Internal server error",
        exception: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize internal error
        
        Args:
            detail: Error message
            exception: Original exception
            context: Additional context
        """
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code="INTERNAL_ERROR",
            context={
                **(context or {}),
                "exception": str(exception) if exception else None,
            },
        )
