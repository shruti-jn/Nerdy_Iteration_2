"""
Configuration module for the Live AI Video Tutor backend.
Loads all settings from environment variables via Pydantic BaseSettings.
Pipeline stage: Infrastructure (shared by all stages)
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from .env file and environment variables."""

    # --- API Keys ---
    deepgram_api_key: str = Field(default="", description="Deepgram API key for STT (Nova-3)")
    groq_api_key: str = Field(default="", description="Groq API key for LLM (Llama 3.3 70B)")
    cartesia_api_key: str = Field(default="", description="Cartesia API key for TTS (Sonic-3)")
    simli_api_key: str = Field(default="", description="Simli API key for avatar rendering")
    logfire_token: str = Field(default="", description="Pydantic Logfire token for observability")
    braintrust_api_key: str = Field(default="", description="Braintrust API key for eval logging")

    # --- Orchestrator ---
    orchestrator: str = Field(default="custom", description="Orchestrator type: 'custom' or 'livekit'")

    # --- Latency Budgets (ms) ---
    stt_target_ms: int = Field(default=150, description="STT target latency in ms")
    stt_max_ms: int = Field(default=300, description="STT max acceptable latency in ms")
    llm_ttft_target_ms: int = Field(default=200, description="LLM time-to-first-token target in ms")
    llm_ttft_max_ms: int = Field(default=400, description="LLM TTFT max acceptable in ms")
    tts_target_ms: int = Field(default=150, description="TTS first byte target latency in ms")
    tts_max_ms: int = Field(default=300, description="TTS first byte max acceptable in ms")
    avatar_target_ms: int = Field(default=100, description="Avatar render target latency in ms")
    avatar_max_ms: int = Field(default=200, description="Avatar render max acceptable in ms")
    total_target_ms: int = Field(default=500, description="End-to-end target latency in ms")
    total_max_ms: int = Field(default=1000, description="End-to-end max acceptable in ms")

    # --- Simli ---
    simli_face_id: str = Field(default="", description="Simli face ID for avatar")

    # --- Server ---
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server bind port")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
