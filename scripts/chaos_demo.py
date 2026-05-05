import time
import requests
import subprocess
import sys

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
    try:
        res = requests.post(f"{BASE_URL}/api/auth/token", json={
            "username": USERNAME,
            "password": PASSWORD
        })
        res.raise_for_status()
        return res.json()["access_token"]
    except Exception as e:
        print(f"Failed to login: {e}")
        sys.exit(1)

def send_signal(token, component_id="db-server-01", component_type="rdbms"):
    payload = {
        "component_id": component_id,
        "component_type": component_type,
        "error_message": f"{component_type.upper()} failure detected",
        "severity": "P0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.post(f"{BASE_URL}/api/signals", json=payload, headers=headers)
        return res.status_code
    except Exception as e:
        print(f"Request failed: {e}")
        return 500

def main():
    print("=== Zeatop Advanced Chaos Engineering Demo ===")
    print("Scenario: RDBMS Outage -> Recovery -> MCP Failure")
    
    token = get_token()

    # 1. RDBMS OUTAGE
    print("\n--- PHASE 1: RDBMS OUTAGE ---")
    print("Injecting FAILURE: Stopping PostgreSQL...")
    run_command(["docker-compose", "pause", "postgres"])
    
    print("Sending signals to trigger Circuit Breaker...")
    for i in range(6):
        status = send_signal(token, component_id="pgsql-01", component_type="rdbms")
        print(f"   Signal {i+1} sent, status: {status}")
        time.sleep(1)
    
    print("Waiting for Circuit Breaker to trip...")
    time.sleep(5)
    
    # 2. RDBMS RECOVERY
    print("\n--- PHASE 2: RDBMS RECOVERY ---")
    print("Restoring PostgreSQL...")
    run_command(["docker-compose", "unpause", "postgres"])
    
    print("Sending signals to verify recovery...")
    for i in range(3):
        status = send_signal(token, component_id="pgsql-01", component_type="rdbms")
        print(f"   Post-recovery signal {i+1} sent, status: {status}")
        time.sleep(1)

    # 3. MCP FAILURE (Cascading/Sequential)
    print("\n--- PHASE 3: MCP FAILURE ---")
    print("Injecting FAILURE: Simulating Control Plane (MCP) outage...")
    # Note: In this architecture, MCP is a logical component handled by MCPAlertStrategy.
    # To simulate a failure, we send high-severity signals for an 'mcp' type component.
    # The system should handle this even if other parts are still recovering.
    
    for i in range(5):
        status = send_signal(token, component_id="mcp-core-cluster", component_type="mcp")
        print(f"   MCP Signal {i+1} sent, status: {status}")
        time.sleep(1)

    print("\n=== Advanced Chaos Demo Complete ===")
    print("Verification:")
    print("1. Check logs for 'Circuit breaker [postgresql] TRIPPED'")
    print("2. Check logs for 'P0 MCP page for mcp-core-cluster'")
    print("3. Check Dashboard for new active incidents for both PostgreSQL and MCP.")

if __name__ == "__main__":
    main()
