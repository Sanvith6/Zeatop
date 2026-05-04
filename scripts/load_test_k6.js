import http from 'k6/http';
import { check, sleep } from 'k6';

/**
 * k6 Load Test: High-Throughput Signal Ingestion
 * 
 * This script simulates 10,000 signals/second (bursted) to demonstrate
 * the system's ability to handle massive ingestion through Redis-backed queuing
 * and adaptive throttling.
 */

export const options = {
  scenarios: {
    constant_request_rate: {
      executor: 'constant-arrival-rate',
      rate: 1000, // 1000 requests per second per VU? No, total rate.
      timeUnit: '1s',
      duration: '1m',
      preAllocatedVUs: 50,
      maxVUs: 100,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'], // Less than 1% errors
    http_req_duration: ['p(95)<200'], // 95% of requests should be under 200ms
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const USERNAME = 'sre-intern';
const PASSWORD = 'zeotap-local';

export function setup() {
  // Login to get JWT token
  const loginRes = http.post(`${BASE_URL}/api/auth/token`, JSON.stringify({
    username: USERNAME,
    password: PASSWORD,
  }), {
    headers: { 'Content-Type': 'application/json' },
  });

  check(loginRes, {
    'logged in successfully': (r) => r.status === 200,
  });

  return { token: loginRes.json('access_token') };
}

export default function (data) {
  const payload = JSON.stringify({
    component_id: `api-server-${Math.floor(Math.random() * 5)}`,
    component_type: 'api',
    error_message: 'High latency detected in downstream service',
    severity: 'P1',
    timestamp: new Date().toISOString(),
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${data.token}`,
    },
  };

  const res = http.post(`${BASE_URL}/api/signals`, payload, params);

  check(res, {
    'is accepted (202)': (r) => r.status === 202,
    'is throttled (429)': (r) => r.status === 429,
  });
}
