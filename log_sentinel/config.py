from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "llama3.2"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    SLACK_WEBHOOK_URL: str = ""
    JIRA_BASE_URL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_PROJECT_KEY: str = "OPS"

    FAISS_INDEX_PATH: str = "./data/faiss_index"

    ANOMALY_CONTAMINATION: float = 0.05
    WINDOW_SIZE_SECONDS: int = 60
    CRITICAL_ERROR_RATE: float = 0.40
    HIGH_ERROR_RATE: float = 0.20
    MEDIUM_ERROR_RATE: float = 0.10
    BASELINE_WINDOW_MINUTES: int = 60
    MAX_AGENT_ITERATIONS: int = 5
    ALERT_COOLDOWN_SECONDS: int = 300


settings = Settings()
