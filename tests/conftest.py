import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.therapist import Therapist, Availability
from app.models.daily_tip import DailyTip
from datetime import time

# In-memory SQLite database for fast, isolated test runs
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Ensure tests run against local SQLite database without external Supabase calls
settings.SUPABASE_SERVICE_ROLE_KEY = ""

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

TestAsyncSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSessionLocal() as session:
        # Seed basic doctor and tips for tests
        doctor = Therapist(
            id="doc-1234-uuid",
            full_name="Dr. Sarah Tariq",
            qualification="M.Sc. SLP",
            years_of_experience=5,
            languages_spoken="Urdu, English",
            rating=5.0,
            consultation_fee=2500.0,
            doctor_code="SPK-1234",
            status="approved"
        )
        session.add(doctor)
        await session.flush()

        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            avail = Availability(
                doctor_id=doctor.id,
                day=day,
                start_time=time(9, 0),
                end_time=time(17, 0),
                is_active=True
            )
            session.add(avail)

        tip = DailyTip(
            tip_text="Practice slowly and clearly.",
            sort_order=1,
            is_active=True
        )
        session.add(tip)

        await session.commit()
        yield session

@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
