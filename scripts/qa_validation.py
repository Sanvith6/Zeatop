import requests
import time
import uuid
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"

def get_now():
    return datetime.now(timezone.utc).isoformat()

def test_auth():
    print("Testing Auth...")
    res = requests.post(f"{BASE_URL}/api/auth/token", json={"username": "sre-intern", "password": "zeotap-local"})
    res.raise_for_status()
    token = res.json()["access_token"]
    print("[OK] Auth OK")
    return {"Authorization": f"Bearer {token}"}

def test_ingestion(headers):
    print("Testing Ingestion...")
    payload = {
        "component_id": f"qa-test-{uuid.uuid4().hex[:6]}",
        "component_type": "api",
        "error_message": "QA Validation Signal",
        "severity": "P0",
        "timestamp": get_now()
    }
    res = requests.post(f"{BASE_URL}/api/signals", json=payload, headers=headers)
    assert res.status_code == 202
    print("[OK] Ingestion OK (202 Accepted)")
    return payload["component_id"]

def test_incidents(headers):
    print("Testing Incidents List...")
    res = requests.get(f"{BASE_URL}/api/workitems", headers=headers)
    assert res.status_code == 200
    print(f"[OK] Incidents List OK (Found {len(res.json())} items)")

def test_debounce_logic(headers):
    print("Testing Debounce Logic (105 signals with CURRENT timestamp)...")
    comp_id = f"debounce-test-{uuid.uuid4().hex[:6]}"
    now = get_now()
    for i in range(105):
        requests.post(f"{BASE_URL}/api/signals", json={
            "component_id": comp_id,
            "component_type": "db",
            "error_message": f"Noise signal {i}",
            "severity": "P1",
            "timestamp": now
        }, headers=headers)
    
    print("Waiting 15s for worker to process and flush...")
    time.sleep(15)
    
    res = requests.get(f"{BASE_URL}/api/workitems", headers=headers)
    items = [i for i in res.json() if i["component_id"] == comp_id]
    
    assert len(items) == 1, f"Expected 1 incident for {comp_id}, found {len(items)}. Check worker logs if 0."
    assert items[0]["signal_count"] >= 100
    print(f"[OK] Debounce OK (Created 1 incident for 100+ signals, count={items[0]['signal_count']})")
    return items[0]["id"]

def test_state_machine_and_rca(headers, incident_id):
    print(f"Testing State Machine & RCA for {incident_id}...")
    
    # 1. Try to CLOSE immediately (should fail - invalid transition)
    res = requests.patch(f"{BASE_URL}/api/workitems/{incident_id}/status", json={"status": "CLOSED"}, headers=headers)
    assert res.status_code == 400
    print("[OK] Transition OPEN -> CLOSED blocked (Correct)")
    
    # 2. Move to INVESTIGATING
    res = requests.patch(f"{BASE_URL}/api/workitems/{incident_id}/status", json={"status": "INVESTIGATING"}, headers=headers)
    assert res.status_code == 200
    
    # 3. Move to RESOLVED
    res = requests.patch(f"{BASE_URL}/api/workitems/{incident_id}/status", json={"status": "RESOLVED"}, headers=headers)
    assert res.status_code == 200
    
    # 4. Try to CLOSE without RCA (should fail)
    res = requests.patch(f"{BASE_URL}/api/workitems/{incident_id}/status", json={"status": "CLOSED"}, headers=headers)
    assert res.status_code == 400
    print("[OK] Close without RCA blocked (Correct)")
    
    # 5. Add RCA
    rca_payload = {
        "incident_start": get_now(),
        "incident_end": get_now(),
        "root_cause_category": "Infrastructure",
        "fix_applied": "Manual restart",
        "prevention_steps": "Better monitoring"
    }
    res = requests.post(f"{BASE_URL}/api/workitems/{incident_id}/rca", json=rca_payload, headers=headers)
    assert res.status_code == 200
    print("[OK] RCA Added successfully")
    
    # 6. Close again (should succeed)
    res = requests.patch(f"{BASE_URL}/api/workitems/{incident_id}/status", json={"status": "CLOSED"}, headers=headers)
    assert res.status_code == 200
    print("[OK] Transition RESOLVED -> CLOSED with RCA successful")

if __name__ == "__main__":
    try:
        h = test_auth()
        test_ingestion(h)
        test_incidents(h)
        inc_id = test_debounce_logic(h)
        test_state_machine_and_rca(h, inc_id)
        print("\n[SUCCESS] QA PASSED: Core functional flows are 100% correct.")
    except Exception as e:
        print(f"\n[FAILED] QA FAILED: {e}")
        exit(1)
