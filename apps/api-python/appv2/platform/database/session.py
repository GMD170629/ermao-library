from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.engine: Engine = create_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    def sessions(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()
