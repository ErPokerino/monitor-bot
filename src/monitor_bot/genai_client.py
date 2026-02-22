"""Centralized google-genai client factory.

Returns a Vertex AI-backed client when GCP_PROJECT_ID is set,
otherwise falls back to API key authentication for local development.
"""

from __future__ import annotations

from google import genai

from monitor_bot.config import Settings


def create_genai_client(settings: Settings) -> genai.Client:
    if settings.gcp_project_id:
        return genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.gcp_region,
        )
    if settings.gemini_api_key:
        return genai.Client(api_key=settings.gemini_api_key)
    raise RuntimeError(
        "Either GCP_PROJECT_ID (for Vertex AI) or GEMINI_API_KEY must be set"
    )
