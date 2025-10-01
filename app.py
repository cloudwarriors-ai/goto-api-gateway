#!/usr/bin/env python3

import os
from typing import Optional, List

import requests
from dotenv import load_dotenv, set_key
import base64
import json
from datetime import datetime, timedelta

load_dotenv()
from fastapi import FastAPI, HTTPException, Query, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from provider_manager import get_provider_manager

app = FastAPI(title="GoTo API Gateway (FastAPI)", version="2.0.0")
pm = get_provider_manager()

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
                print(f"🔄 Token expired, refreshing for tenant {tenant_id}...")
                refresh_result = refresh_goto_token(tenant_id)
                if refresh_result['success']:
                    provider_data = get_provider_credentials(tenant_id, 'goto')
                    token = provider_data.get('access_token')
                else:
                    raise HTTPException(status_code=401, detail="Token refresh failed")
        except Exception as e:
            print(f"⚠️  Token expiry check failed: {e}")
    
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
            
            print(f"✅ Token refreshed successfully for tenant {tenant_id}")
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
    cdp_url: Optional[str] = "http://127.0.0.1:9222"  # Fallback if no managed browser
    use_cdp: Optional[bool] = False  # Force CDP even if managed browser exists


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
        print(f"✅ Authorization code received: {code}")
        # Exchange code for tokens
        result = exchange_code_for_token(code)
        if result.get("success"):
            print("✅ Tokens exchanged and stored successfully")
            return {"message": "Tokens exchanged successfully", "token_info": result}
        else:
            print(f"❌ Token exchange failed: {result.get('error')}")
            return {"message": "Token exchange failed", "error": result.get("error")}
    return {"message": "GoTo API Gateway"}


@app.get("/health")
async def health(tenant_id: str = Query(DEFAULT_TENANT_ID)):
    try:
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
            "providers": provider_status,
            "account_key": DEFAULT_ACCOUNT_KEY,
        }
    except Exception as e:
        return {
            "status": "healthy",
            "tenant_id": tenant_id,
            "providers": {},
            "error": str(e),
        }


@app.get("/auth/status")
async def auth_status():
    return {
        "admin_authenticated": bool(os.getenv("ACCESS_TOKEN")),
        "voice_authenticated": bool(os.getenv("VOICE_ACCESS_TOKEN")),
        "scim_authenticated": bool(os.getenv("SCIM_ACCESS_TOKEN")),
        "admin_expires": None,
        "voice_expires": None,
        "scim_expires": None,
    }


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
