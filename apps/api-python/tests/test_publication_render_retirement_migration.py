from alembic import command
from sqlalchemy import inspect

from app.core.config import Settings
from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine


def test_0028_removes_only_reader_render_cache_table(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0027_remove_file_content_hashes"),
        )
        before = set(inspect(engine).get_table_names())
        assert "PublicationRenderCache" in before
        assert "BookConversionTask" in before

        _run_alembic(engine, lambda config: command.upgrade(config, "head"))

        after = set(inspect(engine).get_table_names())
        assert head_revision(engine) == "0028_remove_publication_render_cache"
        assert "PublicationRenderCache" not in after
        assert "BookConversionTask" in after
        assert before - after == {"PublicationRenderCache"}
    finally:
        engine.dispose()
