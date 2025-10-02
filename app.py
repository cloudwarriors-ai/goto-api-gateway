#!/usr/bin/env python3

import os
import logging
from typing import Optional, List

import requests
from dotenv import load_dotenv, set_key
import base64
import json
from datetime import datetime, timedelta

load_dotenv()
from fastapi import FastAPI, HTTPException, Query, Request, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from provider_manager import get_provider_manager
from session_manager import SessionManager

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GoTo API Gateway",
    version="2.0.0",
    description="""
A FastAPI-based gateway providing session-based authenticated access 
to the GoTo Admin and Voice API with automatic token refresh.

## Features
- 🔐 Session-based authentication (5-minute TTL)
- 🔄 Automatic token refresh
- 🚀 Comprehensive API coverage (Admin, Voice, SCIM)
- 🎯 Generic proxy endpoints for any GoTo API call
- 📊 Multi-tenant support with Redis-backed credential storage

## Authentication Flow
1. Seed credentials in Redis (tenant/system/provider)
2. POST /auth/connect to create a session
3. Use session_id in subsequent API calls
4. POST /auth/disconnect when done (or let TTL expire)

## Common API Endpoints
### Users (Extensions)
- GET /voice-proxy/extensions - List all users/extensions (type=DIRECT_EXTENSION)
- GET /voice-proxy/extensions?type=CALL_QUEUE - List call queues
- GET /voice-proxy/extensions?type=DIAL_PLAN - List auto-attendants

### Account Info
- GET /voice-proxy/accounts/{account_key} - Get account details
""",
    contact={
        "name": "GoTo Gateway Team"
    },
    license_info={
        "name": "MIT"
    }
)
pm = get_provider_manager()
sm = SessionManager(pm.redis_client)

ADMIN_BASE_URL = "https://api.getgo.com/admin/rest/v1"
VOICE_BASE_URL = "https://api.jive.com/voice-admin/v1"
SCIM_BASE_URL = "https://api.getgo.com/identity/v1"
DEFAULT_ACCOUNT_KEY = "4266846632996939781"
DEFAULT_TENANT_ID = "cloudwarriors"


def get_provider_credentials(tenant_id: str, provider: str):
    provider_data = pm.get_provider(tenant_id, provider)
    if not provider_data:
        raise HTTPException(status_code=404, detail=f"Provider {provider} not found for tenant {tenant_id}")
    
    if provider_data.get('status') != 'active':
        raise HTTPException(status_code=403, detail=f"Provider {provider} is not active")
    
    return provider_data


def get_goto_token(tenant_id: str = DEFAULT_TENANT_ID):
    provider_data = get_provider_credentials(tenant_id, 'goto')
    token = provider_data.get('access_token')
    token_expiry = provider_data.get('token_expiry')
    
    if not token:
        raise HTTPException(status_code=401, detail="No GoTo access token available")
    
    if token_expiry:
        try:
            expiry_dt = datetime.fromisoformat(token_expiry.replace('Z', '+00:00'))
            now_dt = datetime.now(expiry_dt.tzinfo)
            
            if now_dt >= expiry_dt:
                logger.info(f"Token expired, refreshing for tenant {tenant_id}...")
                refresh_result = refresh_goto_token(tenant_id)
                if refresh_result['success']:
                    provider_data = get_provider_credentials(tenant_id, 'goto')
                    token = provider_data.get('access_token')
                else:
                    raise HTTPException(status_code=401, detail="Token refresh failed")
        except Exception as e:
            logger.warning(f"Token expiry check failed: {e}")
    
    return token


def refresh_goto_token(tenant_id: str):
    try:
        provider_data = pm.get_provider(tenant_id, 'goto')
        if not provider_data:
            return {"success": False, "error": "Provider not found"}
        
        token_url = 'https://identity.goto.com/oauth/token'
        token_data = {
            'grant_type': 'refresh_token',
            'refresh_token': provider_data['refresh_token'],
        }
        
        auth_string = base64.b64encode(f"{provider_data['client_id']}:{provider_data['client_secret']}".encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_string}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(token_url, data=token_data, headers=headers)
        
        if response.status_code == 200:
            token_response = response.json()
            access_token = token_response['access_token']
            new_refresh_token = token_response.get('refresh_token', provider_data['refresh_token'])
            expires_in = token_response.get('expires_in', 3600)
            expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat() + 'Z'
            
            pm.update_tokens(tenant_id, 'goto', access_token, new_refresh_token, expires_at)
            
            logger.info(f"Token refreshed successfully for tenant {tenant_id}")
            return {"success": True, "expires_in": expires_in, "expires_at": expires_at}
        else:
            return {"success": False, "error": response.text}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


