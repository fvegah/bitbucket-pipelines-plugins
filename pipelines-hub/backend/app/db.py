"""Modelo de datos (SQLite vía SQLAlchemy async)."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """SQLite no guarda zona horaria: todo se guarda y se lee como UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))  # github | bitbucket
    name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(String(200))  # email en Bitbucket
    secret_enc: Mapped[str] = mapped_column(Text)
    api_url: Mapped[str | None] = mapped_column(String(300))  # GitHub Enterprise
    login: Mapped[str | None] = mapped_column(String(200))  # identidad resuelta al validar
    user_id: Mapped[str | None] = mapped_column(String(200))  # login (GitHub) / account_id (BB)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | error
    status_detail: Mapped[str | None] = mapped_column(Text)
    rate_remaining: Mapped[int | None] = mapped_column(Integer)
    rate_limit: Mapped[int | None] = mapped_column(Integer)
    backoff_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    sources: Mapped[list["Source"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Source(Base):
    """Organización / usuario (GitHub) o workspace (Bitbucket) que se sigue."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("account_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # org | user | workspace
    slug: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    repo_filter: Mapped[str | None] = mapped_column(Text)  # globs separados por coma
    max_repos: Mapped[int] = mapped_column(Integer, default=30)
    active_days: Mapped[int] = mapped_column(Integer, default=45)
    repos_etag: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    account: Mapped[Account] = relationship(back_populates="sources")
    repos: Mapped[list["Repo"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )


class Repo(Base):
    __tablename__ = "repos"
    __table_args__ = (UniqueConstraint("source_id", "full_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    full_name: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(200))
    html_url: Mapped[str | None] = mapped_column(String(500))
    git_url: Mapped[str | None] = mapped_column(String(500))  # repo de código (Cloudflare)
    default_branch: Mapped[str | None] = mapped_column(String(200))
    private: Mapped[bool] = mapped_column(Boolean, default=True)
    activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    runs_etag: Mapped[str | None] = mapped_column(Text)
    next_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_polled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deployments_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    prs_etag: Mapped[str | None] = mapped_column(Text)
    prs_next_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="repos")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("repo_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    number: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int | None] = mapped_column(Integer)
    workflow: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    raw_status: Mapped[str | None] = mapped_column(String(100))
    branch: Mapped[str | None] = mapped_column(String(300))
    sha: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str | None] = mapped_column(String(200))
    actor_avatar: Mapped[str | None] = mapped_column(String(500))
    event: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    duration_s: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    repo: Mapped[Repo] = relationship()


class Deployment(Base):
    """Último despliegue conocido por entorno."""

    __tablename__ = "deployments"
    __table_args__ = (UniqueConstraint("repo_id", "environment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    environment: Mapped[str] = mapped_column(String(200))
    env_type: Mapped[str | None] = mapped_column(String(50))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20))
    sha: Mapped[str | None] = mapped_column(String(64))
    ref: Mapped[str | None] = mapped_column(String(300))
    actor: Mapped[str | None] = mapped_column(String(200))
    deployed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    url: Mapped[str | None] = mapped_column(String(500))
    run_external_id: Mapped[str | None] = mapped_column(String(100))

    repo: Mapped[Repo] = relationship()


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repo_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), index=True)  # open | merged | closed
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    author: Mapped[str | None] = mapped_column(String(200))
    author_id: Mapped[str | None] = mapped_column(String(200))
    author_avatar: Mapped[str | None] = mapped_column(String(500))
    source_branch: Mapped[str | None] = mapped_column(String(300))
    target_branch: Mapped[str | None] = mapped_column(String(300))
    head_sha: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    comment_count: Mapped[int | None] = mapped_column(Integer)
    task_count: Mapped[int | None] = mapped_column(Integer)
    reviewers_json: Mapped[str] = mapped_column(Text, default="[]")
    reviews_for: Mapped[str | None] = mapped_column(String(64))  # updated_at ya enriquecido

    repo: Mapped[Repo] = relationship()


class SavedView(Base):
    """Vista guardada de ejecuciones: un nombre + un filtro (JSON)."""

    __tablename__ = "views"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    scope: Mapped[str | None] = mapped_column(String(20))  # runs | prs | deployments
    filter_json: Mapped[str] = mapped_column(Text, default="{}")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


_settings = get_settings()
engine = create_async_engine(_settings.db_url, connect_args={"timeout": 30})


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_columns(conn) -> None:
    """Migración mínima: agrega columnas nuevas (siempre nullables) a tablas existentes."""
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing:
                ddl = col.type.compile(dialect=conn.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
