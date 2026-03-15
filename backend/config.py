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
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key for TTS")
    elevenlabs_voice_id: str = Field(default="JBFqnCBsd6RMkjVDRZzb", description="ElevenLabs voice ID")
    simli_api_key: str = Field(default="", description="Simli API key for avatar rendering")
    logfire_token: str = Field(default="", description="Pydantic Logfire token for observability")
    braintrust_api_key: str = Field(default="", description="Braintrust API key for eval logging")

    # --- Langfuse ---
    langfuse_public_key: str = Field(default="", description="Langfuse public key for LLM tracing")
    langfuse_secret_key: str = Field(default="", description="Langfuse secret key for LLM tracing")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", description="Langfuse API host")

    tts_provider: str = Field(default="deepgram", description="TTS provider: 'deepgram' or 'cartesia'")
    cartesia_voice_id: str = Field(default="", description="Cartesia voice ID (from Cartesia voice library)")

    # --- LLM ---
    llm_model: str = Field(default="llama-3.3-70b-versatile", description="Groq model ID for tutoring")
    llm_max_tokens: int = Field(default=150, description="Max tokens per LLM response (Socratic replies are short)")

    # --- Orchestrator ---
    orchestrator: str = Field(default="custom", description="Orchestrator type: 'custom' or 'livekit'")

    # --- Session ---
    max_turns: int = Field(default=15, description="Maximum conversational turns per tutoring session")

    # --- Deepgram Live STT ---
    stt_endpointing_ms: int = Field(default=300, description="Deepgram endpointing threshold in ms (silence to trigger is_final)")
    stt_utterance_end_ms: int = Field(default=1000, description="Silence duration before Deepgram fires UtteranceEnd event")
    stt_interim_results: bool = Field(default=True, description="Enable interim/partial transcripts from Deepgram")

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

    # --- Avatar Provider ---
    avatar_provider: str = Field(default="simli", description="Avatar provider: 'simli' or 'spatialreal'")

    # --- Simli ---
    simli_face_id: str = Field(default="", description="Simli face ID for avatar")

    # --- SpatialReal ---
    spatialreal_api_key: str = Field(default="", description="SpatialReal API key")
    spatialreal_app_id: str = Field(default="", description="SpatialReal App ID")
    spatialreal_avatar_id: str = Field(default="", description="SpatialReal Avatar ID")
    spatialreal_region: str = Field(default="us-west", description="SpatialReal region: 'us-west' or 'ap-northeast'")

    # --- Server ---
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server bind port")

    model_config = {
        "env_file": ("../.env", ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