def exchange_code_for_token(code):
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    redirect_uri = os.getenv('REDIRECT_URI', 'http://localhost:9111')
    
    token_url = "https://identity.goto.com/oauth/token"
    
    token_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri
    }
    
    auth_string = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        'Authorization': f'Basic {auth_string}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        response = requests.post(token_url, data=token_data, headers=headers)
        
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            scope = token_data.get('scope', '')
            
            # Set based on scope
            if 'voice-admin' in scope:
                os.environ['VOICE_ACCESS_TOKEN'] = access_token
                set_key('.env', 'VOICE_ACCESS_TOKEN', access_token)
                if refresh_token:
                    os.environ['VOICE_REFRESH_TOKEN'] = refresh_token
                    set_key('.env', 'VOICE_REFRESH_TOKEN', refresh_token)
            
            if 'identity:scim.org' in scope:
                os.environ['SCIM_ACCESS_TOKEN'] = access_token
                set_key('.env', 'SCIM_ACCESS_TOKEN', access_token)
                if refresh_token:
                    os.environ['SCIM_REFRESH_TOKEN'] = refresh_token
                    set_key('.env', 'SCIM_REFRESH_TOKEN', refresh_token)
            
            # Default to admin if no specific scope
            if not ('voice-admin' in scope or 'identity:scim.org' in scope):
                os.environ['ACCESS_TOKEN'] = access_token
                set_key('.env', 'ACCESS_TOKEN', access_token)
                if refresh_token:
                    os.environ['REFRESH_TOKEN'] = refresh_token
                    set_key('.env', 'REFRESH_TOKEN', refresh_token)
            
            return {
                'success': True,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'scope': scope,
                'expires_in': expires_in
            }
        else:
            return {
                'success': False,
                'error': response.text,
                'status_code': response.status_code
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


class CDPLoginBody(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    verification_code: Optional[str] = None
    scopes: Optional[List[str]] = None
    cdp_url: Optional[str] = "http://127.0.0.1:9222"
    use_cdp: Optional[bool] = False


class ConnectRequest(BaseModel):
    tenant: str = Field(..., min_length=1, max_length=100, description="Tenant identifier")
    app: str = Field(..., min_length=1, max_length=100, description="Application identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tenant": "cloudwarriors",
                "app": "goto-gw"
            }
        }


class ConnectResponseData(BaseModel):
    session_id: str = Field(..., description="UUID of created session")
    tenant: str = Field(..., description="Tenant identifier")
    app: str = Field(..., description="Application identifier")
    expires_in: int = Field(300, description="Session TTL in seconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant": "cloudwarriors",
                "app": "goto-gw",
                "expires_in": 300
            }
        }


class ConnectResponse(BaseModel):
    success: bool = Field(True, description="Operation success flag")
    data: ConnectResponseData
    message: str = Field(..., description="Human-readable result message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tenant": "cloudwarriors",
                    "app": "goto-gw",
                    "expires_in": 300
                },
                "message": "GoTo session created successfully"
            }
        }


class DisconnectResponse(BaseModel):
    success: bool = Field(..., description="Operation success flag")
    message: str = Field(..., description="Human-readable result message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Session disconnected successfully"
            }
        }


class StatusResponseData(BaseModel):
    admin_authenticated: bool = Field(False, description="Admin API authentication status")
    voice_authenticated: bool = Field(False, description="Voice API authentication status")
    scim_authenticated: bool = Field(False, description="SCIM API authentication status")
    tenant: Optional[str] = Field(None, description="Tenant identifier from session")
    app: Optional[str] = Field(None, description="Application identifier from session")
    session_id: Optional[str] = Field(None, description="Session UUID if validated")
    expires_at: Optional[str] = Field(None, description="Session expiry timestamp (ISO 8601)")
    provider_token_expiry: Optional[str] = Field(None, description="Provider token expiry (ISO 8601)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "admin_authenticated": False,
                "voice_authenticated": True,
                "scim_authenticated": False,
                "tenant": "cloudwarriors",
                "app": "goto-gw",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "expires_at": "2025-10-02T18:20:23Z",
                "provider_token_expiry": "2025-10-02T19:00:00Z"
            }
        }


