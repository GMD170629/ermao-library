import os

import pytest

from app.modules.library.domain.file_moves import (
    FileMoveError,
    render_move_template,
    validate_move_path,
    validate_move_set,
)
from app.modules.library.infrastructure.move_inventory import inspect_move_source


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/x",
        "x/../y",
        "a\\b",
        "a/CON.txt",
        "x.",
        "x ",
        "a//b",
        "a\x00b",
        "x:y",
        "x/" + "字" * 100,
    ],
)
def test_move_names_reject_ambiguous_or_nonportable_paths(path):
    with pytest.raises(FileMoveError):
        validate_move_path(path)


def test_template_substitutions_cannot_inject_paths_or_execute_expressions():
    assert (
        render_move_template(
            "{author}/{title}.{ext}",
            {"author": "../name", "title": "a/b", "ext": "epub"},
        )
        == "_name/a_b.epub"
    )
    for template in ("{title.__class__}", "{title!r}", "{title:>10}", "{unknown}", "{"):
        with pytest.raises(FileMoveError, match="INVALID_TEMPLATE"):
            render_move_template(template, {"title": "book"})


def test_batches_reject_overlaps_including_unicode_and_case_collisions():
    with pytest.raises(FileMoveError, match="OVERLAPPING_TARGETS"):
        validate_move_set((("lib", "a"), ("lib", "a/b")), (("lib", "c"), ("lib", "d")))
    with pytest.raises(FileMoveError, match="OVERLAPPING_TARGETS"):
        validate_move_set(
            (("lib", "a"), ("lib", "b")), (("lib", "É"), ("lib", "e\u0301"))
        )
    with pytest.raises(FileMoveError, match="SOURCE_DESTINATION_OVERLAP"):
        validate_move_set((("lib", "a"),), (("lib", "a/b"),))
    validate_move_set((("lib", "a"),), (("other", "a"),))


def test_inventory_is_pure_and_includes_sidecars(tmp_path):
    book = tmp_path / "book"
    book.mkdir()
    (book / "pages").mkdir()
    (book / "pages/1.jpg").write_bytes(b"page")
    (book / "metadata.opf").write_bytes(b"opf")
    before = {str(p.relative_to(tmp_path)): p.stat() for p in tmp_path.rglob("*")}
    result = inspect_move_source(tmp_path, "book")
    assert result.file_count == 2 and result.byte_count == 7
    assert {item.relative_path for item in result.entries} == {
        "book",
        "book/pages",
        "book/pages/1.jpg",
        "book/metadata.opf",
    }
    assert before == {
        str(p.relative_to(tmp_path)): p.stat() for p in tmp_path.rglob("*")
    }


@pytest.mark.parametrize("special", ["symlink", "hardlink", "fifo"])
def test_inventory_rejects_special_sources_without_following_them(tmp_path, special):
    book = tmp_path / "book"
    book.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    target = book / "target"
    if special == "symlink":
        target.symlink_to(outside)
    elif special == "hardlink":
        os.link(outside, target)
    else:
        os.mkfifo(target)
    with pytest.raises(
        FileMoveError, match="SPECIAL_FILE_UNSUPPORTED|HARDLINK_MOVE_UNSUPPORTED"
    ):
        inspect_move_source(tmp_path, "book")
    assert outside.read_bytes() == b"private"


def test_destination_preview_reports_missing_parents_without_creating_them(tmp_path):
    from app.modules.library.infrastructure.move_inventory import (
        inspect_move_destination,
    )

    (tmp_path / "existing").mkdir()
    result = inspect_move_destination(tmp_path, "existing/author/book/title.epub")
    assert result.missing_directories == ("existing/author", "existing/author/book")
    assert result.parent_relative_path == "existing"
    assert not (tmp_path / "existing/author").exists()
    (tmp_path / "existing/Book.epub").write_bytes(b"existing")
    with pytest.raises(FileMoveError, match="DESTINATION_EXISTS"):
        inspect_move_destination(tmp_path, "existing/book.EPUB")


def test_destination_preview_rejects_parent_symlink(tmp_path):
    from app.modules.library.infrastructure.move_inventory import (
        inspect_move_destination,
    )

    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(FileMoveError, match="DESTINATION_UNAVAILABLE"):
        inspect_move_destination(tmp_path, "link/book.epub")
    assert list((tmp_path / "real").iterdir()) == []


def test_plan_authorizes_entire_batch_before_inspection_and_freezes_limits(tmp_path):
    from dataclasses import replace

    from app.modules.library.application.file_move_plans import (
        MoveActor,
        MoveDestination,
        MoveSource,
        PrepareFileMovePlan,
    )
    from app.modules.library.domain.file_moves import MoveRequest
    from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection

    class Topology:
        def source(self, node_id, library_ids):
            return MoveSource(
                node_id, "library", node_id, tmp_path, "revision", ("book",)
            )

        def destination(self, source, request, library_ids):
            return MoveDestination(
                request.destination_library_id,
                tmp_path,
                request.destination_relative_path,
            )

    actor = MoveActor("user", "grant", frozenset({"library", "other"}), False)
    prepare = PrepareFileMovePlan(
        Topology(), AnchoredMoveInspection(), lambda: 1000, lambda: "plan"
    )
    # Missing source proves no I/O happened before rejecting the unauthorized batch.
    with pytest.raises(FileMoveError, match="CROSS_LIBRARY_NOT_AUTHORIZED"):
        prepare.execute(
            actor,
            (
                MoveRequest("missing", "library", "target"),
                MoveRequest("missing2", "other", "target2"),
            ),
        )
    (tmp_path / "book.epub").write_bytes(b"book")
    plan = prepare.execute(
        replace(actor, allow_cross_library=True),
        (MoveRequest("book.epub", "other", "author/book.epub"),),
    )
    assert plan.expires_at_ms == 901000
    assert plan.moves[0].inventory.byte_count == 4
    assert plan.execution_version == 3
    assert not (tmp_path / "author").exists()


