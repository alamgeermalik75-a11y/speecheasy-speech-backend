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

from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables in development mode if running SQLite / initial setup
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Speech Therapy Backend started in {settings.ENVIRONMENT} mode.")
    except Exception as e:
        logger.error(f"Non-critical startup table sync notice: {e}")

    # Pre-warm Supabase connection pool so initial requests don't pay TLS handshake penalty
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        try:
            from app.core.supabase import get_supabase
            sb = get_supabase()
            sb.table("daily_tips").select("id").limit(1).execute()
            logger.info("Supabase client connection pool pre-warmed successfully.")
        except Exception as e:
            logger.warning(f"Supabase pre-warm notice: {e}")

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
    default_response_class=ORJSONResponse,
    lifespan=lifespan
)

# 1. GZip Compression for responses > 1000 bytes
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 2. CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 3. Structured Request Logging Middleware
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    req_id = f"{time.time_ns() & 0xFFFFFFFF:08x}"
    start_time = time.perf_counter()
    
    # Process request
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

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