class StatusResponse(BaseModel):
    success: bool = Field(True, description="Operation success flag")
    data: StatusResponseData
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {
                    "admin_authenticated": False,
                    "voice_authenticated": True,
                    "scim_authenticated": False,
                    "tenant": "cloudwarriors",
                    "app": "goto-gw",
                    "expires_at": "2025-10-02T18:20:23Z"
                }
            }
        }


class ErrorResponse(BaseModel):
    success: bool = Field(False, description="Operation success flag")
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "Session not found",
                "detail": "Session 550e8400-e29b-41d4-a716-446655440000 does not exist or has expired"
            }
        }


class SessionHeaders(BaseModel):
    session_id: Optional[str] = None
    tenant: Optional[str] = None
    app: Optional[str] = None
    system_client_id: Optional[str] = None
    system_client_secret: Optional[str] = None
    provider_access_token: Optional[str] = None
    provider_refresh_token: Optional[str] = None
    provider_account_key: Optional[str] = None


async def extract_session_headers(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    x_tenant: Optional[str] = Header(None, alias="X-Tenant"),
    x_app: Optional[str] = Header(None, alias="X-App"),
    x_system_client_id: Optional[str] = Header(None, alias="X-System-Client-ID"),
    x_system_client_secret: Optional[str] = Header(None, alias="X-System-Client-Secret"),
    x_provider_access_token: Optional[str] = Header(None, alias="X-Provider-Access-Token"),
    x_provider_refresh_token: Optional[str] = Header(None, alias="X-Provider-Refresh-Token"),
    x_provider_account_key: Optional[str] = Header(None, alias="X-Provider-Account-Key")
) -> SessionHeaders:
    return SessionHeaders(
        session_id=x_session_id,
        tenant=x_tenant,
        app=x_app,
        system_client_id=x_system_client_id,
        system_client_secret=x_system_client_secret,
        provider_access_token=x_provider_access_token,
        provider_refresh_token=x_provider_refresh_token,
        provider_account_key=x_provider_account_key
    )


# @app.on_event("startup")
# async def startup_event():
#     print("🚀 FastAPI starting — initializing headless browser...")
#     try:
#         from playwright.async_api import async_playwright
#     except Exception as e:
#         print("❌ Playwright not available. Install with: pip install playwright && playwright install chromium")
#         app.state.playwright = None
#         app.state.browser = None
#         return

#     try:
#         app.state.playwright = await async_playwright().start()
#         # Launch a persistent, headless Chromium instance we can reuse
#         app.state.browser = await app.state.playwright.chromium.launch(
#             headless=True,
#             args=[
#                 "--no-sandbox",
#                 "--disable-dev-shm-usage",
#                 "--no-first-run",
#                 "--no-default-browser-check",
#             ],
#         )
#         # Validate browser operation with a quick page navigation
#         ctx = await app.state.browser.new_context()
#         page = await ctx.new_page()
#         try:
#             await page.goto("https://example.com", wait_until="domcontentloaded")
#             title = await page.title()
#             print(f"✅ Headless browser ready. Validation title: {title}")
#         finally:
#             await ctx.close()
#     except Exception as e:
#         print(f"❌ Failed to initialize headless browser: {e}")
#         app.state.browser = None


# @app.on_event("shutdown")
# async def shutdown_event():
#     print("🛑 FastAPI shutting down — closing headless browser...")
#     try:
#         browser = getattr(app.state, "browser", None)
#         if browser:
#             await browser.close()
#         pw = getattr(app.state, "playwright", None)
#         if pw:
#             await pw.stop()
#         print("✅ Browser shutdown complete")
#     except Exception as e:
#         print(f"⚠️ Browser shutdown error: {e}")


@app.get("/")
async def root(code: str = Query(None), state: str = Query(None)):
    if code:
        logger.info(f"Authorization code received: {code[:10]}...")
        result = exchange_code_for_token(code)
        if result.get("success"):
            logger.info("Tokens exchanged and stored successfully")
            return {"message": "Tokens exchanged successfully", "token_info": result}
        else:
            logger.error(f"Token exchange failed: {result.get('error')}")
            return {"message": "Token exchange failed", "error": result.get("error")}
    return {"message": "GoTo API Gateway"}


