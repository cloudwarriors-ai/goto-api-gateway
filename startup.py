#!/usr/bin/env python3

import os
import sys
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
print("✅ Environment variables loaded from .env")

# Initialize auth manager
from auth_manager import get_auth_manager
auth_manager = get_auth_manager()
print("✅ Auth manager initialized")

# Check for required environment variables
required_vars = ['CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI']
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    print("Please create a .env file based on .env-template with your credentials")
    sys.exit(1)

# Start FastAPI server
if __name__ == "__main__":
    print("🚀 Starting GoTo API Gateway (FastAPI) on http://0.0.0.0:6655")
    uvicorn.run("app:app", host="0.0.0.0", port=6655, reload=True)