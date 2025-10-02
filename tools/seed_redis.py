#!/usr/bin/env python3
"""
Seed Redis with test credentials for session-based authentication testing.

Usage:
    python tools/seed_redis.py --tenant cloudwarriors --app goto-gw
    
Prerequisites:
    - Redis running on localhost:6379
    - provider_manager.py in parent directory
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provider_manager import get_provider_manager
from datetime import datetime, timedelta
from dotenv import dotenv_values
import argparse
from jwt_utils import get_token_expiry, is_token_expired


def seed_system_credentials(pm, tenant, app):
    """Seed system credentials for OAuth client"""
    print(f"🌱 Seeding system credentials: tenant={tenant} app={app}")
    
    system_config = {
        'client_id': 'test_client_id_12345',
        'client_secret': 'test_client_secret_67890',
        'redirect_uri': 'http://localhost:9111',
        'auth_url': 'https://identity.goto.com/oauth/authorize',
        'token_url': 'https://identity.goto.com/oauth/token'
    }
    
    result = pm.add_system_credentials(tenant, app, system_config)
    
    if result:
        print(f"✅ System credentials seeded successfully")
        creds = pm.get_system_credentials(tenant, app)
        print(f"   Client ID: {creds.get('client_id')}")
        print(f"   Redirect URI: {creds.get('redirect_uri')}")
    else:
        print(f"❌ Failed to seed system credentials")
    
    return result


def seed_provider_tokens(pm, tenant, use_real_tokens=False):
    """Seed GoTo provider tokens"""
    print(f"🌱 Seeding provider tokens: tenant={tenant} provider=goto")
    
    if use_real_tokens:
        # Load from .env
        env_vars = dotenv_values('.env')
        
        access_token = env_vars.get('VOICE_ACCESS_TOKEN', '').strip("'\"")
        refresh_token = env_vars.get('VOICE_REFRESH_TOKEN', '').strip("'\"")
        client_id = env_vars.get('CLIENT_ID', '')
        client_secret = env_vars.get('CLIENT_SECRET', '')
        
        if not access_token:
            print("❌ No VOICE_ACCESS_TOKEN found in .env")
            return False
        
        # Extract real expiry from JWT
        expires_at = get_token_expiry(access_token)
        if not expires_at:
            expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z'
            print("⚠️  Could not extract expiry, using default")
        else:
            if is_token_expired(access_token):
                print(f"⚠️  Token already expired: {expires_at}")
            else:
                print(f"✅ Token valid until: {expires_at}")
    else:
        # Use fake tokens (existing logic)
        access_token = 'test_access_token_abcdef123456'
        refresh_token = 'test_refresh_token_ghijkl789012'
        client_id = 'test_client_id_12345'
        client_secret = 'test_client_secret_67890'
        expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z'
    
    provider_config = {
        'status': 'active',
        'auth_type': 'oauth',
        'client_id': client_id,
        'client_secret': client_secret,
        'account_key': '4266846632996939781',
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_expiry': expires_at,
        'scopes': ['voice-admin', 'admin', 'identity:scim.org'],
        'api_base_url': 'https://api.jive.com/voice-admin/v1',
        'features_enabled': ['call-queues', 'auto-attendants', 'extensions']
    }
    
    existing = pm.get_provider(tenant, 'goto')
    
    if existing:
        print(f"⚠️  Provider 'goto' already exists for tenant={tenant}")
        print(f"   Updating tokens instead...")
        result = pm.update_tokens(
            tenant, 
            'goto',
            provider_config['access_token'],
            provider_config['refresh_token'],
            expires_at
        )
    else:
        result = pm.add_provider(tenant, 'goto', provider_config)
    
    if result:
        print(f"✅ Provider tokens seeded successfully")
        provider = pm.get_provider(tenant, 'goto')
        print(f"   Access Token: {provider.get('access_token')[:20]}...")
        print(f"   Account Key: {provider.get('account_key')}")
        print(f"   Token Expiry: {provider.get('token_expiry')}")
    else:
        print(f"❌ Failed to seed provider tokens")
    
    return result


def seed_tenant_config(pm, tenant):
    """Seed tenant configuration"""
    print(f"🌱 Seeding tenant config: tenant={tenant}")
    
    tenant_config = {
        'name': 'Cloud Warriors Test Tenant',
        'primary_provider': 'goto',
        'sync_strategy': 'primary',
        'data_retention_days': 30,
        'timezone': 'America/New_York'
    }
    
    result = pm.set_tenant_config(tenant, tenant_config)
    
    if result:
        print(f"✅ Tenant config seeded successfully")
        config = pm.get_tenant_config(tenant)
        print(f"   Name: {config.get('name')}")
        print(f"   Primary Provider: {config.get('primary_provider')}")
    else:
        print(f"❌ Failed to seed tenant config")
    
    return result


def verify_redis_connection(pm):
    """Test Redis connectivity"""
    try:
        pm.redis_client.ping()
        print("✅ Redis connection successful")
        return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("   Make sure Redis is running: redis-server")
        return False


def main():
    parser = argparse.ArgumentParser(description='Seed Redis with test data for session auth')
    parser.add_argument('--tenant', default='cloudwarriors', help='Tenant ID')
    parser.add_argument('--app', default='goto-gw', help='Application ID')
    parser.add_argument('--clean', action='store_true', help='Clean existing data first')
    parser.add_argument('--use-env-tokens', action='store_true', help='Use real tokens from .env instead of fake tokens')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Redis Seeding Script for GoTo API Gateway")
    print("=" * 60)
    
    pm = get_provider_manager()
    
    if not verify_redis_connection(pm):
        return 1
    
    if args.clean:
        print(f"\n🧹 Cleaning existing data...")
        pm.delete_system_credentials(args.tenant, args.app)
        pm.delete_provider(args.tenant, 'goto')
        print(f"✅ Cleanup complete\n")
    
    print(f"\nSeeding data for tenant={args.tenant} app={args.app}\n")
    
    success = True
    success &= seed_tenant_config(pm, args.tenant)
    success &= seed_system_credentials(pm, args.tenant, args.app)
    success &= seed_provider_tokens(pm, args.tenant, args.use_env_tokens)
    
    print("\n" + "=" * 60)
    if success:
        print("✅ All data seeded successfully!")
        print("\nNext steps:")
        print(f"  1. Start the API: ./venv/bin/python app.py")
        print(f"  2. Test connect: curl -X POST -H 'Content-Type: application/json' \\")
        print(f"     -d '{{\"tenant\":\"{args.tenant}\",\"app\":\"{args.app}\"}}' \\")
        print(f"     http://localhost:8078/auth/connect")
    else:
        print("❌ Some operations failed. Check errors above.")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
