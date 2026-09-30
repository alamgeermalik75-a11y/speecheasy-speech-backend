import urllib.request
import urllib.error
import json

import os

BASE_URL = os.environ.get("BASE_URL", "https://speecheasy-speech-backend-production.up.railway.app")
DEV_UID = "test-patient-smoke-123"

def request(name, path, method="GET", body=None, headers=None):
    url = f"{BASE_URL}{path}"
    h = headers or {}
    h["Content-Type"] = "application/json"
    h["X-Patient-UID"] = DEV_UID
    data = json.dumps(body).encode("utf-8") if body else None
    
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            parsed = json.loads(content) if content else {}
            print(f"[PASS] {name} (HTTP {resp.status})")
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        print(f"[FAIL] {name} (HTTP {e.code}): {content}")
        return e.code, content
    except Exception as ex:
        print(f"[ERROR] {name}: {ex}")
        return None, str(ex)

def run():
    print("=" * 60)
    print("RUNNING LIVE END-TO-END VERIFICATION")
    print("=" * 60)
    
    # 1. Health
    request("Health Liveness", "/health")
    request("Health Live Alias", "/health/live")
    request("Health Readiness", "/health/ready")

    # 2. Daily Tips
    request("Daily Tips", "/api/v1/daily-tips")

    # 3. Therapists
    st, therapists = request("Therapists List", "/api/v1/therapists")
    if therapists and len(therapists) > 0:
        first_code = therapists[0]["doctor_code"]
        request(f"Therapist by Code ({first_code})", f"/api/v1/therapists/by-code/{first_code}")
    
    # 4. Profile Lifecycle
    profile_payload = {
        "parent_name": "Test Parent",
        "child_name": "Test Kid",
        "sound": "ا",
        "alphabet_name": "alif"
    }
    request("Upsert Profile", "/api/v1/profiles", method="POST", body=profile_payload)
    request("Fetch My Profile", "/api/v1/profiles/me")

    # 5. Practice Attempt Lifecycle
    attempt_payload = {
        "item_id": "smoke_alif_w_1",
        "alphabet_name": "alif",
        "level_key": "words",
        "score": 85
    }
    request("Record Attempt", "/api/v1/attempts", method="POST", body=attempt_payload)
    request("Practice History", "/api/v1/attempts/history?alphabet_name=alif")

    # 6. Notifications
    request("List Notifications", "/api/v1/notifications")
    request("Unread Notifications Count", "/api/v1/notifications/unread-count")

    # 7. Therapist Status
    request("My Therapist Status", "/api/v1/therapists/my-status")

    # 8. AI Chatbot
    chat_payload = {
        "message": "Hello, how can I help my child pronounce the letter alif?"
    }
    request("AI Speech Therapist Chat", "/api/v1/chat", method="POST", body=chat_payload)

    print("=" * 60)
    print("ALL TEST SCENARIOS COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    run()
