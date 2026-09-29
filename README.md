# Speech Therapy Core Backend (FastAPI + PostgreSQL + Firebase)

Production-grade, asynchronous FastAPI backend powering user profiles, sound progression, clinical booking, notifications, and AI therapy assistance for the **Speech Therapy Mobile App (`voice-testing-fyp`)**.

---

## 1. System Scope & Boundaries

### Excluded Services (Running Live Elsewhere)
As required by the architecture, the following services are **NOT** part of this backend:
- **Urdu Content API (`fast-api-chron.onrender.com`)**: Alphabets, words, sentences, poems, stories, fill-in-the-blanks, and content search.
- **Audio Transcription API (`fastapi-backend-speech.onrender.com`)**: Whisper speech-to-text audio proxy.

### Modules Managed By This Backend
1. **Profiles & Focus Sound**: Child and parent registration, sound tracking, account deletion.
2. **Daily Tips**: Rotation of pediatric speech therapy guidance for parents.
3. **Doctor Ratings**: 1–5 star reviews with average rating aggregation.
4. **Therapists & Clinic Code**: Verified therapists directory and `SPK-xxxx` code lookup.
5. **Doctor Requests**: Registration link between patients and speech therapists.
6. **30-Minute Slot Availability & Booking**: Conflict-free session booking with concurrency locking.
7. **Practice Attempts & Progress**: Unique-item mastery scoring and auto-advancement of focus sound.
8. **In-App Notifications**: Milestone trophies (`🏆`), sound celebrations (`🎉`), and booking alerts (`📅`).
9. **Pediatric Speech AI Chatbot**: Rate-limited, safe LLM guidance powered by Groq.
10. **Liveness & Readiness Health Probes**: `/health` and `/health/ready`.

---

## 2. Product Decisions & Business Rules (Section 59 Clarifications)

To ensure consistency and avoid silent assumptions, the following product rules are explicitly implemented and isolated:

### Rule A: Doctor Rating Eligibility
- **Implementation**: Located in `app/services/rating_service.py` (`submit_rating`).
- **Rule**: Patient must have a completed profile and rate an approved doctor. A strict interaction check (`require_prior_interaction=True`) can be toggled to mandate that a patient has an appointment or registration link before rating.
- **Guaranteed Constraint**: Database `UNIQUE(doctor_id, patient_uid)` ensures a patient can only have one current rating per doctor; re-submitting updates their existing score and recalculates the doctor's average.

### Rule B: Authentic Sound Mastery Formula
- **Implementation**: Located in `app/services/progress_service.py` (`ProgressService`).
- **Rule**: A sound's completion percentage is determined by **passed unique items** ($\ge 70\%$) across all practice levels (`words`, `sentences`, `fillBlanks`, `poems`, `story`).
- **Anti-Cheat Protection**: Users **cannot** reach 100% simply by repeatedly submitting the same item over and over.

### Rule C: Deterministic Urdu Alphabet Sequence
- **Implementation**: Located in `app/services/progress_service.py` (`URDU_ALPHABET_SEQUENCE`).
- **Rule**: Fixed curriculum order (Alif, Bay, Pay, Tay, Ttay, Say, Jeem, Chay, ...). When authentic mastery reaches 100%, the backend automatically advances the child's `focus_sound` to the next letter in this sequence and issues a celebration notification.

### Rule D: Account Deletion Cascading
- **Implementation**: Located in `app/models/` and `app/services/profile_service.py`.
- **Rule**: When `DELETE /api/v1/profiles/me` is executed, foreign keys configured with `ON DELETE CASCADE` cleanly delete the user's `focus_sound`, `attempts`, `notifications`, `ratings`, `patient_requests`, and `appointments` to guarantee zero orphaned records.

### Rule E: Patient-Doctor Appointment Booking
- **Implementation**: Located in `app/services/booking_service.py`.
- **Rule**: Any registered patient with a completed child profile can book available 30-minute slots with an approved doctor. Bookings check active availability and enforce transactional locking against double-booking.

---

## 3. Security & Non-Negotiable Rules

1. **Authoritative Patient Identity**:
   - The Firebase decoded token `uid` (or `sub`) is the **only** source of patient identity.
   - The client can **never** submit or override `patient_uid`.
2. **Development Fallback Safeguard**:
   - `X-Patient-UID` is strictly permitted **only** when `ENVIRONMENT=development`.
   - In `ENVIRONMENT=production`, `X-Patient-UID` is unconditionally rejected with `401 Unauthorized`.
3. **Cross-User Data Isolation**:
   - All queries (`attempts`, `notifications`, `profile`, `my-status`) are scoped strictly to `WHERE patient_uid = current_user_uid`.

---

## 4. Setup & Running Locally

### Prerequisites
- Python 3.11+
- Virtualenv

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 3. Run Database Migrations & Seed
```bash
alembic upgrade head
python seed.py
```

### 4. Start Development Server
```bash
uvicorn app.main:app --reload --port 8000
```
- Swagger API Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`
- Readiness Check: `http://localhost:8000/health/ready`

---

## 5. Running the Automated Test Suite

Run pytest with async support:
```bash
pytest
```
Tests cover:
- Authentication & production fallback rejection
- Profile creation, read, update progress preservation, and delete cascade
- Daily tips query
- Doctor ratings bounds and average calculation
- Therapist code search (`SPK-1234`), registration request, and conflict rejection
- 30-minute slot generation, booking, notification, and double-booking collision prevention
- Attempt score validation, milestone alert, authentic mastery calculation, and alphabet progression
- Notification isolation, unread count, mark-read, and deletion
- AI Chatbot validation, sliding-window rate limiting, and safe error handling
- Liveness and readiness health checks

---

## 6. Production Deployment (Docker, Render, or Railway)

Build and run via Docker:
```bash
docker build -t speecheasy-backend .
docker run -p 8000:8000 --env-file .env speecheasy-backend
```
