from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"
    object_store_path: str = "/tmp/rag-objects"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4.1-mini"
    reranker_mode: str = "lexical"
    jwt_secret: str = "development-only"
    acquisition_allowed_hosts: str = "faa.gov,www.faa.gov,uasdoc.faa.gov,nasa.gov,www.nasa.gov,ntrs.nasa.gov,nist.gov,www.nist.gov,cisa.gov,www.cisa.gov,ntsb.gov,www.ntsb.gov,fcc.gov,www.fcc.gov"
    acquisition_max_bytes: int = 25_000_000
    acquisition_timeout_seconds: float = 30.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
