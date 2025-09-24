## GoTo API Gateway Authentication Flow

### Prerequisites
- `.env` file with `CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_URI`, `LOGIN_EMAIL`, `LOGIN_PASSWORD`
- Playwright MCP server configured in `opencode.json` with CDP endpoint
- External CDP session running at `http://localhost:9222` (e.g., Chrome with `--remote-debugging-port=9222`)
- Local FastAPI server running on `REDIRECT_URI` (default: `http://localhost:9111`)

### Step-by-Step Flow

1. **Initialization**
   - `GoToAuthManager` loads credentials from environment variables
   - Parses existing tokens and calculates expiry times from JWT payloads

2. **OAuth URL Generation**
   - Constructs authorization URL: `https://authentication.logmeininc.com/oauth/authorize`
   - Includes `client_id`, `redirect_uri`, `response_type=code`, `state`, and optional `scope`
   - URL encodes parameters properly

3. **Automated Browser Authentication**
    - Connects to external CDP session at `localhost:9222`
    - Navigates to OAuth URL in the existing browser session
    - Fills email field and clicks "Next"
    - Fills password field and clicks "Sign in"
    - Handles MFA if present (waits for manual input)
    - Reaches consent page (`oauth/approve`)

4. **Consent and Authorization**
    - Clicks "Allow" button on consent page
    - Waits for redirect to FastAPI callback at `localhost:9111`
    - FastAPI receives the auth code and exchanges it for tokens automatically

5. **Token Exchange**
   - POST to `https://identity.goto.com/oauth/token`
   - Uses Basic Auth with `client_id:client_secret`
   - Sends `grant_type=authorization_code`, `code`, `redirect_uri`
   - Receives `access_token`, `refresh_token`, `expires_in`, `scope`

6. **Token Storage and Management**
   - Determines token type based on scope:
     - `voice-admin` → voice tokens
     - `identity:scim.org` → SCIM tokens
     - Default → admin tokens
   - Updates in-memory variables and environment variables
   - Writes to `.env` file using `set_key()`
   - Sets expiry time (current time + expires_in - 300 seconds buffer)

7. **Token Refresh**
   - Checks token expiry before use
   - If expired, POST to token endpoint with `grant_type=refresh_token`
   - Updates tokens and `.env` file
   - Returns valid token or None on failure

8. **Authentication Assurance**
   - `ensure_authentication()` method checks required tokens
   - Triggers OAuth flow for missing tokens
   - Supports admin and voice token requirements

### Token Types
- **Admin**: General API access
- **Voice**: Voice admin API access (`voice-admin.v1.read` scope)
- **SCIM**: Identity management API access (`identity:scim.org` scope)

### Error Handling
- Network failures, invalid credentials, MFA requirements
- Token exchange failures, refresh failures
- Browser automation timeouts and exceptions

### Security Notes
- Credentials stored in `.env` (not committed to git)
- Tokens refreshed automatically before expiry
- Basic Auth used for client credentials
- JWT tokens parsed for expiry validation

## Authentication Checklist

- [x] 1. Is the CDP session online at port 9222? (Yes - required for browser automation)
- [x] 2. Start FastAPI server on port 9111 (Done - server running with callback handler)
- [x] 3. Use Playwright MCP to navigate to OAuth URL and complete authentication (Success - auth code received)
- [x] 4. Tokens are automatically exchanged and stored in .env (Done - VOICE_ACCESS_TOKEN and SCIM_ACCESS_TOKEN set)
- [x] 5. Use curl to check health: `curl http://localhost:9111/health` (Tokens available)
- [x] 6. Use curl to get user list: `curl http://localhost:9111/voice-proxy/extensions` (Success - retrieved users)

## Usage After Authentication

Once authentication is complete:

1. **Check Health**: `curl http://localhost:9111/health`
   - Confirms tokens are available

2. **Get User List**: `curl http://localhost:9111/voice-proxy/extensions`
   - Returns JSON with all extensions (users, queues, etc.)
   - Filter for `"type": "DIRECT_EXTENSION"` to get users only

3. **Other Endpoints**:
   - `/voice-proxy/call-queues` - List call queues
   - `/admin-proxy/me` - Get current user info
   - `/scim-proxy/Users` - SCIM user management (if SCIM token available)