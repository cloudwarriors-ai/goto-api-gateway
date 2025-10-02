#!/usr/bin/env python3

import redis
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv()


class ProviderManager:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True
        )
    
    def get_tenant_key(self, tenant_id: str) -> str:
        return f"tenant:{tenant_id}"
    
    def get_provider_key(self, tenant_id: str, provider: str) -> str:
        return f"tenant:{tenant_id}:provider:{provider}"
    
    def get_providers_set_key(self, tenant_id: str) -> str:
        return f"tenant:{tenant_id}:providers"
    
    def get_system_key(self, tenant_id: str, app: str) -> str:
        return f"tenant:{tenant_id}:system:{app}"
    
    def get_systems_set_key(self, tenant_id: str) -> str:
        return f"tenant:{tenant_id}:systems"
    
    def add_provider(
        self,
        tenant_id: str,
        provider: str,
        config: Dict[str, Any]
    ) -> bool:
        provider_key = self.get_provider_key(tenant_id, provider)
        providers_set_key = self.get_providers_set_key(tenant_id)
        
        provider_data = {
            'provider_type': provider,
            'status': config.get('status', 'active'),
            'auth_type': config.get('auth_type', 'oauth'),
            'client_id': str(config.get('client_id', '')),
            'client_secret': str(config.get('client_secret', '')),
            'account_key': str(config.get('account_key', '')),
            'access_token': str(config.get('access_token', '')),
            'refresh_token': str(config.get('refresh_token', '')),
            'token_expiry': str(config.get('token_expiry', '')),
            'scopes': json.dumps(config.get('scopes', [])),
            'api_base_url': str(config.get('api_base_url', '')),
            'webhook_url': str(config.get('webhook_url', '')),
            'features_enabled': json.dumps(config.get('features_enabled', [])),
            'sync_enabled': str(config.get('sync_enabled', True)),
            'last_sync': str(config.get('last_sync', '')),
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z',
        }
        
        self.redis_client.hset(provider_key, mapping=provider_data)
        self.redis_client.sadd(providers_set_key, provider)
        
        return True
    
    def get_provider(self, tenant_id: str, provider: str) -> Optional[Dict[str, Any]]:
        provider_key = self.get_provider_key(tenant_id, provider)
        data = self.redis_client.hgetall(provider_key)
        
        if not data:
            return None
        
        data['scopes'] = json.loads(data.get('scopes', '[]'))
        data['features_enabled'] = json.loads(data.get('features_enabled', '[]'))
        data['sync_enabled'] = data.get('sync_enabled', 'True') == 'True'
        
        return data
    
    def get_all_providers(self, tenant_id: str) -> List[str]:
        providers_set_key = self.get_providers_set_key(tenant_id)
        return list(self.redis_client.smembers(providers_set_key))
    
    def update_provider(
        self,
        tenant_id: str,
        provider: str,
        updates: Dict[str, Any]
    ) -> bool:
        provider_key = self.get_provider_key(tenant_id, provider)
        
        if not self.redis_client.exists(provider_key):
            return False
        
        update_data = {}
        for key, value in updates.items():
            if key in ['scopes', 'features_enabled']:
                update_data[key] = json.dumps(value)
            elif key == 'sync_enabled':
                update_data[key] = str(value)
            else:
                update_data[key] = value
        
        update_data['updated_at'] = datetime.utcnow().isoformat() + 'Z'
        
        self.redis_client.hset(provider_key, mapping=update_data)
        return True
    
    def delete_provider(self, tenant_id: str, provider: str) -> bool:
        provider_key = self.get_provider_key(tenant_id, provider)
        providers_set_key = self.get_providers_set_key(tenant_id)
        
        self.redis_client.delete(provider_key)
        self.redis_client.srem(providers_set_key, provider)
        
        return True
    
    def update_tokens(
        self,
        tenant_id: str,
        provider: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[str] = None
    ) -> bool:
        updates = {
            'access_token': access_token,
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }
        
        if refresh_token:
            updates['refresh_token'] = refresh_token
        
        if expires_at:
            updates['token_expiry'] = expires_at
        
        return self.update_provider(tenant_id, provider, updates)
    
    def get_active_providers(self, tenant_id: str) -> List[Dict[str, Any]]:
        providers = self.get_all_providers(tenant_id)
        active_providers = []
        
        for provider in providers:
            provider_data = self.get_provider(tenant_id, provider)
            if provider_data and provider_data.get('status') == 'active':
                active_providers.append(provider_data)
        
        return active_providers
    
    def set_tenant_config(self, tenant_id: str, config: Dict[str, Any]) -> bool:
        tenant_key = f"{self.get_tenant_key(tenant_id)}:config"
        
        tenant_data = {
            'name': config.get('name', tenant_id),
            'primary_provider': config.get('primary_provider', ''),
            'sync_strategy': config.get('sync_strategy', 'primary'),
            'data_retention_days': str(config.get('data_retention_days', 30)),
            'timezone': config.get('timezone', 'UTC'),
            'created_at': config.get('created_at', datetime.utcnow().isoformat() + 'Z'),
            'updated_at': datetime.utcnow().isoformat() + 'Z',
        }
        
        self.redis_client.hset(tenant_key, mapping=tenant_data)
        return True
    
    def get_tenant_config(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        tenant_key = f"{self.get_tenant_key(tenant_id)}:config"
        data = self.redis_client.hgetall(tenant_key)
        
        if not data:
            return None
        
        data['data_retention_days'] = int(data.get('data_retention_days', 30))
        return data
    
    def add_system_credentials(
        self,
        tenant_id: str,
        app: str,
        config: Dict[str, Any]
    ) -> bool:
        system_key = self.get_system_key(tenant_id, app)
        systems_set_key = self.get_systems_set_key(tenant_id)
        
        system_data = {
            'client_id': str(config.get('client_id', '')),
            'client_secret': str(config.get('client_secret', '')),
            'redirect_uri': str(config.get('redirect_uri', '')),
            'auth_url': str(config.get('auth_url', '')),
            'token_url': str(config.get('token_url', '')),
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z',
        }
        
        self.redis_client.hset(system_key, mapping=system_data)
        self.redis_client.sadd(systems_set_key, app)
        
        return True
    
    def get_system_credentials(self, tenant_id: str, app: str) -> Optional[Dict[str, Any]]:
        system_key = self.get_system_key(tenant_id, app)
        data = self.redis_client.hgetall(system_key)
        
        if not data:
            return None
        
        return data
    
    def get_all_systems(self, tenant_id: str) -> List[str]:
        systems_set_key = self.get_systems_set_key(tenant_id)
        return list(self.redis_client.smembers(systems_set_key))
    
    def update_system_credentials(
        self,
        tenant_id: str,
        app: str,
        updates: Dict[str, Any]
    ) -> bool:
        system_key = self.get_system_key(tenant_id, app)
        
        if not self.redis_client.exists(system_key):
            return False
        
        updates['updated_at'] = datetime.utcnow().isoformat() + 'Z'
        
        self.redis_client.hset(system_key, mapping=updates)
        return True
    
    def delete_system_credentials(self, tenant_id: str, app: str) -> bool:
        system_key = self.get_system_key(tenant_id, app)
        systems_set_key = self.get_systems_set_key(tenant_id)
        
        self.redis_client.delete(system_key)
        self.redis_client.srem(systems_set_key, app)
        
        return True


def get_provider_manager():
    return ProviderManager(
        redis_host=os.getenv('REDIS_HOST', 'localhost'),
        redis_port=int(os.getenv('REDIS_PORT', 6379)),
        redis_db=int(os.getenv('REDIS_DB', 0))
    )
