# GoTo API Gateway - Quick Reference

**Last Updated**: October 2, 2025  
**Version**: 2.0 (Session-Based Auth)

---

## 🚀 Quick Start

### 1. Create a Session
```bash
curl -X POST http://localhost:8078/auth/connect \
  -H "Content-Type: application/json" \
  -d '{"tenant":"cloudwarriors","app":"goto"}'

# Returns:
{
  "success": true,
  "data": {
    "session_id": "abc123...",
    "expires_in": 300
  }
}
```

### 2. Use Session in API Calls
```bash
# Add session_id as query parameter
curl "http://localhost:8078/voice-proxy/extensions?session_id=abc123..."
```

### 3. Disconnect When Done
```bash
curl -X POST "http://localhost:8078/auth/disconnect?session_id=abc123..."
```

---

## 📋 Common API Endpoints

### **Users / Extensions**
> ⚠️ **IMPORTANT**: Users are called "extensions" in the GoTo Voice API

```bash
# List all users (extensions with type=DIRECT_EXTENSION)
GET /voice-proxy/extensions?session_id=xxx

# Filter by type
GET /voice-proxy/extensions?type=DIRECT_EXTENSION&session_id=xxx
GET /voice-proxy/extensions?type=CALL_QUEUE&session_id=xxx
GET /voice-proxy/extensions?type=DIAL_PLAN&session_id=xxx
```

**Extension Types:**
- `DIRECT_EXTENSION` - Regular users
- `CALL_QUEUE` - Call queue extensions
- `DIAL_PLAN` - Auto-attendants
- `CONFERENCE_BRIDGE` - Conference rooms
- `RING_GROUP` - Ring groups

### **Account Information**
```bash
# Get account details
GET /voice-proxy/accounts/4266846632996939781?session_id=xxx
```

### **Call Queues**
```bash
# List call queues
GET /voice-proxy/call-queues?session_id=xxx

# Get specific queue
GET /voice-proxy/call-queues/{queue_id}?session_id=xxx

# Get queue users
GET /voice-proxy/call-queues/{queue_id}/users?session_id=xxx
```

### **Phone Numbers**
```bash
# List phone numbers
GET /voice-proxy/phone-numbers?session_id=xxx
```

### **Locations**
```bash
# List office locations
GET /voice-proxy/locations?session_id=xxx
```

### **Devices**
```bash
# List voice devices
GET /voice-proxy/devices?session_id=xxx
```

---

## 🔍 Session Management

### **Check Session Status**
```bash
# With session_id (session-based)
GET /auth/status?session_id=abc123...

# Without session_id (legacy mode)
GET /auth/status
```

**Response:**
```json
{
  "success": true,
  "data": {
    "voice_authenticated": true,
    "admin_authenticated": false,
    "scim_authenticated": false,
    "tenant": "cloudwarriors",
    "app": "goto",
    "session_id": "abc123...",
    "expires_at": "2025-10-02T15:30:00Z",
    "provider_token_expiry": "2025-10-02T18:10:23Z"
  }
}
```

---

## 🔄 Token Refresh

**Automatic:** Tokens are automatically refreshed when expired (no action needed)

**Manual Refresh:**
```bash
POST /tenants/cloudwarriors/providers/goto/refresh-token
```

---

## 🏥 Health Check

```bash
GET /health

# Returns:
{
  "status": "healthy",
  "tenant_id": "cloudwarriors",
  "redis_healthy": true,
  "providers": {
    "goto": {
      "status": "active",
      "has_token": true,
      "token_expiry": "2025-10-02T18:10:23Z"
    }
  },
  "account_key": "4266846632996939781"
}
```

---

## 📝 Example: Get User List

```bash
# Step 1: Connect
SESSION_ID=$(curl -s -X POST http://localhost:8078/auth/connect \
  -H "Content-Type: application/json" \
  -d '{"tenant":"cloudwarriors","app":"goto"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['data']['session_id'])")

# Step 2: Get users (extensions)
curl -s "http://localhost:8078/voice-proxy/extensions?session_id=$SESSION_ID" | \
  python3 -m json.tool

# Step 3: Disconnect
curl -s -X POST "http://localhost:8078/auth/disconnect?session_id=$SESSION_ID"
```

**Output:**
```json
{
  "items": [
    {
      "id": "3835e9a3-2368-4e53-82b5-50d1358f0d1d",
      "number": "1000",
      "name": "Chris Nebel",
      "type": "DIRECT_EXTENSION",
      "accountKey": "4266846632996939781"
    },
    ...
  ]
}
```

---

## ⚙️ Configuration

### Redis Connection
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

### Credentials Storage
```
Redis Keys:
- tenant:{tenant}:config                    # Tenant config
- tenant:{tenant}:system:{app}              # System credentials (OAuth client)
- tenant:{tenant}:provider:{provider}       # Provider tokens
- session:{session_id}                      # Active sessions (300s TTL)
```

---

## 🐛 Troubleshooting

### Token Expired Error
```json
{"errorCode": "AUTHN_INVALID_TOKEN"}
```
**Solution:** Token refresh happens automatically. Check logs for refresh errors.

### Session Not Found
```json
{"detail": "Session not found or expired"}
```
**Solution:** Create a new session with `/auth/connect`

### Provider Not Found
```json
{"detail": "Provider goto not found"}
```
**Solution:** Seed credentials with `python tools/seed_redis.py`

---

## 🛠️ Tools

```bash
# Seed Redis with credentials
python tools/seed_redis.py

# Run session tests
python tools/test_sessions.py

# Verify OpenAPI schema
python tools/verify_openapi.py

# Migrate .env to Redis
python tools/migrate_env_to_redis.py
```

---

## 📚 API Documentation

Interactive API docs available at:
- Swagger UI: http://localhost:8078/docs
- ReDoc: http://localhost:8078/redoc
- OpenAPI JSON: http://localhost:8078/openapi.json
