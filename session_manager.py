#!/usr/bin/env python3

import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class SessionManager:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.session_ttl = 300
    
    def _get_session_key(self, session_id: str) -> str:
        return f"session:{session_id}"
    
    def create_session(
        self,
        tenant: str,
        app: str,
        system_creds: Dict[str, Any],
        provider_tokens: Dict[str, Any]
    ) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat() + 'Z'
        expires_at = (datetime.utcnow() + timedelta(seconds=self.session_ttl)).isoformat() + 'Z'
        
        session_data = {
            'tenant': tenant,
            'app': app,
            'system_creds': json.dumps(system_creds),
            'provider_tokens': json.dumps(provider_tokens),
            'created_at': created_at,
            'expires_at': expires_at
        }
        
        session_key = self._get_session_key(session_id)
        self.redis_client.hset(session_key, mapping=session_data)
        self.redis_client.expire(session_key, self.session_ttl)
        
        return {
            'session_id': session_id,
            'tenant': tenant,
            'app': app,
            'expires_in': self.session_ttl,
            'expires_at': expires_at,
            'created_at': created_at
        }
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session_key = self._get_session_key(session_id)
        data = self.redis_client.hgetall(session_key)
        
        if not data:
            return None
        
        data['system_creds'] = json.loads(data.get('system_creds', '{}'))
        data['provider_tokens'] = json.loads(data.get('provider_tokens', '{}'))
        
        return data
    
    def validate_session(self, session_id: str) -> bool:
        session_key = self._get_session_key(session_id)
        return self.redis_client.exists(session_key) > 0
    
    def delete_session(self, session_id: str) -> bool:
        session_key = self._get_session_key(session_id)
        deleted = self.redis_client.delete(session_key)
        return deleted > 0
    
    def get_session_ttl(self, session_id: str) -> Optional[int]:
        session_key = self._get_session_key(session_id)
        ttl = self.redis_client.ttl(session_key)
        return ttl if ttl > 0 else None
    
    def refresh_session_ttl(self, session_id: str) -> bool:
        session_key = self._get_session_key(session_id)
        if not self.redis_client.exists(session_key):
            return False
        self.redis_client.expire(session_key, self.session_ttl)
        return True


def get_session_manager(redis_client):
    return SessionManager(redis_client)
