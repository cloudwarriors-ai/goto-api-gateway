#!/usr/bin/env python3
"""Verify OpenAPI spec contains all required session endpoints"""

import requests
import json
import sys


def verify_openapi():
    print("🔍 Fetching OpenAPI spec from http://localhost:8078/openapi.json...")
    
    try:
        resp = requests.get("http://localhost:8078/openapi.json")
        spec = resp.json()
    except Exception as e:
        print(f"❌ Failed to fetch OpenAPI: {e}")
        return False
    
    print("✅ OpenAPI spec retrieved\n")
    
    required_endpoints = [
        ("/auth/connect", "post"),
        ("/auth/disconnect", "post"),
        ("/auth/status", "get"),
        ("/health", "get"),
        ("/voice-proxy/{api_path:path}", "get"),
        ("/admin-proxy/{api_path:path}", "get")
    ]
    
    paths = spec.get("paths", {})
    
    print("📋 Checking required endpoints...")
    all_found = True
    
    for endpoint, method in required_endpoints:
        found = False
        for path_key in paths:
            if path_key in [endpoint, endpoint.replace(":path", "")]:
                if method in paths[path_key]:
                    print(f"  ✓ {method.upper()} {endpoint}")
                    found = True
                    break
        
        if not found:
            print(f"  ✗ {method.upper()} {endpoint} - MISSING")
            all_found = False
    
    print()
    
    print("📋 Checking required schemas...")
    required_schemas = [
        "ConnectRequest",
        "ConnectResponse",
        "DisconnectResponse",
        "StatusResponse"
    ]
    
    components = spec.get("components", {})
    schemas = components.get("schemas", {})
    
    for schema in required_schemas:
        if schema in schemas:
            print(f"  ✓ {schema}")
        else:
            print(f"  ✗ {schema} - MISSING")
            all_found = False
    
    print()
    
    if all_found:
        print("✅ All required endpoints and schemas present!")
        print(f"\nℹ️  View interactive docs at: http://localhost:8078/docs")
        return True
    else:
        print("❌ Some required items are missing")
        return False


if __name__ == '__main__':
    success = verify_openapi()
    sys.exit(0 if success else 1)
