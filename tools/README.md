# GoTo API Gateway Tools

Utility scripts for managing session-based authentication and testing the GoTo API Gateway.

## Overview

This directory contains tools for:
- **Seeding** Redis with test credentials
- **Testing** session functionality
- **Migrating** existing .env credentials to Redis
- **Verifying** OpenAPI specification completeness

## Prerequisites

- Redis running on `localhost:6379`
- API server running on `localhost:8078`
- Python 3.7+ with required dependencies installed

## Tools

### 1. seed_redis.py

Seeds Redis with test credentials for session authentication testing.

**Usage:**
```bash
# Seed with defaults (tenant=cloudwarriors, app=goto-gw)
python tools/seed_redis.py

# Seed with custom tenant/app
python tools/seed_redis.py --tenant acme --app myapp

# Clean existing data and re-seed
python tools/seed_redis.py --clean
```

**What it seeds:**
- System credentials (OAuth client_id/client_secret)
- Provider tokens (GoTo access/refresh tokens)
- Tenant configuration

---

### 2. test_sessions.py

Comprehensive test suite for session-based authentication functionality.

**Usage:**
```bash
# Run all tests (except TTL expiry test)
python tools/test_sessions.py

# Run all tests including 5+ minute TTL test
python tools/test_sessions.py --skip-ttl=false

# Run with cleanup
python tools/test_sessions.py --cleanup
```

**Tests included:**
1. ✅ API health check
2. ✅ Session creation (POST /auth/connect)
3. ✅ Session validation (GET /auth/status?session_id=...)
4. ✅ Legacy status check (backward compat)
5. ✅ Invalid session rejection (401)
6. ✅ Session deletion (POST /auth/disconnect)
7. ✅ Missing credentials error (404)

**Expected output:**
```
==============================================================
GoTo API Gateway - Session Tests
==============================================================

▶ Testing: API Health Check
  ✓ API is healthy
  ℹ Redis: ✓

▶ Testing: Session Creation (POST /auth/connect)
  ✓ Session created successfully
  ℹ Session ID: 550e8400-e29b-41d4-a716-446655440000
  ℹ Expires in: 300s

...

==============================================================
Test Summary
==============================================================
Total Tests: 7
Passed: 7
Failed: 0

✓ All tests passed!
==============================================================
```

---

### 3. verify_openapi.py

Verifies that the OpenAPI specification includes all required session endpoints and schemas.

**Usage:**
```bash
python tools/verify_openapi.py
```

**Checks:**
- Required endpoints: `/auth/connect`, `/auth/disconnect`, `/auth/status`, `/health`
- Required schemas: `ConnectRequest`, `ConnectResponse`, etc.
- Proxy endpoints: `/voice-proxy/{path}`, `/admin-proxy/{path}`

**View interactive docs:**
After verification, visit http://localhost:8078/docs

---

### 4. migrate_env_to_redis.py

Migrates existing credentials from `.env` file to Redis for session-based authentication.

**Usage:**
```bash
# Migrate with defaults
python tools/migrate_env_to_redis.py

# Migrate with custom tenant/app
python tools/migrate_env_to_redis.py --tenant acme --app myapp

# Migrate from specific .env file
python tools/migrate_env_to_redis.py --env /path/to/.env
```

**What it migrates:**
- System credentials: `CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_URI`
- Provider tokens: `ACCESS_TOKEN`, `REFRESH_TOKEN`, `VOICE_ACCESS_TOKEN`
- Account key: `ACCOUNT_KEY` (or uses default)

**Important:**
- The original `.env` file is **NOT modified**
- Credentials remain in `.env` for backward compatibility
- The application will use Redis for session-based auth going forward

---

## Typical Workflow

### Initial Setup

1. **Start Redis** (if not running):
   ```bash
   redis-server
   ```

2. **Seed test data**:
   ```bash
   python tools/seed_redis.py --clean
   ```

3. **Start API server**:
   ```bash
   ./venv/bin/python app.py
   ```

4. **Run tests**:
   ```bash
   python tools/test_sessions.py
   ```

5. **Verify OpenAPI**:
   ```bash
   python tools/verify_openapi.py
   ```

### Migration from Existing Deployment

If you have an existing `.env` file with credentials:

1. **Migrate credentials**:
   ```bash
   python tools/migrate_env_to_redis.py
   ```

2. **Verify migration**:
   ```bash
   python tools/test_sessions.py
   ```

3. **Update deployment** to use Redis-based sessions

---

## Troubleshooting

### Redis Connection Failed

**Error:** `❌ Redis connection failed: Error 111 connecting to localhost:6379. Connection refused.`

**Solution:**
```bash
# Start Redis
redis-server

# Or if using systemd
sudo systemctl start redis
```

### API Not Healthy

**Error:** `❌ API is not healthy. Make sure server is running.`

**Solution:**
```bash
# Start the API server
./venv/bin/python app.py

# Check if running
curl http://localhost:8078/health
```

### Session Creation Fails (404)

**Error:** `System credentials not found for tenant=X app=Y`

**Solution:**
```bash
# Seed credentials first
python tools/seed_redis.py --tenant X --app Y
```

### Token Expired

If provider tokens have expired:

```bash
# Re-seed with fresh tokens
python tools/seed_redis.py --clean
```

---

## Redis Data Structure

After running seed_redis.py, Redis contains:

```
tenant:cloudwarriors:system:goto-gw (HASH)
  - client_id
  - client_secret
  - redirect_uri
  - auth_url
  - token_url
  - created_at
  - updated_at

tenant:cloudwarriors:provider:goto (HASH)
  - provider_type: goto
  - status: active
  - auth_type: oauth
  - client_id
  - client_secret
  - account_key
  - access_token
  - refresh_token
  - token_expiry
  - scopes (JSON array)
  - api_base_url
  - features_enabled (JSON array)
  - created_at
  - updated_at

tenant:cloudwarriors:systems (SET)
  - goto-gw

tenant:cloudwarriors:providers (SET)
  - goto

tenant:cloudwarriors:config (HASH)
  - name
  - primary_provider
  - sync_strategy
  - data_retention_days
  - timezone
  - created_at
  - updated_at
```

Sessions are created dynamically:
```
session:{uuid} (HASH, TTL=300s)
  - tenant
  - app
  - system_creds (JSON string)
  - provider_tokens (JSON string)
  - created_at
  - expires_at
```

---

## Environment Variables

Scripts respect these environment variables:

- `REDIS_HOST` - Redis hostname (default: localhost)
- `REDIS_PORT` - Redis port (default: 6379)
- `REDIS_DB` - Redis database number (default: 0)
- `LOG_LEVEL` - Logging level (default: INFO)

---

## Contributing

When adding new tools:

1. Add shebang: `#!/usr/bin/env python3`
2. Add docstring with usage examples
3. Make executable: `chmod +x tools/your_script.py`
4. Update this README
5. Test with various scenarios

---

## Support

For issues or questions:
- Check the main README.md in the project root
- Review AUTHFLOW.md for authentication flow details
- Consult MULTI_PROVIDER_IMPLEMENTATION.md for architecture info
