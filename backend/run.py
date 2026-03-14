"""
Uvicorn runner for the Live AI Video Tutor backend.
Usage: python run.py
"""

import uvicorn

from config import settings

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
