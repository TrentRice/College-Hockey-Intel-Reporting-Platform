"""
Centralized project configuration.

Reads from environment variables (populated via .env locally, or real env vars
in production/CI). Import `settings` anywhere in the codebase instead of calling
os.environ directly — keeps config in one auditable place.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    environment: str = "development"
    log_level: str = "INFO"

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_artifact_root: str = "./mlruns"
    mlflow_model_name: str = "my-model"
    mlflow_model_stage: str = "Production"

    # Database: the hockey database from docker-compose.yml (make db-up)
    database_url: str = "postgresql://hockey:hockey@localhost:5432/hockey"

    # Serving app
    api_host: str = "127.0.0.1"  # this machine only; see docs/schema.md "Data source and use"
    api_port: int = 8000
    # Required in the X-API-Key header when set. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"
    api_key: str = ""

    # AWS (only required for deploy)
    aws_region: str = "us-east-1"
    aws_account_id: str = ""
    ecr_repository_name: str = ""
    ecs_cluster_name: str = ""
    ecs_service_name: str = ""


settings = Settings()
