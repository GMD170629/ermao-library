from pathlib import Path, PurePosixPath

from app.modules.imports.application.library_paths import library_directory_tree_node
from app.modules.imports.infrastructure.directory_mounts import directory_mount_resolver
from app.modules.imports.presentation.schemas import LibraryDirectoryNode


def test_mounts_include_same_device_bind_and_nested_mounts(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 8:1 / / rw - ext4 /dev/sda rw\n"
        "2 1 8:1 /host/books /books rw - ext4 /dev/sda rw\n"
        "3 2 8:2 / /books/other rw - xfs /dev/sdb rw\n"
        "4 1 0:2 / /proc rw - proc proc rw\n"
        "5 1 0:3 / /dev rw - tmpfs tmpfs rw\n"
        "6 2 0:4 / /books/system rw - proc proc rw\n"
        "7 1 0:5 / /temporary rw - tmpfs tmpfs rw\n"
        "8 1 0:6 / /network rw - nfs nas:/books rw\n"
        "malformed line\n",
        encoding="utf-8",
    )
    resolve = directory_mount_resolver(mountinfo)
    assert resolve(Path("/books")) == "/books"
    assert resolve(Path("/books/title/volume")) == "/books"
    assert resolve(Path("/books/other/title")) == "/books/other"
    assert resolve(Path("/temporary")) == "/temporary"
    assert resolve(Path("/network/title")) == "/network"
    for path in ("/", "/bookshelf", "/ordinary", "/proc/self", "/dev/shm", "/books/system"):
        assert resolve(Path(path)) is None


def test_mount_paths_decode_kernel_escapes_and_refresh(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        r"2 1 8:1 /host/private /my\040books\134name rw shared:1 - ext4 /dev/sda rw" + "\n",
        encoding="utf-8",
    )
    assert directory_mount_resolver(mountinfo)(PurePosixPath("/my books\\name/title")) == "/my books\\name"
    mountinfo.write_text("", encoding="utf-8")
    assert directory_mount_resolver(mountinfo)(Path("/my books\\name")) is None
    assert directory_mount_resolver(tmp_path / "absent")(Path("/books")) is None


def test_directory_response_marks_parent_and_children_without_host_paths(tmp_path):
    books = tmp_path / "books"
    books.mkdir()
    (books / "title").mkdir()
    (tmp_path / "ordinary").mkdir()
    def resolve(path: Path) -> str | None:
        return str(books) if path.is_relative_to(books) else None
    node, error, status = library_directory_tree_node(str(tmp_path), mount_root_for_path=resolve)
    assert status == 200 and error is None
    payload = LibraryDirectoryNode.model_validate(node).model_dump(by_alias=True)
    children = {child["name"]: child for child in payload["children"]}
    assert children["books"]["mountRoot"] == str(books)
    assert children["ordinary"]["mountRoot"] is None
    node, _, _ = library_directory_tree_node(str(books), mount_root_for_path=resolve)
    assert node["mountRoot"] == str(books)
    assert node["children"][0]["mountRoot"] == str(books)
    assert "/private/host" not in str(node)


def test_container_browser_lists_mounts_and_rejects_unmounted_paths(tmp_path):
    books = tmp_path / "nested" / "books"
    books.mkdir(parents=True)
    (books / "title").mkdir()
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()

    def resolve(path: Path) -> str | None:
        return str(books) if path.is_relative_to(books) else None

    for path in (None, "/", str(books.parent)):
        node, error, status = library_directory_tree_node(
            path, mount_root_for_path=resolve, browse_roots=(books,),
        )
        assert status == 200 and error is None
        assert node["mountedOnly"] is True and node["readable"] is False
        assert [child["path"] for child in node["children"]] == [str(books)]
    node, _, status = library_directory_tree_node(
        str(books), mount_root_for_path=resolve, browse_roots=(books,),
    )
    assert status == 200 and node["children"][0]["name"] == "title"
    node, _, status = library_directory_tree_node(
        str(ordinary), mount_root_for_path=resolve, browse_roots=(books,),
    )
    assert status == 404 and node is None
    node, _, status = library_directory_tree_node(
        None, mount_root_for_path=lambda path: None, browse_roots=(),
    )
    assert status == 200 and node["children"] == [] and node["mountedOnly"] is True


def test_container_detection_keeps_restricted_empty_list_when_metadata_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SHUKU_CONTAINER", "1")
    assert directory_mount_resolver(tmp_path / "missing").browse_roots == ()
    assert directory_mount_resolver(tmp_path / "missing", containerized=False).browse_roots is None


def test_mount_browser_filters_children_that_resolve_outside_mount(tmp_path):
    books = tmp_path / "books"
    books.mkdir()
    (books / "title").mkdir()
    (books / "system").mkdir()

    def resolve(path: Path) -> str | None:
        return str(books) if path.is_relative_to(books) and path.name != "system" else None

    node, _, status = library_directory_tree_node(
        str(books), mount_root_for_path=resolve, browse_roots=(books,),
    )
    assert status == 200
    assert [child["name"] for child in node["children"]] == ["title"]
