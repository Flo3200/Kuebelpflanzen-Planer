"""Application configuration. Everything comes from environment variables or the .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KP_",
        env_file=(str(PROJECT_ROOT / ".env"), ".env"),
        extra="ignore",
    )

    env: str = "development"
    base_url: str = "http://localhost:8000"
    secret_key: str = "insecure-dev-key"
    encryption_key: str = ""

    database_url: str = "postgresql+psycopg://kp_app:kp_app@localhost:5433/kuebelplaner"
    database_owner_url: str = "postgresql+psycopg://kp_owner:kp_owner@localhost:5433/kuebelplaner"
    test_database_url: str = ""
    test_database_owner_url: str = ""
    db_pool_size: int = 10

    files_dir: str = "./data/files"
    storage_backend: str = "local"
    frontend_dist: str = ""
    embedded_worker: bool = False
    max_upload_mb: int = 25

    cookie_secure: bool = False
    session_hours: int = 12
    driver_session_days: int = 60

    routing_provider: str = "offline"
    osrm_url: str = "https://router.project-osrm.org"
    ors_api_key: str = ""
    google_maps_api_key: str = ""
    geocoder: str = "offline"
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    # online payments (Stripe Connect): platform key, webhook secret, API base (tests: local mock)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_base: str = "https://api.stripe.com"

    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = ""

    login_max_attempts: int = 8
    login_max_attempts_ip: int = 50
    login_window_minutes: int = 15

    @property
    def files_path(self) -> Path:
        p = Path(self.files_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def frontend_dist_path(self) -> Path:
        if self.frontend_dist:
            return Path(self.frontend_dist)
        return PROJECT_ROOT / "frontend" / "dist"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_config() -> Config:
    return Config()
