#!/usr/bin/env python3

import requests
import base64
import os
import time
import urllib.parse
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv, set_key

# Playwright imports for automation
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️  Playwright not available. Install with: pip install playwright")

load_dotenv()

def get_token_expiry(token):
    """Extract expiry datetime from JWT token"""
    if not token:
        return None
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)  # pad for base64
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded.decode('utf-8'))
        exp = data.get('exp')
        if exp:
            return datetime.fromtimestamp(exp)
    except Exception:
        pass
    return None

class GoToAuthManager:
    """Centralized authentication manager for GoTo APIs with Playwright automation"""
    
    def __init__(self):
        self.client_id = os.getenv('CLIENT_ID')
        self.client_secret = os.getenv('CLIENT_SECRET')
        self.redirect_uri = os.getenv('REDIRECT_URI', 'http://localhost:9111')
        self.login_email = os.getenv('LOGIN_EMAIL')
        self.login_password = os.getenv('LOGIN_PASSWORD')
        
        # Current tokens
        self.admin_access_token = os.getenv('ACCESS_TOKEN')
        self.admin_refresh_token = os.getenv('REFRESH_TOKEN')
        self.voice_access_token = os.getenv('VOICE_ACCESS_TOKEN')
        self.voice_refresh_token = os.getenv('VOICE_REFRESH_TOKEN')
        self.scim_access_token = os.getenv('SCIM_ACCESS_TOKEN')
        self.scim_refresh_token = os.getenv('SCIM_REFRESH_TOKEN')

        # Token expiry tracking - parse from tokens
        self.admin_token_expiry = get_token_expiry(self.admin_access_token)
        self.voice_token_expiry = get_token_expiry(self.voice_access_token)
        self.scim_token_expiry = get_token_expiry(self.scim_access_token)
    
    def get_oauth_url(self, scopes=None):
        """Generate OAuth authorization URL"""
        if not self.client_id:
            raise ValueError("CLIENT_ID not configured")
        
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'state': 'goto_oauth_state_123'
        }
        
        if scopes:
            if isinstance(scopes, list):
                scopes = ' '.join(scopes)
            params['scope'] = scopes
        
        # Build URL with proper encoding
        base_url = "https://authentication.logmeininc.com/oauth/authorize"
        query_parts = [
            f"client_id={params['client_id']}",
            f"redirect_uri=http%3A%2F%2Flocalhost%3A9111",  # Properly encoded
            f"response_type={params['response_type']}",
            f"state={params['state']}"
        ]
        
        if 'scope' in params:
            query_parts.append(f"scope={urllib.parse.quote(params['scope'])}")
        
        return f"{base_url}?{'&'.join(query_parts)}"
    
    def exchange_code_for_token(self, auth_code):
        """Exchange authorization code for access token"""
        if not self.client_id or not self.client_secret:
            raise ValueError("OAuth client credentials not configured")
        
        token_url = "https://identity.goto.com/oauth/token"
        
        token_data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': self.redirect_uri  # Use correct format
        }
        
        # Use Basic Auth for client credentials
        auth_string = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
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
                
                # Determine token type based on scope
                if 'voice-admin' in scope:
                    self.voice_access_token = access_token
                    self.voice_refresh_token = refresh_token
                    self.voice_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    # Update environment variables in running process
                    os.environ['VOICE_ACCESS_TOKEN'] = access_token
                    if refresh_token:
                        os.environ['VOICE_REFRESH_TOKEN'] = refresh_token
                elif 'identity:scim.org' in scope:
                    self.scim_access_token = access_token
                    self.scim_refresh_token = refresh_token
                    self.scim_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    # Update environment variables in running process
                    os.environ['SCIM_ACCESS_TOKEN'] = access_token
                    if refresh_token:
                        os.environ['SCIM_REFRESH_TOKEN'] = refresh_token
                else:
                    self.admin_access_token = access_token
                    self.admin_refresh_token = refresh_token
                    self.admin_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    # Update environment variables in running process  
                    os.environ['ACCESS_TOKEN'] = access_token
                    if refresh_token:
                        os.environ['REFRESH_TOKEN'] = refresh_token
                
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
    
    def refresh_token(self, token_type='admin'):
        """Refresh access token using refresh token"""
        if token_type == 'admin':
            refresh_token = self.admin_refresh_token
        elif token_type == 'voice':
            refresh_token = self.voice_refresh_token
        else:  # scim
            refresh_token = self.scim_refresh_token
        
        if not refresh_token:
            return {'success': False, 'error': 'No refresh token available'}
        
        token_url = "https://identity.goto.com/oauth/token"
        
        token_data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }
        
        auth_string = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_string}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        try:
            response = requests.post(token_url, data=token_data, headers=headers)
            
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get('access_token')
                new_refresh_token = token_data.get('refresh_token')
                expires_in = token_data.get('expires_in', 3600)
                
                if token_type == 'admin':
                    self.admin_access_token = access_token
                    if new_refresh_token:
                        self.admin_refresh_token = new_refresh_token
                    self.admin_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    set_key('.env', 'ACCESS_TOKEN', access_token)
                    if new_refresh_token:
                        set_key('.env', 'REFRESH_TOKEN', new_refresh_token)
                elif token_type == 'voice':
                    self.voice_access_token = access_token
                    if new_refresh_token:
                        self.voice_refresh_token = new_refresh_token
                    self.voice_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    set_key('.env', 'VOICE_ACCESS_TOKEN', access_token)
                    if new_refresh_token:
                        set_key('.env', 'VOICE_REFRESH_TOKEN', new_refresh_token)
                else:  # scim
                    self.scim_access_token = access_token
                    if new_refresh_token:
                        self.scim_refresh_token = new_refresh_token
                    self.scim_token_expiry = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    set_key('.env', 'SCIM_ACCESS_TOKEN', access_token)
                    if new_refresh_token:
                        set_key('.env', 'SCIM_REFRESH_TOKEN', new_refresh_token)
                
                return {
                    'success': True,
                    'access_token': access_token,
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
    
    def get_valid_token(self, token_type='admin'):
        """Get a valid access token, refreshing if necessary"""
        if token_type == 'admin':
            current_token = self.admin_access_token
            expiry = self.admin_token_expiry
        elif token_type == 'voice':
            current_token = self.voice_access_token
            expiry = self.voice_token_expiry
        else:  # scim
            current_token = self.scim_access_token
            expiry = self.scim_token_expiry
        
        # Check if token needs refresh
        if not current_token or (expiry and datetime.now() >= expiry):
            print(f"🔄 Refreshing {token_type} token...")
            result = self.refresh_token(token_type)
            if result['success']:
                return result['access_token']
            else:
                print(f"❌ Token refresh failed: {result['error']}")
                return None
        
        return current_token
    
    def automated_oauth_flow(self, scopes=None, headless=True):
        """Complete automated OAuth flow using Playwright"""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright not available. Install with: pip install playwright")
        
        if not self.login_email or not self.login_password:
            raise ValueError("LOGIN_EMAIL and LOGIN_PASSWORD must be configured in .env")
        
        print(f"🚀 Starting automated OAuth flow...")
        print(f"📧 Email: {self.login_email}")
        print(f"🔐 Scopes: {scopes or 'default'}")
        
        oauth_url = self.get_oauth_url(scopes)
        print(f"🔗 OAuth URL: {oauth_url}")
        
        with sync_playwright() as p:
            # Launch browser
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            
            try:
                # Navigate to OAuth URL
                print(f"🌐 Navigating to: {oauth_url}")
                page.goto(oauth_url)
                page.wait_for_load_state('networkidle')
                
                # Debug: Check what page we actually landed on
                current_url = page.url
                page_title = page.title()
                print(f"🔍 Current URL: {current_url}")
                print(f"📄 Page title: {page_title}")
                print(f"📝 Page content preview: {page.content()[:200]}...")
                
                # Check if we're already on the consent page
                if 'oauth/approve' in page.url:
                    print("✅ Already authenticated, on consent page")
                else:
                    # Fill email
                    print("📧 Entering email...")
                    print(f"🔍 Looking for email input field...")
                    page.fill('input[name="username"], input[type="email"], input[placeholder*="email" i]', self.login_email)
                    page.click('button:has-text("Next"), input[type="submit"], button[type="submit"]')
                    page.wait_for_load_state('networkidle')
                    
                    # Fill password
                    print("🔑 Entering password...")
                    page.fill('input[name="password"], input[type="password"]', self.login_password)
                    page.click('button:has-text("Sign in"), input[type="submit"], button[type="submit"]')
                    page.wait_for_load_state('networkidle')
                    
                    # Handle MFA if required
                    if 'Multi-factor authentication' in page.content():
                        print("🔐 MFA required - please enter code manually or update script")
                        # You could add MFA automation here if needed
                        page.wait_for_url(lambda url: 'oauth/approve' in url, timeout=60000)
                
                # Handle consent page
                if 'oauth/approve' in page.url:
                    print("✅ On consent page, clicking Allow...")
                    page.click('button:has-text("Allow")')
                    
                    # Wait for redirect to localhost
                    page.wait_for_url(lambda url: 'localhost:9111' in url, timeout=30000)
                    
                    # Extract authorization code from URL
                    current_url = page.url
                    if 'code=' in current_url:
                        auth_code = current_url.split('code=')[1].split('&')[0]
                        print(f"✅ Authorization code obtained: {auth_code[:20]}...")
                        
                        # Exchange code for token
                        result = self.exchange_code_for_token(auth_code)
                        
                        if result['success']:
                            print(f"✅ Token exchange successful!")
                            print(f"   Scope: {result['scope']}")
                            print(f"   Expires in: {result['expires_in']} seconds")
                            return result
                        else:
                            print(f"❌ Token exchange failed: {result['error']}")
                            return result
                    else:
                        return {
                            'success': False,
                            'error': 'No authorization code found in redirect URL'
                        }
                else:
                    return {
                        'success': False,
                        'error': 'Did not reach consent page'
                    }
                    
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Browser automation failed: {str(e)}'
                }
            finally:
                browser.close()
    
    def ensure_authentication(self, require_voice=False):
        """Ensure we have valid authentication for required APIs"""
        needs_auth = []
        
        # Check admin token
        admin_token = self.get_valid_token('admin')
        if not admin_token:
            needs_auth.append('admin')
        
        # Check voice token if required
        if require_voice:
            voice_token = self.get_valid_token('voice')
            if not voice_token:
                needs_auth.append('voice')
        
        if needs_auth:
            print(f"🔐 Authentication required for: {', '.join(needs_auth)}")
            
            # Try to get admin token first (no scope)
            if 'admin' in needs_auth:
                print("🔄 Getting admin authentication...")
                result = self.automated_oauth_flow()
                if not result['success']:
                    return result
            
            # Get voice token if needed
            if 'voice' in needs_auth:
                print("🔄 Getting voice admin authentication...")
                result = self.automated_oauth_flow(scopes=['voice-admin.v1.read'])
                if not result['success']:
                    return result
        
        return {'success': True, 'message': 'Authentication complete'}

# Global auth manager instance
auth_manager = GoToAuthManager()

def get_auth_manager():
    """Get the global auth manager instance"""
    return auth_manager