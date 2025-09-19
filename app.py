#!/usr/bin/env python3

import os
from typing import Optional, List

import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from auth_manager import get_auth_manager

app = FastAPI(title="GoTo API Gateway (FastAPI)", version="1.1.0")
auth_manager = get_auth_manager()

ADMIN_BASE_URL = "https://api.getgo.com/admin/rest/v1"
VOICE_BASE_URL = "https://api.jive.com/voice-admin/v1"
DEFAULT_ACCOUNT_KEY = "4266846632996939781"


class CDPLoginBody(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    verification_code: Optional[str] = None
    scopes: Optional[List[str]] = None
    cdp_url: Optional[str] = "http://127.0.0.1:9222"  # Fallback if no managed browser


@app.on_event("startup")
async def startup_event():
    print("🚀 FastAPI starting — initializing headless browser...")
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        print("❌ Playwright not available. Install with: pip install playwright && playwright install chromium")
        app.state.playwright = None
        app.state.browser = None
        return

    try:
        app.state.playwright = await async_playwright().start()
        # Launch a persistent, headless Chromium instance we can reuse
        app.state.browser = await app.state.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        # Validate browser operation with a quick page navigation
        ctx = await app.state.browser.new_context()
        page = await ctx.new_page()
        try:
            await page.goto("https://example.com", wait_until="domcontentloaded")
            title = await page.title()
            print(f"✅ Headless browser ready. Validation title: {title}")
        finally:
            await ctx.close()
    except Exception as e:
        print(f"❌ Failed to initialize headless browser: {e}")
        app.state.browser = None


@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 FastAPI shutting down — closing headless browser...")
    try:
        browser = getattr(app.state, "browser", None)
        if browser:
            await browser.close()
        pw = getattr(app.state, "playwright", None)
        if pw:
            await pw.stop()
        print("✅ Browser shutdown complete")
    except Exception as e:
        print(f"⚠️ Browser shutdown error: {e}")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "admin_token_available": bool(auth_manager.admin_access_token),
        "voice_token_available": bool(auth_manager.voice_access_token),
        "headless_browser": bool(getattr(app.state, "browser", None) is not None),
        "account_key": DEFAULT_ACCOUNT_KEY,
    }


@app.get("/auth/status")
async def auth_status():
    admin_token = auth_manager.get_valid_token("admin")
    voice_token = auth_manager.get_valid_token("voice")
    return {
        "admin_authenticated": bool(admin_token),
        "voice_authenticated": bool(voice_token),
        "admin_expires": auth_manager.admin_token_expiry.isoformat() if auth_manager.admin_token_expiry else None,
        "voice_expires": auth_manager.voice_token_expiry.isoformat() if auth_manager.voice_token_expiry else None,
    }


