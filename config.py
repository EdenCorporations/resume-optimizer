"""Central configuration for the Resume Optimizer application."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Groq API
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv(
        "GROQ_MODEL", "meta-llama/llama-4-maverick-17b-128e-instruct"
    )

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "resume-optimizer-dev-key")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))  # 16MB

    # Vercel / Storage
    IS_VERCEL = bool(os.getenv("VERCEL", ""))
    BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN", "")

    # Vercel AI Gateway (free $5/mo credit, auto-OIDC on Vercel)
    AI_GATEWAY_API_KEY = os.getenv("AI_GATEWAY_API_KEY", "")

    # OpenRouter (free vision model for image classification)
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

    # Research APIs (all optional — free tiers)
    BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
    FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

    # Paths (used in local/dev mode only)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    OUTPUT_FOLDER = os.path.join(BASE_DIR, "outputs")

    @classmethod
    def validate(cls):
        """Validate that required configuration is present."""
        if not cls.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is required. Set it in your .env file."
            )
        # Only create local dirs when NOT on Vercel (read-only filesystem)
        if not cls.IS_VERCEL:
            os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
            os.makedirs(cls.OUTPUT_FOLDER, exist_ok=True)