@app.get("/health", tags=["Health"])
async def health(tenant_id: str = Query(DEFAULT_TENANT_ID)):
    try:
        redis_healthy = False
        try:
            pm.redis_client.ping()
            redis_healthy = True
        except Exception as redis_err:
            logger.error(f"Redis health check failed: {redis_err}")
        
        providers = pm.get_all_providers(tenant_id)
        provider_status = {}
        
        for provider in providers:
            provider_data = pm.get_provider(tenant_id, provider)
            if provider_data:
                provider_status[provider] = {
                    "status": provider_data.get("status"),
                    "has_token": bool(provider_data.get("access_token")),
                    "token_expiry": provider_data.get("token_expiry"),
                }
        
        return {
            "status": "healthy",
            "tenant_id": tenant_id,
            "redis_healthy": redis_healthy,
            "providers": provider_status,
            "account_key": DEFAULT_ACCOUNT_KEY,
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "healthy",
            "tenant_id": tenant_id,
            "redis_healthy": False,
            "providers": {},
            "error": str(e),
        }


@app.post("/auth/connect",
    response_model=ConnectResponse,
    status_code=200,
    responses={
        200: {"description": "Session created successfully"},
        400: {"description": "Invalid request body"},
        404: {"description": "System credentials or provider tokens not found"},
        500: {"description": "Internal server error"}
    },
    tags=["Authentication"]
)
async def auth_connect(body: ConnectRequest):
    """
    Issue a session for tenant/app using pre-seeded credentials in Redis.
    
    Creates a new session with 5-minute TTL bundling system credentials
    and provider tokens for use by the Django API Gateway.
    """
    try:
        system_creds = pm.get_system_credentials(body.tenant, body.app)
        if not system_creds:
            logger.warning(f"System credentials not found: tenant={body.tenant} app={body.app}")
            raise HTTPException(
                status_code=404,
                detail=f"System credentials not found for tenant={body.tenant} app={body.app}"
            )
        
        provider_data = pm.get_provider(body.tenant, 'goto')
        if not provider_data:
            logger.warning(f"Provider 'goto' not found for tenant={body.tenant}")
            raise HTTPException(
                status_code=404,
                detail=f"Provider 'goto' not found for tenant={body.tenant}"
            )
        
        provider_tokens = {
            'access_token': provider_data.get('access_token'),
            'refresh_token': provider_data.get('refresh_token'),
            'token_expiry': provider_data.get('token_expiry'),
            'account_key': provider_data.get('account_key'),
            'api_base_url': provider_data.get('api_base_url', VOICE_BASE_URL)
        }
        
        session_data = sm.create_session(
            tenant=body.tenant,
            app=body.app,
            system_creds=system_creds,
            provider_tokens=provider_tokens
        )
        
        logger.info(f"Session created: {session_data['session_id']} for tenant={body.tenant} app={body.app}")
        
        return ConnectResponse(
            success=True,
            data=ConnectResponseData(
                session_id=session_data['session_id'],
                tenant=body.tenant,
                app=body.app,
                expires_in=300
            ),
            message="GoTo session created successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/auth/disconnect",
    response_model=DisconnectResponse,
    status_code=200,
    responses={
        200: {"description": "Session disconnected successfully"},
        400: {"description": "Missing session_id parameter"},
        404: {"description": "Session not found or already expired"},
        500: {"description": "Internal server error"}
    },
    tags=["Authentication"]
)
async def auth_disconnect(session_id: str = Query(..., description="Session UUID to disconnect")):
    """
    Revoke a session by removing it from Redis.
    
    Once disconnected, the session_id becomes invalid and cannot be used
    for authenticated requests. This is idempotent - calling multiple times
    with the same session_id will return 404 after the first call.
    """
    try:
        deleted = sm.delete_session(session_id)
        
        if deleted:
            logger.info(f"Session disconnected: {session_id}")
            return DisconnectResponse(
                success=True,
                message="Session disconnected successfully"
            )
        else:
            logger.warning(f"Session not found: {session_id}")
            raise HTTPException(
                status_code=404,
                detail=f"Session not found: {session_id}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session disconnect error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/auth/status",
    response_model=StatusResponse,
    status_code=200,
    responses={
        200: {"description": "Authentication status retrieved"},
        401: {"description": "Invalid or expired session"},
        500: {"description": "Internal server error"}
    },
    tags=["Authentication"]
)
async def auth_status(
    session_id: Optional[str] = Query(None, description="Optional session UUID to validate"),
    tenant_id: Optional[str] = Query(None, description="Optional tenant ID for provider status")
):
    """
    Get authentication status for providers and optionally validate a session.
    
    Without session_id: Returns boolean flags for each provider's authentication state.
    With session_id: Validates session and returns augmented data with tenant/app/expiry.
    """
    try:
        if session_id:
            session_data = sm.get_session(session_id)
            
            if not session_data:
                logger.warning(f"Invalid session: {session_id}")
                raise HTTPException(
                    status_code=401,
                    detail=f"Invalid or expired session: {session_id}"
                )
            
            tenant = session_data.get('tenant')
            app = session_data.get('app')
            expires_at = session_data.get('expires_at')
            
            provider_tokens = session_data.get('provider_tokens', {})
            has_access_token = bool(provider_tokens.get('access_token'))
            token_expiry = provider_tokens.get('token_expiry')
            
            logger.info(f"Session validated: {session_id} tenant={tenant} app={app}")
            
            return StatusResponse(
                success=True,
                data=StatusResponseData(
                    admin_authenticated=False,
                    voice_authenticated=has_access_token,
                    scim_authenticated=False,
                    tenant=tenant,
                    app=app,
                    session_id=session_id,
                    expires_at=expires_at,
                    provider_token_expiry=token_expiry
                )
            )
        
        elif tenant_id:
            try:
                provider_data = pm.get_provider(tenant_id, 'goto')
                has_token = bool(provider_data and provider_data.get('access_token'))
                token_expiry = provider_data.get('token_expiry') if provider_data else None
            except:
                has_token = False
                token_expiry = None
            
            return StatusResponse(
                success=True,
                data=StatusResponseData(
                    admin_authenticated=False,
                    voice_authenticated=has_token,
                    scim_authenticated=False,
                    tenant=tenant_id,
                    provider_token_expiry=token_expiry
                )
            )
        
        else:
            return StatusResponse(
                success=True,
                data=StatusResponseData(
                    admin_authenticated=bool(os.getenv("ACCESS_TOKEN")),
                    voice_authenticated=bool(os.getenv("VOICE_ACCESS_TOKEN")),
                    scim_authenticated=bool(os.getenv("SCIM_ACCESS_TOKEN"))
                )
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# @app.post("/auth/cdp-login")
# async def cdp_login(body: CDPLoginBody):
#     """Automated OAuth using a persistent, headless browser started at app init.
#     - If the managed headless browser isn't available, falls back to CDP at cdp_url.
#     - If MFA is detected and no verification_code is supplied, returns mfa_required.
#     - If verification_code is supplied, attempts to submit it and continue.
#     Returns token exchange result from auth_manager.
#     """
#     username = body.username or os.getenv("LOGIN_EMAIL")
#     password = body.password or os.getenv("LOGIN_PASSWORD")
#     scopes = body.scopes
#     cdp_url = body.cdp_url or "http://127.0.0.1:9222"
#     verification_code = body.verification_code

#     if not username or not password:
#     raise HTTPException(status_code=400, detail="Username and password are required or must be set in .env")

#     oauth_url = auth_manager.get_oauth_url(scopes)

#     async def run_with_managed_browser() -> dict:
#         browser = getattr(app.state, "browser", None)
#         if not browser:
#             return {"success": False, "error": "Managed browser not available"}
#         context = await browser.new_context()
#         page = await context.new_page()
#         try:
#             await page.goto(oauth_url)
#             # Email
#             try:
#                 await page.fill('input[name="username"], input[type="email"], #username', username)
#                 await page.press('input[name="username"], input[type="email"], #username', 'Enter')
#                 await page.wait_for_load_state('networkidle')
#             except Exception:
#                 pass
#             # Password
#             try:
#                 await page.fill('input[type="password"]', password)
#                 await page.press('input[type="password"]', 'Enter')
#                 await page.wait_for_load_state('networkidle')
#             except Exception:
#                 pass
#             # Detect MFA
#             await page.wait_for_timeout(1500)
#             mfa_selectors = [
#                 'input[name="verificationCode"]',
#                 'input[placeholder*="verification" i]',
#                 'input[placeholder*="code" i]',
#                 'input[type="text"][maxlength="6"]',
#                 'input[type="number"][maxlength="6"]',
#                 'input[autocomplete="one-time-code"]',
#             ]
#             mfa_present = False
#             for sel in mfa_selectors:
#                 try:
#                     el = await page.query_selector(sel)
#                     if el and await el.is_visible():
#                         mfa_present = True
#                         break
#                 except Exception:
#                     continue
#             if mfa_present and not verification_code:
#                 return {"success": False, "mfa_required": True, "message": "MFA required. Provide verification_code."}
#             if mfa_present and verification_code:
#                 for sel in mfa_selectors:
#                     try:
#                         el = await page.query_selector(sel)
#                         if el and await el.is_visible():
#                             await el.fill(verification_code)
#                             try:
#                                 await page.press(sel, 'Enter')
#                             except Exception:
#                                 pass
#                             break
#                     except Exception:
#                         continue
#                 await page.wait_for_load_state('networkidle')
#             # Redirect & code
#             await page.wait_for_url(lambda u: 'localhost:9111' in u, timeout=30000)
#             final_url = page.url
#             if 'code=' in final_url:
#                 return {"success": True, "auth_code": final_url.split('code=')[1].split('&')[0]}
#             return {"success": False, "error": "No authorization code in redirect URL", "final_url": final_url}
#         finally:
#             try:
#                 await context.close()
#             except Exception:
#                 pass

#     async def run_with_cdp() -> dict:
#         from playwright.async_api import async_playwright
#         async with async_playwright() as p:
#             browser = await p.chromium.connect_over_cdp(cdp_url)
#             context = await browser.new_context()
#             page = await context.new_page()
#             try:
#                 await page.goto(oauth_url)
#                 # Email
#                 try:
#                     await page.fill('input[name="username"], input[type="email"], #username', username)
#                     await page.press('input[name="username"], input[type="email"], #username', 'Enter')
#                     await page.wait_for_load_state('networkidle')
#                 except Exception:
#                     pass
#                 # Password
#                 try:
#                     await page.fill('input[type="password"]', password)
#                     await page.press('input[type="password"]', 'Enter')
#                     await page.wait_for_load_state('networkidle')
#                 except Exception:
#                     pass
#                 # Detect MFA
#                 await page.wait_for_timeout(1500)
#                 mfa_selectors = [
#                 'input[name="verificationCode"]',
#                 'input[placeholder*="verification" i]',
#                 'input[placeholder*="code" i]',
#                 'input[type="text"][maxlength="6"]',
#                 'input[type="number"][maxlength="6"]',
#                 'input[autocomplete="one-time-code"]',
#             ]
#             mfa_present = False
#             for sel in mfa_selectors:
#                 try:
#                     el = await page.query_selector(sel)
#                     if el and await el.is_visible():
#                         mfa_present = True
#                         break
#                 except Exception:
#                     continue
#             if mfa_present and not verification_code:
#                 return {"success": False, "mfa_required": True, "message": "MFA required. Provide verification_code."}
#             if mfa_present and verification_code:
#                 for sel in mfa_selectors:
#                     try:
#                         el = await page.query_selector(sel)
#                         if el and await el.is_visible():
#                             await el.fill(verification_code)
#                             try:
#                                 await page.press(sel, 'Enter')
#                             except Exception:
#                                 pass
#                             break
#                     except Exception:
#                         continue
#                 await page.wait_for_load_state('networkidle')
#             await page.wait_for_url(lambda u: 'localhost:9111' in u, timeout=30000)
#             final_url = page.url
#             if 'code=' in final_url:
#                 return {"success": True, "auth_code": final_url.split('code=')[1].split('&')[0]}
#             return {"success": False, "error": "No authorization code in redirect URL", "final_url": final_url}
#         finally:
#             try:
#                 await context.close()
#             except Exception:
#                 pass

#     # Prefer managed headless browser; allow forcing CDP; fall back to CDP when missing
#     if body.use_cdp:
#         print("ℹ️ Forcing CDP path for authentication")
#         auth_result = await run_with_cdp()
#     elif getattr(app.state, "browser", None) is not None:
#         auth_result = await run_with_managed_browser()
#     else:
#         print("ℹ️ Managed browser unavailable — falling back to CDP endpoint")
#         auth_result = await run_with_cdp()

#     if auth_result.get("mfa_required"):
#         return auth_result
#     if not auth_result.get("success"):
#         raise HTTPException(status_code=400, detail=auth_result.get("error", "Authentication failed"))

#     token_result = auth_manager.exchange_code_for_token(auth_result["auth_code"])
#     return token_result


@app.get("/call-queues")
async def list_call_queues(
    accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY),
    tenant_id: str = Query(DEFAULT_TENANT_ID)
):
    token = get_goto_token(tenant_id)
    provider_data = get_provider_credentials(tenant_id, 'goto')

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": provider_data.get('account_key', accountKey)}
    url = f"{provider_data.get('api_base_url', VOICE_BASE_URL)}/call-queues"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail=r.text)
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/me")
async def get_me():
    token = os.getenv("ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid token available")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"{ADMIN_BASE_URL}/me"
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail=r.text)
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===============================
# Voice Auto Attendants Endpoints
# ===============================

