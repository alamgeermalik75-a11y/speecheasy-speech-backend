import time
import uuid
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from app.config import settings
from app.core.database import engine, Base
from app.core.exceptions import (
    app_http_exception_handler,
    validation_exception_handler,
    global_exception_handler
)
from app.api.v1.router import api_router

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("speech_backend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables in development mode if running SQLite / initial setup
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Speech Therapy Backend started in {settings.ENVIRONMENT} mode.")
    except Exception as e:
        logger.error(f"Non-critical startup table sync notice: {e}")
    yield
    try:
        await engine.dispose()
        logger.info("Database connection closed.")
    except Exception as e:
        logger.error(f"Database shutdown notice: {e}")

app = FastAPI(
    title="Speech Therapy & Articulation Core Backend",
    description="Dedicated FastAPI backend for User, Therapist, Progress, and Chatbot services.",
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan
)

# 1. CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 2. Structured Request Logging Middleware
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    # Process request
    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)

    logger.info(
        f"[{req_id}] {request.method} {request.url.path} - "
        f"Status: {response.status_code} ({duration_ms}ms)"
    )
    response.headers["X-Request-ID"] = req_id
    return response

# 3. Global Exception Handlers
app.add_exception_handler(HTTPException, app_http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# 4. Public Health Endpoints
@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
@app.get("/health/live", tags=["Health"])
async def liveness_health_check():
    """Liveness check probe."""
    return {
        "service": "Speech Therapy & Articulation Core Backend",
        "version": "1.0.0",
        "status": "ok"
    }

@app.get("/health/ready", tags=["Health"])
async def readiness_health_check():
    """Readiness check probe validating database connectivity."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is currently unavailable"
        )

# 5. Include API v1 Router
app.include_router(api_router)

@app.post("/api/v1/auth/logout", tags=["Auth"])
async def speech_backend_logout():
    """Universal logout handler for speech backend."""
    return {"message": "Successfully logged out.", "success": True}
