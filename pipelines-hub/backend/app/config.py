"""Configuración del servicio (variables de entorno con prefijo HUB_)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HUB_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    # Clave Fernet para cifrar los tokens. Si no viene, se genera y se guarda en data_dir.
    secret_key: str | None = None
    static_dir: Path | None = None

    # Cadencias del poller (segundos)
    tick_seconds: float = 5
    repo_list_interval: int = 60
    hot_poll_interval: int = 15  # repos con ejecuciones activas
    warm_poll_interval: int = 60  # repos con ejecuciones en la última hora
    cold_poll_interval: int = 600  # el resto
    deployments_interval: int = 1800
    github_pr_interval: int = 120  # con ETag: casi gratis
    bitbucket_pr_interval: int = 300  # Bitbucket no tiene ETag: cuidar el rate limit
    closed_pr_days: int = 14  # cuánto se guardan los PR cerrados/mergeados
    concurrency: int = 6

    # Qué repos se siguen por defecto dentro de una org/workspace
    default_max_repos: int = 30
    default_active_days: int = 45
    runs_per_repo: int = 30  # cuántas ejecuciones se guardan por repo

    http_timeout: float = 30

    # Infraestructura (montados en el contenedor en modo solo lectura)
    kubeconfig: Path = Path("~/.kube/config")
    ssh_dir: Path = Path("~/.ssh")
    server_sample_interval: int = 60
    server_history_days: int = 7

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'hub.db'}"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
