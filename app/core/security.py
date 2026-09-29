import logging
from typing import Optional

import jwt
from fastapi import Header, Depends
from pydantic import BaseModel

from app.config import settings
from app.core.exceptions import UnauthorizedException, ForbiddenException

logger = logging.getLogger(__name__)


class AuthenticatedUser(BaseModel):
    uid: str
    email: Optional[str] = None
    role: Optional[str] = None


def decode_speecheasy_access_token(token: str) -> dict:
    """
    Validate a SpeechEasy access JWT issued by the patient Auth API (:8001).

    The Auth API is the single source of truth for authentication:
      - HS256, shared JWT_SECRET_KEY
      - `sub`  -> public.users.id (canonical application user identity)
      - `token_type` must be "access" (refresh tokens are never accepted)
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Access token has expired")
    except jwt.InvalidTokenError:
        raise UnauthorizedException("Unauthorized")

    if payload.get("token_type") != "access":
        raise UnauthorizedException("Invalid token type")

    return payload


async def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_patient_uid: Optional[str] = Header(None, alias="X-Patient-UID"),
) -> AuthenticatedUser:
    """
    Resolve the current patient identity.

    Priority (spec section 3): JWT authenticated identity > X-Patient-UID.

    1. Authorization: Bearer <access_token> is mandatory in production.
    2. X-Patient-UID is ONLY a development fallback when no valid JWT is
       presented. If a JWT is present and the header mismatches it, the
       request is rejected (403).
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        if token:
            try:
                payload = decode_speecheasy_access_token(token)
                uid = payload.get("sub")
                if uid:
                    user = AuthenticatedUser(
                        uid=str(uid).strip(),
                        email=payload.get("email"),
                        role=payload.get("role", "patient"),
                    )
                    # Backward-compat header must never contradict the JWT.
                    if x_patient_uid and x_patient_uid.strip() and x_patient_uid.strip() != user.uid:
                        raise ForbiddenException(
                            "X-Patient-UID does not match the authenticated user"
                        )
                    return user
            except UnauthorizedException:
                # If access token has expired in development, allow falling back to X-Patient-UID
                if not (settings.is_development and x_patient_uid and x_patient_uid.strip()):
                    raise

    # Development-only fallback so legacy clients (which send only
    # X-Patient-UID) keep working until the Flutter app is updated.
    if settings.is_development and x_patient_uid and x_patient_uid.strip():
        return AuthenticatedUser(uid=x_patient_uid.strip(), role="patient")

    raise UnauthorizedException("Unauthorized")


async def get_current_patient_uid(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    """Convenience dependency returning the authenticated user's id (users.id)."""
    return current_user.uid


# Alias used across existing endpoints
get_current_user_uid = get_current_patient_uid
