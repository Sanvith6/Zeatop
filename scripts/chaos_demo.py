import time
import requests
import subprocess
import json
import os

# Configuration
BASE_URL = "http://localhost:8000"
USERNAME = "sre-intern"
PASSWORD = "zeotap-local"

def run_command(cmd):
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result.stdout

def get_token():
    print("Logging in...")
    res = requests.post(f"{BASE_URL}/api/auth/token", json={
        "username": USERNAME,
        "password": PASSWORD
    })
    res.raise_for_status()
    return res.json()["access_token"]

def send_signal(token, component_id="db-server-01"):
    payload = {
        "component_id": component_id,
        "component_type": "rdbms",
        "error_message": "Postgres connection timeout",
        "severity": "P0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.post(f"{BASE_URL}/api/signals", json=payload, headers=headers)
    return res.status_code

def main():
    print("=== Zetatop Chaos Engineering Demo ===")
    
    try:
        token = get_token()
    except Exception as e:
        print(f"Failed to login: {e}")
        return

    # 1. Show normal operation
    print("\n1. Sending 5 signals under normal conditions...")
    for _ in range(5):
        status = send_signal(token)
        print(f"   Signal sent, status: {status}")
    
    # 2. Inject Failure
    print("\n2. Injecting FAILURE: Stopping PostgreSQL...")
    run_command(["docker-compose", "pause", "postgres"])
    
    print("\n3. Sending signals while Postgres is DOWN (Proving Circuit Breaker)...")
    # Send enough signals to trip the circuit (threshold is 5)
    for i in range(7):
        status = send_signal(token)
        print(f"   Signal {i+1} sent, status: {status}")
        time.sleep(1)
    
    print("\n4. Checking if Circuit Breaker is TRIPPED...")
    print("   (Wait for worker logs to show 'Circuit breaker [postgresql] TRIPPED')")
    time.sleep(5)
    
    # 3. Restore Service
    print("\n5. Restoring Service: Starting PostgreSQL...")
    run_command(["docker-compose", "unpause", "postgres"])
    
    print("\n6. Sending signals post-recovery...")
    for i in range(5):
        status = send_signal(token)
        print(f"   Signal {i+1} sent, status: {status}")
        time.sleep(1)

    print("\n=== Chaos Demo Complete ===")
    print("Check backend/worker logs and Dashboard to see recovery and DLQ ingestion.")

if __name__ == "__main__":
    main()
