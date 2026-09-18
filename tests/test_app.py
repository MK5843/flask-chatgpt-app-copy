"""
Basic automated checks — confirm the app starts cleanly and core
routes behave as expected. These run automatically on every push.
"""
import os

import sys

# Make sure Python can find app.py, which lives one folder above this file
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Dummy values so the app can start in CI without needing real secrets.
# This is a fixed, non-secret Fernet key generated just for testing —
# never used against real data.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("APP_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "Puuk_0nZmM7KWmWDJQBW6dE1yM6kWCE4ckZCRreiI34=")
os.environ.setdefault("FLASK_SECRET_KEY", "test-flask-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DB_PASSWORD", "postgres")
os.environ.setdefault("FLASK_DEBUG", "False")

import pytest
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


def test_login_page_loads(client):
    """The sign-in page should be publicly reachable."""
    response = client.get("/login-page")
    assert response.status_code == 200


def test_chat_requires_login(client):
    """Someone not signed in should never reach the chat endpoint."""
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code in (302, 401)  # redirected to login, or unauthorized


def test_signup_rejects_short_password(client):
    """Password validation should reject anything under 8 characters."""
    response = client.post("/signup", json={"email": "test@example.com", "password": "short"})
    assert response.status_code == 400