#!/usr/bin/env python3

import os
from dotenv import load_dotenv
from provider_manager import get_provider_manager
from datetime import datetime, timedelta

load_dotenv()


def migrate_goto_credentials():
    pm = get_provider_manager()
    tenant_id = "cloudwarriors"
    
    print(f"🔄 Migrating GoTo credentials for tenant: {tenant_id}")
    
    pm.set_tenant_config(tenant_id, {
        'name': 'Cloud Warriors',
        'primary_provider': 'goto',
        'sync_strategy': 'primary',
        'data_retention_days': 90,
        'timezone': 'America/New_York',
    })
    print(f"✅ Tenant config created")
    
    goto_config = {
        'status': 'active',
        'auth_type': 'oauth',
        'client_id': os.getenv('CLIENT_ID', ''),
        'client_secret': os.getenv('CLIENT_SECRET', ''),
        'account_key': '4266846632996939781',
        'access_token': os.getenv('VOICE_ACCESS_TOKEN', '').strip("'"),
        'refresh_token': os.getenv('VOICE_REFRESH_TOKEN', '').strip("'"),
        'token_expiry': (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z',
        'scopes': ['voice-admin.v1.read', 'identity:scim.org'],
        'api_base_url': 'https://api.jive.com/voice-admin/v1',
        'webhook_url': '',
        'features_enabled': ['users', 'extensions', 'call_queues', 'auto_attendants'],
        'sync_enabled': True,
        'last_sync': '',
    }
    
    pm.add_provider(tenant_id, 'goto', goto_config)
    print(f"✅ GoTo provider added with credentials")
    
    provider = pm.get_provider(tenant_id, 'goto')
    print(f"\n📋 GoTo Provider Details:")
    print(f"   Status: {provider['status']}")
    print(f"   Auth Type: {provider['auth_type']}")
    print(f"   Account Key: {provider['account_key']}")
    print(f"   Client ID: {provider['client_id'][:20]}...")
    print(f"   Access Token: {provider['access_token'][:50]}...")
    print(f"   Scopes: {provider['scopes']}")
    print(f"   Features: {provider['features_enabled']}")
    print(f"   Created: {provider['created_at']}")
    
    all_providers = pm.get_all_providers(tenant_id)
    print(f"\n📊 All providers for {tenant_id}: {all_providers}")
    
    tenant_config = pm.get_tenant_config(tenant_id)
    print(f"\n🏢 Tenant Config:")
    print(f"   Name: {tenant_config['name']}")
    print(f"   Primary Provider: {tenant_config['primary_provider']}")
    print(f"   Sync Strategy: {tenant_config['sync_strategy']}")


if __name__ == "__main__":
    migrate_goto_credentials()
