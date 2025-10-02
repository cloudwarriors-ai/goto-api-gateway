#!/usr/bin/env python3
"""
Test suite for session-based authentication functionality.

Usage:
    python tools/test_sessions.py
    python tools/test_sessions.py --skip-ttl
    python tools/test_sessions.py --cleanup
    
Prerequisites:
    - Redis seeded with test data (run tools/seed_redis.py first)
    - API server running on localhost:8078
"""

import requests
import time
import json
import sys
import argparse

BASE_URL = "http://localhost:8078"
DEFAULT_TENANT = "cloudwarriors"
DEFAULT_APP = "goto"


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'


def print_test(name):
    print(f"\n{Colors.BLUE}▶ Testing: {name}{Colors.END}")


def print_pass(message):
    print(f"  {Colors.GREEN}✓ {message}{Colors.END}")


def print_fail(message):
    print(f"  {Colors.RED}✗ {message}{Colors.END}")


def print_info(message):
    print(f"  {Colors.YELLOW}ℹ {message}{Colors.END}")


class SessionTester:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.session_id = None
        self.passed = 0
        self.failed = 0
    
    def test_health(self):
        print_test("API Health Check")
        try:
            resp = requests.get(f"{self.base_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                print_pass(f"API is healthy")
                print_info(f"Redis: {'✓' if data.get('redis_healthy') else '✗'}")
                self.passed += 1
                return True
            else:
                print_fail(f"Health check failed: {resp.status_code}")
                self.failed += 1
                return False
        except Exception as e:
            print_fail(f"Health check error: {e}")
            self.failed += 1
            return False
    
    def test_connect(self):
        print_test("Session Creation (POST /auth/connect)")
        try:
            payload = {"tenant": DEFAULT_TENANT, "app": DEFAULT_APP}
            resp = requests.post(
                f"{self.base_url}/auth/connect",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.session_id = data.get('data', {}).get('session_id')
                
                print_pass("Session created successfully")
                print_info(f"Session ID: {self.session_id}")
                print_info(f"Expires in: {data.get('data', {}).get('expires_in')}s")
                
                self.passed += 1
                return True
            else:
                print_fail(f"Connect failed: {resp.status_code}")
                print_info(f"Response: {resp.text}")
                self.failed += 1
                return False
                
        except Exception as e:
            print_fail(f"Connect error: {e}")
            self.failed += 1
            return False
    
    def test_status_with_session(self):
        print_test("Session Validation (GET /auth/status with session_id)")
        
        if not self.session_id:
            print_fail("No session_id available")
            self.failed += 1
            return False
        
        try:
            resp = requests.get(
                f"{self.base_url}/auth/status",
                params={"session_id": self.session_id}
            )
            
            if resp.status_code == 200:
                data = resp.json()
                
                print_pass("Session validated successfully")
                print_info(f"Tenant: {data.get('data', {}).get('tenant')}")
                print_info(f"App: {data.get('data', {}).get('app')}")
                
                self.passed += 1
                return True
            else:
                print_fail(f"Status check failed: {resp.status_code}")
                self.failed += 1
                return False
                
        except Exception as e:
            print_fail(f"Status check error: {e}")
            self.failed += 1
            return False
    
    def test_status_without_session(self):
        print_test("Legacy Status Check (GET /auth/status)")
        try:
            resp = requests.get(f"{self.base_url}/auth/status")
            
            if resp.status_code == 200:
                print_pass("Legacy status check works")
                self.passed += 1
                return True
            else:
                print_fail(f"Status check failed: {resp.status_code}")
                self.failed += 1
                return False
                
        except Exception as e:
            print_fail(f"Status check error: {e}")
            self.failed += 1
            return False
    
    def test_invalid_session(self):
        print_test("Invalid Session Validation")
        try:
            fake_session = "00000000-0000-0000-0000-000000000000"
            resp = requests.get(
                f"{self.base_url}/auth/status",
                params={"session_id": fake_session}
            )
            
            if resp.status_code == 401:
                print_pass("Invalid session correctly rejected (401)")
                self.passed += 1
                return True
            else:
                print_fail(f"Expected 401, got {resp.status_code}")
                self.failed += 1
                return False
                
        except Exception as e:
            print_fail(f"Invalid session test error: {e}")
            self.failed += 1
            return False
    
    def test_disconnect(self):
        print_test("Session Deletion (POST /auth/disconnect)")
        
        if not self.session_id:
            print_fail("No session_id available")
            self.failed += 1
            return False
        
        try:
            resp = requests.post(
                f"{self.base_url}/auth/disconnect",
                params={"session_id": self.session_id}
            )
            
            if resp.status_code == 200:
                print_pass("Session disconnected successfully")
                
                verify_resp = requests.get(
                    f"{self.base_url}/auth/status",
                    params={"session_id": self.session_id}
                )
                
                if verify_resp.status_code == 401:
                    print_pass("Session confirmed deleted")
                    self.passed += 1
                    return True
                else:
                    print_fail(f"Session still exists")
                    self.failed += 1
                    return False
            else:
                print_fail(f"Disconnect failed: {resp.status_code}")
                self.failed += 1
                return False
                
        except Exception as e:
            print_fail(f"Disconnect error: {e}")
            self.failed += 1
            return False
    
    def test_connect_missing_credentials(self):
        print_test("Connect with Missing Credentials")
        try:
            payload = {"tenant": "nonexistent", "app": "fake-app"}
            resp = requests.post(f"{self.base_url}/auth/connect", json=payload)
            
            if resp.status_code == 404:
                print_pass("Missing credentials correctly rejected (404)")
                self.passed += 1
                return True
            else:
                print_fail(f"Expected 404, got {resp.status_code}")
                self.failed += 1
                return False
                
        except Exception as e:
            print_fail(f"Missing credentials test error: {e}")
            self.failed += 1
            return False
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        total = self.passed + self.failed
        print(f"Total Tests: {total}")
        print(f"{Colors.GREEN}Passed: {self.passed}{Colors.END}")
        print(f"{Colors.RED}Failed: {self.failed}{Colors.END}")
        
        if self.failed == 0:
            print(f"\n{Colors.GREEN}✓ All tests passed!{Colors.END}")
        else:
            print(f"\n{Colors.RED}✗ {self.failed} test(s) failed{Colors.END}")
        
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Test session functionality')
    parser.add_argument('--skip-ttl', action='store_true', help='Skip TTL expiry test')
    parser.add_argument('--cleanup', action='store_true', help='Clean up test sessions')
    args = parser.parse_args()
    
    print("=" * 60)
    print("GoTo API Gateway - Session Tests")
    print("=" * 60)
    
    tester = SessionTester()
    
    if not tester.test_health():
        print_fail("API is not healthy. Make sure server is running.")
        return 1
    
    tests = [
        tester.test_status_without_session,
        tester.test_connect,
        tester.test_status_with_session,
        tester.test_invalid_session,
        tester.test_disconnect,
        tester.test_connect_missing_credentials,
    ]
    
    for test_func in tests:
        test_func()
    
    tester.print_summary()
    
    return 0 if tester.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
