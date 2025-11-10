"""
ELIS User Management System

A modular FastAPI application for user authentication and management with MongoDB.

This package provides:
- Authentication routes (register, login)
- User management endpoints
- MongoDB integration
- JWT token handling
- Password security with bcrypt

Usage:
    from app.main import app
    # or
    python -m app
"""

__version__ = "1.0.0"
__author__ = "ELIS Development Team"
__title__ = "ELIS User Management System"
__description__ = "FastAPI authentication system with MongoDB"

# Package exports for convenient imports
from app.main import app

__all__ = ["app"]
