import pytest
import jwt
from datetime import datetime, timezone, timedelta
from app.config import settings


def make_access_token(uid: str, email: str = "user@example.com") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": uid,
        "email": email,
        "role": "patient",
        "token_type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_auth_missing_token(client):
    res = await client.get("/api/v1/profiles/me")
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized"

@pytest.mark.asyncio
async def test_auth_invalid_bearer_token(client):
    res = await client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": "Bearer invalid_token_xyz"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized"

@pytest.mark.asyncio
async def test_auth_jwt_from_auth_api_accepted(client):
    """A valid Auth-API-style access JWT authenticates the patient."""
    token = make_access_token("jwt_user_1", "jwt_user@example.com")
    res = await client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 = authenticated OK, profile simply doesn't exist yet
    assert res.status_code == 404
    assert res.json()["detail"] == "Profile not found"


@pytest.mark.asyncio
async def test_auth_refresh_token_rejected_as_access(client):
    """Refresh tokens must never authenticate API requests."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "jwt_user_2",
        "email": "refresh@example.com",
        "role": "patient",
        "token_type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=30)).timestamp()),
    }
    refresh_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    res = await client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_auth_x_patient_uid_mismatch_with_jwt_rejected(client):
    """JWT identity wins; a contradictory X-Patient-UID is a 403."""
    token = make_access_token("jwt_user_3")
    res = await client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": f"Bearer {token}", "X-Patient-UID": "attacker_uid"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_auth_dev_fallback_works_in_development(client):
    # In development mode, X-Patient-UID header is accepted
    res = await client.get(
        "/api/v1/profiles/me",
        headers={"X-Patient-UID": "dev_user_123"}
    )
    # 404 because profile doesn't exist yet, but passed 401 authentication
    assert res.status_code == 404
    assert res.json()["detail"] == "Profile not found"

@pytest.mark.asyncio
async def test_auth_dev_fallback_rejected_in_production(client):
    original_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        res = await client.get(
            "/api/v1/profiles/me",
            headers={"X-Patient-UID": "dev_user_123"}
        )
        # In production, X-Patient-UID MUST be rejected with 401
        assert res.status_code == 401
        assert res.json()["detail"] == "Unauthorized"
    finally:
        settings.ENVIRONMENT = original_env
