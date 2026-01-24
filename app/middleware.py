"""
Security middleware for the ytdlp-microservice.

This module provides middleware for adding security headers to all responses.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all HTTP responses.

    This middleware adds the following security headers:
    - X-Content-Type-Options: nosniff - Prevents MIME type sniffing
    - X-Frame-Options: DENY - Prevents clickjacking attacks
    - Content-Security-Policy: default-src 'self' - Restricts resource sources
    - Strict-Transport-Security (HTTPS only) - Enforces HTTPS connections

    The middleware checks the request scheme and only adds HSTS header
    when the request is made over HTTPS to avoid browser warnings.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process the request and add security headers to the response.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or route handler in the chain

        Returns:
            Response with security headers added
        """
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking - deny all framing
        response.headers["X-Frame-Options"] = "DENY"

        # Content Security Policy - allow scripts for Swagger UI paths
        if request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' https://fastapi.tiangolo.com; "
                "connect-src 'self' https://cdn.jsdelivr.net"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'"

        # HSTS only if using HTTPS (avoid browser warnings on HTTP)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
