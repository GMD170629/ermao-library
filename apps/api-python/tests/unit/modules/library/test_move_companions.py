import pytest

from app.modules.library.application.file_move_plans import MoveDestination, MoveSource
from app.modules.library.domain.file_moves import FileMoveError
from app.modules.library.infrastructure.move_companions import move_companion_paths
from app.modules.metadata.application.opf import serialize_opf_metadata
from app.modules.metadata.public import PublicationMetadata


def inspect(root):
    return move_companion_paths(
        MoveSource("node", "library", "book.epub", root, "revision", ("book",)),
        MoveDestination("library", root, "author/new.epub"),
        directory=False,
    )


def test_same_stem_sidecar_is_ambiguous_between_formats(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"epub")
    (tmp_path / "book.pdf").write_bytes(b"pdf")
    (tmp_path / "book.opf").write_bytes(
        serialize_opf_metadata(PublicationMetadata(title="Book"))
    )
    with pytest.raises(FileMoveError, match="AMBIGUOUS_SIDECAR"):
        inspect(tmp_path)
    assert not (tmp_path / "author").exists()


def test_shared_directory_metadata_is_not_taken_by_one_file(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"epub")
    (tmp_path / "metadata.opf").write_bytes(b"shared")
    with pytest.raises(FileMoveError, match="SHARED_SIDECAR_REQUIRES_DIRECTORY_MOVE"):
        inspect(tmp_path)


@pytest.mark.parametrize(
    "href",
    [
        "../private/cover.jpg",
        "/private/cover.jpg",
        "https://private/cover.jpg",
        "nested/cover.jpg",
    ],
)
def test_cover_references_cannot_expand_arbitrary_paths(tmp_path, href):
    (tmp_path / "book.epub").write_bytes(b"epub")
    (tmp_path / "book.opf").write_bytes(
        serialize_opf_metadata(PublicationMetadata(title="Book", cover_href=href))
    )
    with pytest.raises(FileMoveError, match="SIDECAR_COVER_REQUIRES_DIRECTORY_MOVE"):
        inspect(tmp_path)


def test_cover_name_and_opf_content_are_preserved(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"epub")
    opf = serialize_opf_metadata(
        PublicationMetadata(title="Book", cover_href="cover.jpg")
    )
    (tmp_path / "book.opf").write_bytes(opf)
    (tmp_path / "cover.jpg").write_bytes(b"cover")
    assert inspect(tmp_path) == (
        ("book.opf", "author/new.opf"),
        ("cover.jpg", "author/cover.jpg"),
    )
    assert (tmp_path / "book.opf").read_bytes() == opf
    assert not (tmp_path / "author").exists()
