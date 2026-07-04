from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # Worker tuning
    worker_poll_interval_s: float = 1.0
    worker_concurrency: int = 4
    heartbeat_interval_s: float = 10.0
    # A worker is considered dead after missing this many heartbeat intervals.
    heartbeat_dead_after_s: float = 30.0

    scheduler_interval_s: float = 1.0
    # Postgres advisory lock key that guarantees a single active scheduler.
    scheduler_lock_key: int = 815_2026

    class Config:
        env_file = ".env"


settings = Settings()
