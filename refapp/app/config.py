"""Runtime configuration for the Harbor reference app.

All settings are environment-driven (12-factor). Defaults target host-local
development; docker-compose overrides the hostnames to service names.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLAlchemy URL using the psycopg (v3) driver.
    database_url: str = "postgresql+psycopg://harbor:harbor@localhost:5432/harbor"

    # Harbor gateway (data plane) base URL.
    gateway_url: str = "http://localhost:8080"

    # Model name forwarded to the gateway. In mock mode it is cosmetic.
    primary_model: str = "gpt-4o-mini"

    # Local embedding model (ONNX via fastembed — no torch, small image).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Retrieval depth.
    top_k: int = 4

    # Comma-separated CORS origins for the Vite dev server.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
