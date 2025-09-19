# GoTo Admin API Gateway

A Flask-based API gateway that provides authenticated access to the GoTo Admin REST API with automatic token refresh capabilities.

## Features

- 🔐 **OAuth 2.0 Authentication** - Complete OAuth flow with GoTo
- 🔄 **Automatic Token Refresh** - Handles token expiration automatically
- 🚀 **Comprehensive API Coverage** - Proxies all 115+ GoTo Admin API endpoints
- 📊 **Account Management** - Users, groups, licenses, settings
- 📈 **Reporting** - Activity, usage, meeting, and billing reports
- 🛡️ **Error Handling** - Robust error handling and validation
- 🎯 **Generic Proxy** - Catch-all endpoint for any GoTo API call

## Setup

### 1. OAuth Configuration

1. Go to [GoTo Developer Portal](https://developer.logmeininc.com/clients)
2. Create a new OAuth client with:
   - Redirect URI: `http://localhost:9111`
   - Scopes: Profile, Admin Center, SCIM
3. Copy your Client ID and Client Secret

### 2. Environment Configuration

Create a `.env` file:

```bash
CLIENT_ID=your_client_id_here
CLIENT_SECRET=your_client_secret_here
REDIRECT_URI=http://localhost:9111
LOGIN_EMAIL=your_goto_email@domain.com
LOGIN_PASSWORD=your_goto_password
ACCESS_TOKEN=your_access_token_here
REFRESH_TOKEN=your_refresh_token_here
```

### 3. Installation

```bash
# Create virtual environment
python3 -m venv venv
./venv/bin/pip install flask requests python-dotenv

# Run the server
./venv/bin/python app.py
```

## API Endpoints

### Authentication & Health
- `GET /health` - Health check and configuration status
- `GET /auth/status` - Authentication status and token expiry

### Admin Information
- `GET /me` - Get current admin user information

### Account Management
- `GET /accounts/{accountKey}` - Get account details
- `PUT /accounts/{accountKey}` - Update account
- `GET /accounts/{accountKey}/attributes` - Get account attributes
- `POST /accounts/{accountKey}/attributes` - Add account attribute

### Group Management
- `GET /accounts/{accountKey}/groups` - List groups
- `POST /accounts/{accountKey}/groups` - Create group
- `GET /accounts/{accountKey}/groups/{groupKey}` - Get group details
- `PUT /accounts/{accountKey}/groups/{groupKey}` - Update group
- `DELETE /accounts/{accountKey}/groups/{groupKey}` - Delete group

### User Management
- `GET /accounts/{accountKey}/users` - List users
- `POST /accounts/{accountKey}/users` - Create user
- `GET /accounts/{accountKey}/users/{userKey}` - Get user details
- `PUT /accounts/{accountKey}/users/{userKey}` - Update user
- `DELETE /accounts/{accountKey}/users/{userKey}` - Delete user

### Generic Proxy
- `{METHOD} /proxy/{api_path}` - Proxy any GoTo Admin API endpoint

## Usage Examples

### Admin API Examples
```bash
# Get current admin info
curl http://localhost:5000/me

# Get account details
curl http://localhost:5000/accounts/4266846632996939781

# List users
curl http://localhost:5000/accounts/4266846632996939781/users

# Get licenses
curl http://localhost:5000/proxy/accounts/4266846632996939781/licenses
```

### Voice Admin API Examples (with voice_gateway.py)
```bash
# List call queues
curl http://localhost:5000/call-queues

# Get queue users
curl http://localhost:5000/call-queues/dc465382-8d64-4922-a3bd-5ed2f76db553/users

# List extensions
curl http://localhost:5000/extensions

# List phone numbers
curl http://localhost:5000/phone-numbers
```

### Working Samples
See the `working-samples/` directory for comprehensive examples:
- OAuth automation scripts
- API testing utilities
- Resource discovery tools
- User management scripts

## Authentication Flow

The gateway handles authentication automatically using Playwright browser automation:

### Starting with No Tokens

When the application starts with no authentication tokens:

1. **Detection**: The `auth_manager` detects missing tokens when API calls are made
2. **Automated OAuth**: Launches Playwright browser automation to:
   - Navigate to GoTo OAuth authorization URL
   - Automatically fill in email/password from `.env`
   - Handle consent page approval
   - Extract authorization code from redirect
   - Exchange code for access and refresh tokens
3. **Token Storage**: Saves tokens to `.env` file for future use
4. **Seamless Operation**: API calls proceed normally after authentication

### Token Management

- **Automatic Refresh**: Tokens are refreshed before expiration
- **Dual Scope Support**: Handles both Admin API and Voice Admin API tokens
- **Persistence**: All tokens saved to `.env` for application restarts
- **Error Handling**: Graceful fallback to re-authentication if refresh fails

### Requirements for Automated Authentication

The `.env` file must contain:
- `LOGIN_EMAIL` - Your GoTo account email
- `LOGIN_PASSWORD` - Your GoTo account password
- `CLIENT_ID` - OAuth application client ID  
- `CLIENT_SECRET` - OAuth application client secret

**Note**: The system can handle MFA-enabled accounts but may require manual intervention for MFA code entry.

## GoTo API Integration

The gateway proxies requests to `https://api.getgo.com/admin/rest/v1/` with:

- **Bearer Token Authentication** - Automatically adds `Authorization: Bearer {token}` header
- **Content Type Headers** - Sets appropriate JSON headers
- **Query Parameters** - Forwards all query parameters
- **Request Bodies** - Forwards JSON request bodies for POST/PUT operations
- **Response Codes** - Returns original GoTo API status codes

## Error Handling

- **401 Unauthorized** - Token expired or invalid
- **404 Not Found** - Endpoint doesn't exist
- **500 Internal Error** - Request failed or network error
- **Original API Errors** - Forwards GoTo API error responses

## Development

The server runs in debug mode on `http://localhost:5000` and automatically reloads on code changes.

### Available Data

From your account, you have access to:
- **Account Key**: `4266846632996939781`
- **User Key**: `780362331528597503`
- **Account Name**: "Cloud Warrior - GTC - Demo"
- **Admin Roles**: SUPER_USER, MANAGE_USERS, MANAGE_ACCOUNT, etc.
- **Products**: G2M (GoTo Meeting), G2C (GoTo Connect), JIVE

## Project Structure

```
goto-api-gateway/
├── app.py                          # Main Flask API gateway (Admin API)
├── voice_gateway.py                # Voice & Admin API gateway (recommended)
├── working-samples/                # Complete working examples
│   ├── README.md                   # Detailed sample documentation
│   ├── automated_oauth.py          # OAuth URL generation
│   ├── complete_oauth.py           # Admin API token exchange
│   ├── exchange_voice_token.py     # Voice API token exchange
│   ├── test_*.py                   # API testing scripts
│   ├── list_*.py                   # Resource listing scripts
│   └── discover_resources.py       # Resource discovery utility
├── admin.postman_collection.json   # Admin API endpoints (115+)
├── GoToConnect.postman_collection.json # Voice Admin endpoints
├── Scim.postman_collection.json    # SCIM API endpoints
├── .env                            # Environment variables (tokens, config)
└── README.md                       # This file
```

## Security Notes

- Store `.env` file securely and never commit to version control
- Access tokens expire every hour (auto-refresh implemented)
- Refresh tokens are long-lived (30 days)
- All API calls require valid authentication
- Use HTTPS in production environments
- Voice Admin API requires separate `voice-admin.v1.read` scope

## Available Resources

### ✅ **Call Queues** (9 total)
- Cloud Warriors, WorkingQueue, Example Queue 1765
- Tyler 7/8/Pratt queues, test_token, d, ww