@app.post("/auth/cdp-login")
async def cdp_login(body: CDPLoginBody):
    """Automated OAuth using a persistent, headless browser started at app init.
    - If the managed headless browser isn't available, falls back to CDP at cdp_url.
    - If MFA is detected and no verification_code is supplied, returns mfa_required.
    - If verification_code is supplied, attempts to submit it and continue.
    Returns token exchange result from auth_manager.
    """
    username = body.username or os.getenv("LOGIN_EMAIL")
    password = body.password or os.getenv("LOGIN_PASSWORD")
    scopes = body.scopes
    cdp_url = body.cdp_url or "http://127.0.0.1:9222"
    verification_code = body.verification_code

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required or must be set in .env")

    oauth_url = auth_manager.get_oauth_url(scopes)

    async def run_with_managed_browser() -> dict:
        browser = getattr(app.state, "browser", None)
        if not browser:
            return {"success": False, "error": "Managed browser not available"}
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(oauth_url)
            # Email
            try:
                await page.fill('input[name="username"], input[type="email"], #username', username)
                await page.press('input[name="username"], input[type="email"], #username', 'Enter')
                await page.wait_for_load_state('networkidle')
            except Exception:
                pass
            # Password
            try:
                await page.fill('input[type="password"]', password)
                await page.press('input[type="password"]', 'Enter')
                await page.wait_for_load_state('networkidle')
            except Exception:
                pass
            # Detect MFA
            await page.wait_for_timeout(1500)
            mfa_selectors = [
                'input[name="verificationCode"]',
                'input[placeholder*="verification" i]',
                'input[placeholder*="code" i]',
                'input[type="text"][maxlength="6"]',
                'input[type="number"][maxlength="6"]',
                'input[autocomplete="one-time-code"]',
            ]
            mfa_present = False
            for sel in mfa_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        mfa_present = True
                        break
                except Exception:
                    continue
            if mfa_present and not verification_code:
                return {"success": False, "mfa_required": True, "message": "MFA required. Provide verification_code."}
            if mfa_present and verification_code:
                for sel in mfa_selectors:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            await el.fill(verification_code)
                            try:
                                await page.press(sel, 'Enter')
                            except Exception:
                                pass
                            break
                    except Exception:
                        continue
                await page.wait_for_load_state('networkidle')
            # Redirect & code
            await page.wait_for_url(lambda u: 'localhost:9111' in u, timeout=30000)
            final_url = page.url
            if 'code=' in final_url:
                return {"success": True, "auth_code": final_url.split('code=')[1].split('&')[0]}
            return {"success": False, "error": "No authorization code in redirect URL", "final_url": final_url}
        finally:
            try:
                await context.close()
            except Exception:
                pass

    async def run_with_cdp() -> dict:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(oauth_url)
                # Email
                try:
                    await page.fill('input[name="username"], input[type="email"], #username', username)
                    await page.press('input[name="username"], input[type="email"], #username', 'Enter')
                    await page.wait_for_load_state('networkidle')
                except Exception:
                    pass
                # Password
                try:
                    await page.fill('input[type="password"]', password)
                    await page.press('input[type="password"]', 'Enter')
                    await page.wait_for_load_state('networkidle')
                except Exception:
                    pass
                # Detect MFA
                await page.wait_for_timeout(1500)
                mfa_selectors = [
                    'input[name="verificationCode"]',
                    'input[placeholder*="verification" i]',
                    'input[placeholder*="code" i]',
                    'input[type="text"][maxlength="6"]',
                    'input[type="number"][maxlength="6"]',
                    'input[autocomplete="one-time-code"]',
                ]
                mfa_present = False
                for sel in mfa_selectors:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            mfa_present = True
                            break
                    except Exception:
                        continue
                if mfa_present and not verification_code:
                    return {"success": False, "mfa_required": True, "message": "MFA required. Provide verification_code."}
                if mfa_present and verification_code:
                    for sel in mfa_selectors:
                        try:
                            el = await page.query_selector(sel)
                            if el and await el.is_visible():
                                await el.fill(verification_code)
                                try:
                                    await page.press(sel, 'Enter')
                                except Exception:
                                    pass
                                break
                        except Exception:
                            continue
                    await page.wait_for_load_state('networkidle')
                await page.wait_for_url(lambda u: 'localhost:9111' in u, timeout=30000)
                final_url = page.url
                if 'code=' in final_url:
                    return {"success": True, "auth_code": final_url.split('code=')[1].split('&')[0]}
                return {"success": False, "error": "No authorization code in redirect URL", "final_url": final_url}
            finally:
                try:
                    await context.close()
                except Exception:
                    pass

    # Prefer managed headless browser; fall back to CDP endpoint
    if getattr(app.state, "browser", None) is not None:
        auth_result = await run_with_managed_browser()
    else:
        print("ℹ️ Managed browser unavailable — falling back to CDP endpoint")
        auth_result = await run_with_cdp()

    if auth_result.get("mfa_required"):
        return auth_result
    if not auth_result.get("success"):
        raise HTTPException(status_code=400, detail=auth_result.get("error", "Authentication failed"))

    token_result = auth_manager.exchange_code_for_token(auth_result["auth_code"])
    return token_result


@app.get("/call-queues")
async def list_call_queues(accountKey: Optional[str] = Query(DEFAULT_ACCOUNT_KEY)):
    token = auth_manager.get_valid_token("voice") or auth_manager.get_valid_token("admin")
    if not token:
        raise HTTPException(status_code=401, detail="No valid token available")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    params = {"accountKey": accountKey}
    url = f"{VOICE_BASE_URL}/call-queues"
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
    token = auth_manager.get_valid_token("admin")
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


if __name__ == "__main__":
    import uvicorn
    print("🟢 Starting GoTo API Gateway (FastAPI) on http://localhost:8000")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
