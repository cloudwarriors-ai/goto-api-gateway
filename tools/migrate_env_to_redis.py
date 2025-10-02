#!/usr/bin/env python3
"""
Migrate credentials from .env file to Redis for session-based authentication.

Usage:
    python tools/migrate_env_to_redis.py --tenant cloudwarriors --app goto-gw
    
This script reads credentials from .env and populates Redis with:
- System credentials (CLIENT_ID, CLIENT_SECRET)
- Provider tokens (ACCESS_TOKEN, REFRESH_TOKEN, etc.)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provider_manager import get_provider_manager
from datetime import datetime, timedelta
from dotenv import dotenv_values
import argparse
from jwt_utils import get_token_expiry, is_token_expired


def migrate_to_redis(pm, tenant, app, env_path='.env'):
    print(f"🔄 Migrating credentials from {env_path} to Redis...")
    print(f"   Tenant: {tenant}")
    print(f"   App: {app}\n")
    
    if not os.path.exists(env_path):
        print(f"❌ .env file not found at: {env_path}")
        return False
    
    env_vars = dotenv_values(env_path)
    
    system_config = {
        'client_id': env_vars.get('CLIENT_ID', ''),
        'client_secret': env_vars.get('CLIENT_SECRET', ''),
        'redirect_uri': env_vars.get('REDIRECT_URI', 'http://localhost:9111'),
        'auth_url': 'https://identity.goto.com/oauth/authorize',
        'token_url': 'https://identity.goto.com/oauth/token'
    }
    
    if not system_config['client_id'] or not system_config['client_secret']:
        print("⚠️  CLIENT_ID or CLIENT_SECRET not found in .env")
        print("   Skipping system credentials migration")
    else:
        print("📝 Migrating system credentials...")
        result = pm.add_system_credentials(tenant, app, system_config)
        if result:
            print(f"✅ System credentials migrated")
        else:
            print(f"❌ Failed to migrate system credentials")
    
    access_token = env_vars.get('ACCESS_TOKEN') or env_vars.get('VOICE_ACCESS_TOKEN')
    refresh_token = env_vars.get('REFRESH_TOKEN') or env_vars.get('VOICE_REFRESH_TOKEN')
    
    if not access_token:
        print("\n⚠️  No ACCESS_TOKEN or VOICE_ACCESS_TOKEN found in .env")
        print("   Skipping provider tokens migration")
        return True
    
    print("\n📝 Migrating provider tokens...")
    
    # Extract real expiry from JWT token
    access_token_clean = access_token.strip("'\"")
    expires_at = get_token_expiry(access_token_clean)
    
    if not expires_at:
        print("⚠️  Could not extract expiry from token, using 1 hour default")
        expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z'
    else:
        # Check if token is already expired
        if is_token_expired(access_token_clean):
            print(f"⚠️  Token is already expired (exp: {expires_at})")
            print(f"   Migration will proceed, but token refresh will be needed")
        else:
            print(f"✅ Token valid until: {expires_at}")
    
    provider_config = {
        'status': 'active',
        'auth_type': 'oauth',
        'client_id': system_config['client_id'],
        'client_secret': system_config['client_secret'],
        'account_key': env_vars.get('ACCOUNT_KEY', '4266846632996939781'),
        'access_token': access_token,
        'refresh_token': refresh_token or '',
        'token_expiry': expires_at,
        'scopes': ['voice-admin', 'admin', 'identity:scim.org'],
        'api_base_url': 'https://api.jive.com/voice-admin/v1',
        'features_enabled': ['call-queues', 'auto-attendants', 'extensions']
    }
    
    existing = pm.get_provider(tenant, 'goto')
    
    if existing:
        print(f"⚠️  Provider 'goto' already exists - updating tokens")
        result = pm.update_tokens(tenant, 'goto', access_token, refresh_token, expires_at)
    else:
        result = pm.add_provider(tenant, 'goto', provider_config)
    
    if result:
        print(f"✅ Provider tokens migrated")
    else:
        print(f"❌ Failed to migrate provider tokens")
        return False
    
    tenant_config = {
        'name': f'{tenant.title()} (Migrated)',
        'primary_provider': 'goto',
        'sync_strategy': 'primary',
        'data_retention_days': 30,
        'timezone': 'UTC'
    }
    
    pm.set_tenant_config(tenant, tenant_config)
    
    print(f"\n✅ Migration complete!")
    print(f"\n⚠️  IMPORTANT: .env file has NOT been modified")
    print(f"   Your credentials remain in .env for backward compatibility")
    print(f"   The application will now use Redis for session-based auth")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='Migrate .env credentials to Redis')
    parser.add_argument('--tenant', default='cloudwarriors', help='Tenant ID')
    parser.add_argument('--app', default='goto-gw', help='Application ID')
    parser.add_argument('--env', default='.env', help='Path to .env file')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Environment to Redis Migration Script")
    print("=" * 60)
    
    pm = get_provider_manager()
    
    try:
        pm.redis_client.ping()
        print("✅ Redis connection successful\n")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("   Make sure Redis is running: redis-server")
        return 1
    
    success = migrate_to_redis(pm, args.tenant, args.app, args.env)
    
    print("\n" + "=" * 60)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