@pytest.mark.parametrize("directory", [False, True])
def test_exclusive_publication_does_not_replace_an_existing_target(tmp_path, directory):
    from app.infrastructure.exclusive_rename import exclusive_rename
    from app.modules.library.infrastructure.source_file_access import (
        open_library_directory,
    )

    source = tmp_path / "source"
    target = tmp_path / "target"
    if directory:
        source.mkdir()
        target.mkdir()
        (source / "book").write_bytes(b"source")
        (target / "book").write_bytes(b"target")
    else:
        source.write_bytes(b"source")
        target.write_bytes(b"target")
    with open_library_directory(tmp_path) as descriptor:
        with pytest.raises(FileMoveError, match="DESTINATION_EXISTS"):
            exclusive_rename(descriptor, "source", descriptor, "target")
        exclusive_rename(descriptor, "source", descriptor, "published")
    assert not source.exists()
    assert (
        tmp_path / ("published/book" if directory else "published")
    ).read_bytes() == b"source"
    assert (target / "book" if directory else target).read_bytes() == b"target"


def test_system_move_checks_source_and_completion_without_recovery_copy(tmp_path):
    from app.modules.library.application.file_move_plans import (
        MoveDestination,
        MoveSource,
        PlannedMove,
    )
    from app.modules.library.infrastructure.file_move_io import SystemMovePublication
    from app.modules.library.infrastructure.move_inventory import (
        inspect_move_destination,
    )

    source = tmp_path / "book"
    source.write_bytes(b"original")
    plan = PlannedMove(
        MoveSource("node", "library", "book", tmp_path, "revision", ("book",)),
        MoveDestination("library", tmp_path, "renamed"),
        inspect_move_source(tmp_path, "book"),
        inspect_move_destination(tmp_path, "renamed"),
    )
    files = SystemMovePublication()
    assert not files.is_published(plan)
    files.publish(plan)
    assert (tmp_path / "renamed").read_bytes() == b"original"
    assert not source.exists()
    assert files.is_published(plan)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["renamed"]
    (tmp_path / "renamed").write_bytes(b"external modification")
    with pytest.raises(FileMoveError, match="FILE_MOVE_INCOMPLETE"):
        files.is_published(plan)
    source.write_bytes(b"new occupant")
    with pytest.raises(FileMoveError, match="SOURCE_CHANGED"):
        files.publish(plan)


@pytest.mark.parametrize("directory", [False, True])
def test_system_move_skip_cannot_report_success_or_overwrite(
    tmp_path, monkeypatch, directory
):
    from app.modules.library.application.file_move_plans import (
        MoveDestination,
        MoveSource,
        PlannedMove,
    )
    from app.modules.library.infrastructure import file_move_io
    from app.modules.library.infrastructure.move_inventory import (
        inspect_move_destination,
    )

    source, target = tmp_path / "source", tmp_path / "target"
    if directory:
        source.mkdir()
        (source / "book").write_bytes(b"original")
    else:
        source.write_bytes(b"original")
    plan = PlannedMove(
        MoveSource("node", "library", "source", tmp_path, "revision", ("book",)),
        MoveDestination("library", tmp_path, "target"),
        inspect_move_source(tmp_path, "source"),
        inspect_move_destination(tmp_path, "target"),
    )
    run = file_move_io.subprocess.run

    def concurrent_target(*args, **kwargs):
        if directory:
            target.mkdir()
            (target / "book").write_bytes(b"other")
        else:
            target.write_bytes(b"other")
        return run(*args, **kwargs)

    monkeypatch.setattr(file_move_io.subprocess, "run", concurrent_target)
    with pytest.raises(FileMoveError, match="DESTINATION_EXISTS|FILE_MOVE_INCOMPLETE"):
        file_move_io.SystemMovePublication().publish(plan)
    if directory and not source.exists():
        # BSD mv lacks -T: an external directory race must be reported as
        # incomplete, retaining both the moved content and the existing target.
        assert (target / "source/book").read_bytes() == b"original"
    else:
        assert (source / "book" if directory else source).read_bytes() == b"original"
    assert (target / "book" if directory else target).read_bytes() == b"other"


@pytest.mark.parametrize("target_exists", [False, True])
def test_native_move_failure_preserves_cause_and_inspects_destination(
    tmp_path, monkeypatch, target_exists
):
    import subprocess

    from app.modules.library.application.file_move_plans import (
        MoveDestination,
        MoveSource,
        PlannedMove,
    )
    from app.modules.library.infrastructure.file_move_io import SystemMovePublication
    from app.modules.library.infrastructure.move_inventory import inspect_move_destination

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"original")
    plan = PlannedMove(
        MoveSource("node", "library", "source", tmp_path, "revision", ("book",)),
        MoveDestination("library", tmp_path, "target"),
        inspect_move_source(tmp_path, "source"),
        inspect_move_destination(tmp_path, "target"),
    )
    failure = subprocess.CalledProcessError(1, ["mv"], stderr=b"native failure")

    def fail_move(*args):
        if target_exists:
            target.write_bytes(b"other")
        raise failure

    monkeypatch.setattr(SystemMovePublication, "_move", staticmethod(fail_move))
    expected = "DESTINATION_EXISTS" if target_exists else "FILE_MOVE_FAILED"
    with pytest.raises(FileMoveError, match=expected) as caught:
        SystemMovePublication().publish(plan)
    assert caught.value.__cause__ is failure
    assert source.read_bytes() == b"original"
    if target_exists:
        assert target.read_bytes() == b"other"
    else:
        assert not target.exists()
