"""
ELIS User Management System
FastAPI application with MongoDB authentication
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, users
from app.db.mongodb import db_connection

# Create FastAPI app
app = FastAPI(
    title="ELIS User Management System",
    description="User authentication and management with MongoDB",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware -- During production, restrict origins appropriately
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(users.router)


# ============================================================================
# LIFECYCLE EVENTS
# ============================================================================
@app.on_event("startup")
async def startup_event():
    """Initialize database connection on startup"""
    try:
        db_connection.connect()
    except Exception as e:
        print(f"Failed to connect to MongoDB: {str(e)}")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown"""
    db_connection.disconnect()


# ============================================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================================
@app.get("/", tags=["General"])
async def root() -> dict:
    """
    Root endpoint - API information
    
    Provides information about available endpoints and API version
    """
    return {
        "message": "Welcome to ELIS User Management System",
        "version": "1.0.0",
        "documentation": {
            "swagger": "/docs",
            "redoc": "/redoc"
        },
        "endpoints": {
            "register": "POST /auth/register",
            "login": "POST /auth/login",
            "profile": "GET /users/me",
            "health": "GET /health"
        }
    }


@app.get("/health", tags=["General"])
async def health_check() -> dict:
    """
    Health check endpoint
    
    Verifies MongoDB connection and API status
    """
    try:
        db = db_connection.get_database()
        db.client.admin.command('ping')
        
        return {
            "status": "healthy",
            "database": "connected",
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "version": "1.0.0"
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
