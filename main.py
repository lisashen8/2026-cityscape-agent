"""
Application entry point that initializes and configures the FastAPI web server using Google ADK.
Exposes the agent endpoints, session management, and optional web interface or A2A communication.
Runs via Uvicorn to serve incoming requests when deployed to Cloud Run.
"""

import os

import uvicorn
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents") 

SESSION_SERVICE_URI = os.getenv("SESSION_SERVICE_URI", "sqlite:///./sessions.db")
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
SERVE_WEB_INTERFACE = os.getenv("SERVE_WEB_INTERFACE", "false").lower() == "true"
ENABLE_A2A = os.getenv("ENABLE_A2A", "false").lower() == "true"

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri=SESSION_SERVICE_URI,
    allow_origins=ALLOWED_ORIGINS,
    web=SERVE_WEB_INTERFACE,
    a2a=ENABLE_A2A
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
