import json
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    ENVIRONMENT: str = "development"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./speecheasy.db"
    SUPABASE_URL: Optional[str] = "https://fwrkrpmqmqxlgvyzrizq.supabase.co"
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ3cmtycG1xbXF4bGd2eXpyaXpxIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MDQ3MTQxOSwiZXhwIjoyMTA2MDQ3NDE5fQ.qCh5EDtm1EnWIlaBVkStFTF3_Wqqow1R5OjE924Re44"

    # SpeechEasy JWT Authentication
    # MUST match JWT_SECRET_KEY of patient_auth_service (the token issuer).
    JWT_SECRET_KEY: str = "speecheasy_patient_super_secret_production_key_498273948729384792384"
    JWT_ALGORITHM: str = "HS256"

    # AI Chatbot
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_FALLBACK_MODEL: str = "llama-3.1-8b-instant"
    CHAT_RATE_LIMIT: int = 20  # requests per minute per user
    CHAT_REQUEST_TIMEOUT: int = 30  # seconds

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"


settings = Settings()
