"""
Project configuration, read from environment variables (and .env locally).

Import `settings` instead of reading os.environ directly, so configuration lives in one
place.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The hockey database from docker-compose.yml (make db-up). Inside Docker, compose sets
    # this to the `db` service instead of localhost.
    database_url: str = "postgresql://hockey:hockey@localhost:5432/hockey"

    # Required in the X-API-Key header when set; the dashboard sends it too. Generate one:
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"
    api_key: str = ""


settings = Settings()