@app.get("/autoattendants")
async def list_auto_attendants(accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY)):
    token = os.getenv("VOICE_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid voice token available")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": accountKey}
    url = f"{VOICE_BASE_URL}/extensions"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            data = r.json()
            # Infer auto attendants as extensions with type "DIAL_PLAN"
            auto_attendants = [ext for ext in data.get("items", []) if ext.get("type") == "DIAL_PLAN"]
            return {"items": auto_attendants}
        return JSONResponse(content=(r.json() if r.text else {}), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/autoattendants/{attendant_id}")
async def get_auto_attendant(attendant_id: str, accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY)):
    token = os.getenv("VOICE_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid voice token available")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": accountKey}
    url = f"{VOICE_BASE_URL}/extensions"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            data = r.json()
            # Find the extension with matching id and type DIAL_PLAN
            for ext in data.get("items", []):
                if ext.get("id") == attendant_id and ext.get("type") == "DIAL_PLAN":
                    return ext
            return JSONResponse(content={"error": "Auto attendant not found"}, status_code=404)
        return JSONResponse(content=(r.json() if r.text else {}), status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/autoattendants")
async def create_auto_attendant(request: Request, accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY)):
    token = os.getenv("VOICE_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid voice token available")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": accountKey}
    body = None
    try:
        body = await request.json()
    except Exception:
        body = {}
    url = f"{VOICE_BASE_URL}/autoattendants"
    try:
        r = requests.post(url, headers=headers, params=params, json=body, timeout=60)
        content = None
        try:
            content = r.json()
        except Exception:
            content = r.text
        return JSONResponse(content=content, status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/autoattendants/{attendant_id}")
async def update_auto_attendant(attendant_id: str, request: Request, accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY)):
    token = os.getenv("VOICE_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid voice token available")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": accountKey}
    body = None
    try:
        body = await request.json()
    except Exception:
        body = {}
    url = f"{VOICE_BASE_URL}/autoattendants/{attendant_id}"
    try:
        r = requests.put(url, headers=headers, params=params, json=body, timeout=60)
        content = None
        try:
            content = r.json()
        except Exception:
            content = r.text
        return JSONResponse(content=content, status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/autoattendants/{attendant_id}")
async def delete_auto_attendant(attendant_id: str, accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY)):
    token = os.getenv("VOICE_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid voice token available")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": accountKey}
    url = f"{VOICE_BASE_URL}/autoattendants/{attendant_id}"
    try:
        r = requests.delete(url, headers=headers, params=params, timeout=30)
        content = None
        try:
            content = r.json()
        except Exception:
            content = r.text
        return JSONResponse(content=content, status_code=r.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===============================
# Generic Proxy Endpoints
# ===============================

@app.api_route("/admin-proxy/{api_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def admin_proxy(api_path: str, request: Request):
    token = os.getenv("ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="No valid admin token available")

    url = f"{ADMIN_BASE_URL}/{api_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = dict(request.query_params)

    data = None
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            data = await request.json()
        except Exception:
            data = None

    try:
        resp = requests.request(request.method, url, headers=headers, params=params, json=data, timeout=60)
        content = None
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(content=content, status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/voice-proxy/{api_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def voice_proxy(api_path: str, request: Request, tenant_id: str = Query(DEFAULT_TENANT_ID)):
    """
    Proxy endpoint for GoTo Voice Admin API.
    
    Common endpoints:
    - extensions: List all extensions/users (filter by type: DIRECT_EXTENSION, CALL_QUEUE, DIAL_PLAN)
    - accounts/{account_key}: Get account details
    - lines: List phone lines
    - call-queues: List call queues
    
    Example: GET /voice-proxy/extensions?session_id=xxx
    """
    token = get_goto_token(tenant_id)
    provider_data = get_provider_credentials(tenant_id, 'goto')

    url = f"{provider_data.get('api_base_url', VOICE_BASE_URL)}/{api_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = dict(request.query_params)
    if "tenant_id" in params:
        del params["tenant_id"]
    if "accountKey" not in params:
        params["accountKey"] = provider_data.get('account_key', DEFAULT_ACCOUNT_KEY)

    data = None
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            data = await request.json()
        except Exception:
            data = None

    try:
        resp = requests.request(request.method, url, headers=headers, params=params, json=data, timeout=60)
        content = None
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(content=content, status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/scim-proxy/{api_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def scim_proxy(api_path: str, request: Request):
    token = os.getenv("SCIM_ACCESS_TOKEN")  # SCIM uses token with identity:scim.org scope
    if not token:
        raise HTTPException(status_code=401, detail="No valid SCIM token available")

    url = f"{SCIM_BASE_URL}/{api_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = dict(request.query_params)

    data = None
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            data = await request.json()
        except Exception:
            data = None

    try:
        resp = requests.request(request.method, url, headers=headers, params=params, json=data, timeout=60)
        content = None
        try:
            content = resp.json()
        except Exception:
            content = resp.text
        return JSONResponse(content=content, status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tenants/{tenant_id}/providers")
async def list_tenant_providers(tenant_id: str):
    try:
        providers = pm.get_all_providers(tenant_id)
        provider_list = []
        
        for provider in providers:
            provider_data = pm.get_provider(tenant_id, provider)
            if provider_data:
                provider_list.append({
                    "provider": provider,
                    "status": provider_data.get("status"),
                    "auth_type": provider_data.get("auth_type"),
                    "account_key": provider_data.get("account_key"),
                    "has_token": bool(provider_data.get("access_token")),
                    "token_expiry": provider_data.get("token_expiry"),
                    "features_enabled": provider_data.get("features_enabled"),
                    "created_at": provider_data.get("created_at"),
                    "updated_at": provider_data.get("updated_at"),
                })
        
        return {"tenant_id": tenant_id, "providers": provider_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tenants/{tenant_id}/providers/{provider}")
async def get_tenant_provider(tenant_id: str, provider: str):
    try:
        provider_data = pm.get_provider(tenant_id, provider)
        if not provider_data:
            raise HTTPException(status_code=404, detail=f"Provider {provider} not found for tenant {tenant_id}")
        
        provider_data.pop("client_secret", None)
        provider_data.pop("access_token", None)
        provider_data.pop("refresh_token", None)
        
        return {"tenant_id": tenant_id, "provider": provider, "config": provider_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tenants/{tenant_id}/config")
async def get_tenant_config(tenant_id: str):
    try:
        config = pm.get_tenant_config(tenant_id)
        if not config:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        
        return {"tenant_id": tenant_id, "config": config}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tenants/{tenant_id}/providers/{provider}/refresh-token")
async def refresh_provider_token(tenant_id: str, provider: str):
    try:
        if provider != 'goto':
            raise HTTPException(status_code=400, detail=f"Token refresh not implemented for provider: {provider}")
        
        result = refresh_goto_token(tenant_id)
        
        if result['success']:
            return {
                "success": True,
                "message": "Token refreshed successfully",
                "expires_in": result.get('expires_in'),
                "expires_at": result.get('expires_at')
            }
        else:
            raise HTTPException(status_code=500, detail=f"Token refresh failed: {result.get('error')}")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("🟢 Starting GoTo API Gateway (FastAPI) v2.0 on http://localhost:8078")
    uvicorn.run("app:app", host="0.0.0.0", port=8078, reload=True)
