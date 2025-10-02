#!/usr/bin/env python3
"""JWT token utility functions for extracting claims without verification"""

import base64
import json
from datetime import datetime
from typing import Optional, Dict, Any


def decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode JWT payload without signature verification.
    
    Args:
        token: JWT token string (can be with or without 'Bearer ' prefix)
    
    Returns:
        Decoded payload as dict, or None if decoding fails
    """
    try:
        if token.startswith('Bearer '):
            token = token[7:]
        
        token = token.strip("'\"")
        
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        payload = parts[1]
        
        padding = len(payload) % 4
        if padding:
            payload += '=' * (4 - padding)
        
        decoded_bytes = base64.urlsafe_b64decode(payload)
        
        payload_dict = json.loads(decoded_bytes)
        
        return payload_dict
    
    except Exception as e:
        print(f"⚠️  Failed to decode JWT: {e}")
        return None


def get_token_expiry(token: str) -> Optional[str]:
    """
    Extract expiry timestamp from JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        ISO 8601 timestamp string with 'Z' suffix, or None if extraction fails
    """
    payload = decode_jwt_payload(token)
    
    if not payload:
        return None
    
    exp_timestamp = payload.get('exp')
    if not exp_timestamp:
        return None
    
    try:
        exp_datetime = datetime.utcfromtimestamp(exp_timestamp)
        return exp_datetime.isoformat() + 'Z'
    except Exception as e:
        print(f"⚠️  Failed to parse expiry timestamp: {e}")
        return None


def get_token_issued_at(token: str) -> Optional[str]:
    """
    Extract issued-at timestamp from JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        ISO 8601 timestamp string with 'Z' suffix, or None if extraction fails
    """
    payload = decode_jwt_payload(token)
    
    if not payload:
        return None
    
    iat_timestamp = payload.get('iat')
    if not iat_timestamp:
        return None
    
    try:
        iat_datetime = datetime.utcfromtimestamp(iat_timestamp)
        return iat_datetime.isoformat() + 'Z'
    except Exception as e:
        print(f"⚠️  Failed to parse issued-at timestamp: {e}")
        return None


def is_token_expired(token: str) -> Optional[bool]:
    """
    Check if JWT token is expired based on its exp claim.
    
    Args:
        token: JWT token string
    
    Returns:
        True if expired, False if valid, None if cannot determine
    """
    payload = decode_jwt_payload(token)
    
    if not payload:
        return None
    
    exp_timestamp = payload.get('exp')
    if not exp_timestamp:
        return None
    
    try:
        exp_datetime = datetime.utcfromtimestamp(exp_timestamp)
        now = datetime.utcnow()
        return now >= exp_datetime
    except Exception:
        return None


def get_token_info(token: str) -> Dict[str, Any]:
    """
    Extract all useful information from JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Dict with token information (exp, iat, sub, scopes, etc.)
    """
    payload = decode_jwt_payload(token)
    
    if not payload:
        return {"error": "Failed to decode token"}
    
    info = {
        "subject": payload.get('sub'),
        "audience": payload.get('aud'),
        "scopes": payload.get('sc', ''),
        "issued_at": get_token_issued_at(token),
        "expires_at": get_token_expiry(token),
        "is_expired": is_token_expired(token),
        "token_type": payload.get('typ'),
        "level_of_assurance": payload.get('levelOfAssurance')
    }
    
    return info
