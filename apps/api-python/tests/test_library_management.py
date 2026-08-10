import json

import pytest
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.modules.library.infrastructure.deletion import delete_work_records
from app.services import library_management
from app.services.library_filters import compile_filter_rules
from app.services.library_management import (
    count_categories,
    delete_category,
    duplicate_groups,
    list_categories,
    merge_categories,
    merge_works,
    rename_category,
    smart_shelf_work_ids,
    sync_work_facets,
    undo_operation,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def _insert_work(
    db: Session, work_id: str, title: str, author: str, tags: list[str]
) -> None:
    db.execute(
        text(
            "INSERT INTO `LibraryWork` (`id`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`, `tags`, `mergeKey`, `updatedAt`) "
            "VALUES (:id, :title, :normalized_title, :author, :normalized_author, :tags, :merge_key, '2026-07-22T00:00:00')"
        ),
        {
            "id": work_id,
            "title": title,
            "normalized_title": title.casefold().replace(" ", ""),
            "author": author,
            "normalized_author": author.casefold().replace(" ", ""),
            "tags": json.dumps(tags, ensure_ascii=False),
            "merge_key": f"{title.casefold()}:{author.casefold()}",
        },
    )
    db.execute(
        text(
            "INSERT INTO `LibraryMediaVersion` (`id`, `workId`, `mediaKind`, `updatedAt`) "
            "VALUES (:id, :work_id, 'EBOOK', '2026-07-22T00:00:00')"
        ),
        {"id": f"media-{work_id}", "work_id": work_id},
    )
    db.execute(
        text(
            "INSERT INTO `LibraryVolume` (`id`, `mediaVersionId`, `title`, `sortOrder`, `format`, `resourceKey`, `publisher`, `importStatus`, `updatedAt`) "
            "VALUES (:id, :media_id, :title, 0, 'EPUB', :resource_key, :publisher, 'IMPORTED', '2026-07-22T00:00:00')"
        ),
        {
            "id": f"volume-{work_id}",
            "media_id": f"media-{work_id}",
            "title": f"{title} 默认卷",
            "resource_key": f"key-{work_id}",
            "publisher": "星海出版社",
        },
    )
    db.commit()
    sync_work_facets(db, work_id)


def test_duplicates_smart_shelf_merge_and_undo_use_persisted_v9_data(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-a", "星海列车", "林川", ["科幻", "收藏"])
            _insert_work(db, "work-b", "星海列车", "林川", ["科幻小说"])
            assert len(duplicate_groups(db)) == 1
            assert smart_shelf_work_ids(db, {"search": "星海", "tags": ["科幻"]}) == [
                "work-a"
            ]
            assert {item["name"] for item in list_categories(db, "TAG")} == {
                "科幻",
                "收藏",
                "科幻小说",
            }

            merged = merge_works(db, "work-a", ["work-b"], None)
            assert db.get(LibraryWork, "work-b") is None
            assert db.get(LibraryMediaVersion, "media-work-b") is None
            assert (
                db.get(LibraryVolume, "volume-work-b").media_version_id
                == "media-work-a"
            )
            assert merged["operation"]["undoAvailable"] is True

            undo_operation(db, merged["operation"]["id"], None)
            assert db.get(LibraryWork, "work-b") is not None
            assert db.get(LibraryMediaVersion, "media-work-b") is not None
            assert (
                db.get(LibraryVolume, "volume-work-b").media_version_id
                == "media-work-b"
            )
    finally:
        engine.dispose()


def test_category_listing_supports_count_search_and_stable_pagination(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            for index in range(1, 26):
                _insert_work(
                    db,
                    f"work-{index:02d}",
                    f"作品 {index:02d}",
                    f"作者 {index:02d}",
                    [f"标签 {index:02d}"],
                )
            assert count_categories(db, "AUTHOR") == 25
            first_page = list_categories(db, "AUTHOR", limit=10, offset=0)
            third_page = list_categories(db, "AUTHOR", limit=10, offset=20)
            assert len(first_page) == 10
            assert len(third_page) == 5
            assert {item["id"] for item in first_page}.isdisjoint(
                {item["id"] for item in third_page}
            )
            assert count_categories(db, "AUTHOR", "作者 02") == 1
            assert [
                item["name"]
                for item in list_categories(db, "AUTHOR", "作者 02", limit=10)
            ] == ["作者 02"]
    finally:
        engine.dispose()


def test_category_merge_rename_and_undo_restore_legacy_metadata(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-a", "边界", "林川", ["科幻"])
            _insert_work(db, "work-b", "远航", "周禾", ["科幻小说"])
            tags = {item["name"]: item for item in list_categories(db, "TAG")}

            merged = merge_categories(
                db, "TAG", [tags["科幻小说"]["id"]], tags["科幻"]["id"], None
            )
            assert json.loads(
                db.execute(
                    text("SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-b'")
                ).scalar()
            ) == ["科幻"]
            undo_operation(db, merged["operation"]["id"], None)
            assert json.loads(
                db.execute(
                    text("SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-b'")
                ).scalar()
            ) == ["科幻小说"]

            tag = next(
                item for item in list_categories(db, "TAG") if item["name"] == "科幻"
            )
            renamed = rename_category(db, tag["id"], "科学幻想", None)
            assert json.loads(
                db.execute(
                    text("SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
            ) == ["科学幻想"]
            undo_operation(db, renamed["operation"]["id"], None)
            assert json.loads(
                db.execute(
                    text("SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
            ) == ["科幻"]
    finally:
        engine.dispose()


def test_category_delete_clears_all_metadata_kinds_and_supports_undo(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-a", "边界", "林川、周禾", ["科幻", "收藏"])
            db.execute(
                text(
                    "UPDATE `LibraryWork` SET `seriesName` = '星海丛书', `seriesIndex` = 3 "
                    "WHERE `id` = 'work-a'"
                )
            )
            db.commit()
            sync_work_facets(db, "work-a")

            for kind, name in (
                ("TAG", "科幻"),
                ("AUTHOR", "林川"),
                ("SERIES", "星海丛书"),
            ):
                category = next(
                    item for item in list_categories(db, kind) if item["name"] == name
                )
                deleted = delete_category(db, category["id"], None)
                assert deleted["kind"] == kind
                assert deleted["affectedBookCount"] == 1
                assert all(
                    item["id"] != category["id"] for item in list_categories(db, kind)
                )

                if kind == "TAG":
                    assert json.loads(
                        db.execute(
                            text(
                                "SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-a'"
                            )
                        ).scalar()
                    ) == ["收藏"]
                elif kind == "AUTHOR":
                    assert (
                        db.execute(
                            text(
                                "SELECT `author` FROM `LibraryWork` WHERE `id` = 'work-a'"
                            )
                        ).scalar()
                        == "周禾"
                    )
                elif kind == "SERIES":
                    assert (
                        db.execute(
                            text(
                                "SELECT `seriesName` FROM `LibraryWork` WHERE `id` = 'work-a'"
                            )
                        ).scalar()
                        is None
                    )
                    assert (
                        db.execute(
                            text(
                                "SELECT `seriesIndex` FROM `LibraryWork` WHERE `id` = 'work-a'"
                            )
                        ).scalar()
                        is None
                    )
                undo_operation(db, deleted["operation"]["id"], None)
                assert any(
                    item["id"] == category["id"] for item in list_categories(db, kind)
                )

            assert json.loads(
                db.execute(
                    text("SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
            ) == ["科幻", "收藏"]
            assert (
                db.execute(
                    text("SELECT `author` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
                == "林川、周禾"
            )
            assert (
                db.execute(
                    text("SELECT `seriesName` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
                == "星海丛书"
            )
            assert (
                db.execute(
                    text(
                        "SELECT `seriesIndex` FROM `LibraryWork` WHERE `id` = 'work-a'"
                    )
                ).scalar()
                == 3
            )
            assert (
                db.execute(
                    text(
                        "SELECT `publisher` FROM `LibraryVolume` WHERE `id` = 'volume-work-a'"
                    )
                ).scalar()
                == "星海出版社"
            )
    finally:
        engine.dispose()


def test_deleting_a_work_only_author_uses_unknown_author_fallback(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-a", "边界", "林川", [])
            author = next(
                item for item in list_categories(db, "AUTHOR") if item["name"] == "林川"
            )

            delete_category(db, author["id"], None)

            assert (
                db.execute(
                    text("SELECT `author` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
                == "未知作者"
            )
            assert db.execute(
                text(
                    "SELECT `normalizedAuthor` FROM `LibraryWork` WHERE `id` = 'work-a'"
                )
            ).scalar()
    finally:
        engine.dispose()


def test_library_writes_rollback_when_facet_sync_fails(tmp_path, monkeypatch) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-a", "星海列车", "林川", ["科幻"])
            _insert_work(db, "work-b", "远航日志", "周禾", ["旅行"])
            original_sync = library_management.sync_work_facets

            def fail_sync(*_args, **_kwargs) -> None:
                raise RuntimeError("facet sync failed")

            monkeypatch.setattr(library_management, "sync_work_facets", fail_sync)
            with pytest.raises(RuntimeError, match="facet sync failed"):
                merge_works(db, "work-a", ["work-b"], None)
            assert (
                db.execute(
                    text("SELECT `hidden` FROM `LibraryWork` WHERE `id` = 'work-b'")
                ).scalar()
                == 0
            )
            assert (
                db.execute(
                    text(
                        "SELECT media.workId FROM LibraryVolume AS volume JOIN LibraryMediaVersion AS media ON media.id = volume.mediaVersionId WHERE volume.id = 'volume-work-b'"
                    )
                ).scalar()
                == "work-b"
            )
            assert (
                db.execute(text("SELECT COUNT(*) FROM `LibraryOperation`")).scalar()
                == 0
            )

            monkeypatch.setattr(library_management, "sync_work_facets", original_sync)
            merged = merge_works(db, "work-a", ["work-b"], None)
            operation_id = str(merged["operation"]["id"])
            monkeypatch.setattr(library_management, "sync_work_facets", fail_sync)
            with pytest.raises(RuntimeError, match="facet sync failed"):
                undo_operation(db, operation_id, None)
            assert db.get(LibraryWork, "work-b") is None
            assert db.get(LibraryMediaVersion, "media-work-b") is None
            assert (
                db.get(LibraryVolume, "volume-work-b").media_version_id
                == "media-work-a"
            )
            assert (
                db.execute(
                    text(
                        "SELECT `status` FROM `LibraryOperation` WHERE `id` = :operation_id"
                    ),
                    {"operation_id": operation_id},
                ).scalar()
                == "COMPLETED"
            )
    finally:
        engine.dispose()


def test_category_write_rolls_back_and_success_commits_once(
    tmp_path, monkeypatch
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-a", "边界", "林川", ["科幻"])
            tag = next(
                item for item in list_categories(db, "TAG") if item["name"] == "科幻"
            )
            original_commit = db.commit
            commit_count = 0

            def count_commit() -> None:
                nonlocal commit_count
                commit_count += 1
                original_commit()

            monkeypatch.setattr(db, "commit", count_commit)
            rename_category(db, str(tag["id"]), "科学幻想", None)
            assert commit_count == 1

            def fail_sync(*_args, **_kwargs) -> None:
                raise RuntimeError("facet sync failed")

            monkeypatch.setattr(library_management, "sync_work_facets", fail_sync)
            renamed_tag = next(
                item
                for item in list_categories(db, "TAG")
                if item["name"] == "科学幻想"
            )
            with pytest.raises(RuntimeError, match="facet sync failed"):
                delete_category(db, str(renamed_tag["id"]), None)
            assert json.loads(
                db.execute(
                    text("SELECT `tags` FROM `LibraryWork` WHERE `id` = 'work-a'")
                ).scalar()
            ) == ["科学幻想"]
            assert next(
                item
                for item in list_categories(db, "TAG")
                if item["name"] == "科学幻想"
            )
    finally:
        engine.dispose()


def test_dynamic_filters_cover_metadata_files_shelves_folders_and_free_combinations(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.execute(
                text(
                    "INSERT INTO `MonitorFolder` (`id`, `name`, `rootPath`, `updatedAt`) "
                    "VALUES ('folder-a', '科幻原始目录', '/books/scifi', '2026-07-22T00:00:00')"
                )
            )
            _insert_work(db, "work-a", "星海列车", "林川", ["科幻", "收藏"])
            _insert_work(db, "work-b", "远航日志", "周禾", ["旅行"])
            db.execute(
                text(
                    "UPDATE `LibraryWork` SET `monitorFolderId` = 'folder-a', `origin` = 'WATCH', "
                    "`metadataQuality` = 92, `createdAt` = '2026-07-01T10:00:00' WHERE `id` = 'work-a'"
                )
            )
            db.execute(
                text(
                    "UPDATE `LibraryVolume` SET `format` = 'EPUB', `language` = 'zh-CN' WHERE `id` = 'volume-work-a'"
                )
            )
            db.execute(
                text(
                    "UPDATE `LibraryVolume` SET `monitorFolderId` = 'folder-a', `origin` = 'WATCH' WHERE `id` = 'volume-work-a'"
                )
            )
            db.execute(
                text(
                    "UPDATE `LibraryMediaVersion` SET `mediaKind` = 'AUDIOBOOK' WHERE `id` = 'media-work-b'"
                )
            )
            db.execute(
                text(
                    "UPDATE `LibraryVolume` SET `format` = 'AUDIO' WHERE `id` = 'volume-work-b'"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `LibraryFile` (`id`, `volumeId`, `path`, `kind`, `mimeType`, `sizeBytes`, `updatedAt`) "
                    "VALUES ('file-a', 'volume-work-a', '/books/scifi/星海列车.epub', 'BOOK', 'application/epub+zip', 2097152, '2026-07-22T00:00:00')"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `Shelf` (`id`, `name`, `updatedAt`) VALUES ('shelf-a', '科幻收藏', '2026-07-22T00:00:00')"
                )
            )
            db.execute(
                text(
                    "INSERT INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES ('shelf-a', 'work-a', '2026-07-22T00:00:00')"
                )
            )
            db.commit()
            all_rules = {
                "combinator": "ALL",
                "conditions": [
                    {"field": "tag", "operator": "equals", "value": "科幻"},
                    {"field": "mediaKind", "operator": "equals", "value": "EBOOK"},
                    {"field": "shelf", "operator": "equals", "value": "shelf-a"},
                    {
                        "field": "monitorFolder",
                        "operator": "equals",
                        "value": "folder-a",
                    },
                    {"field": "sourcePath", "operator": "contains", "value": "scifi"},
                    {"field": "fileSize", "operator": "greater_than", "value": "1.5"},
                    {
                        "field": "createdAt",
                        "operator": "on_or_after",
                        "value": "2026-07-01",
                    },
                ],
            }
            predicate, _params, error = compile_filter_rules(db, all_rules, alias="w")
            assert error is None
            assert predicate is not None
            matched = db.scalars(
                select(LibraryWork.id).where(predicate).order_by(LibraryWork.id)
            ).all()
            assert matched == ["work-a"]
            assert smart_shelf_work_ids(db, all_rules) == ["work-a"]

            any_rules = {
                "combinator": "ANY",
                "conditions": [
                    {"field": "title", "operator": "contains", "value": "不存在"},
                    {"field": "format", "operator": "equals", "value": "AUDIO"},
                ],
            }
            assert smart_shelf_work_ids(db, any_rules) == ["work-b"]

    finally:
        engine.dispose()


def test_delete_work_removes_media_versions_and_volumes(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "work-delete", "待删除作品", "林川", ["科幻"])
            media_version = db.get(LibraryMediaVersion, "media-work-delete")
            assert media_version is not None

            result = delete_work_records(db, "work-delete")
            db.commit()

            assert result["deleted"] is True
            assert db.get(LibraryWork, "work-delete") is None
            assert db.get(LibraryMediaVersion, "media-work-delete") is None
            assert db.get(LibraryVolume, "volume-work-delete") is None
    finally:
        engine.dispose()
