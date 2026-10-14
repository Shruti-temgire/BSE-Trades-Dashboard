"""FastAPI application entry point.

Run from the project root:
    python -m uvicorn backend.app.main:app --port 8000
"""

from .app_factory import create_app

app = create_app()
