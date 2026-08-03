from __future__ import annotations

import zipfile
from pathlib import Path

from app.modules.imports.application.import_epub import parse_epub_metadata


def _write_epub(path: Path, *, opf_path: str) -> None:
    package_directory = Path(opf_path).parent.as_posix()
    prefix = "" if package_directory == "." else f"{package_directory}/"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            f'<container><rootfiles><rootfile full-path="{opf_path}"/></rootfiles></container>',
        )
        archive.writestr(
            opf_path,
            """<package><metadata><title>Navigation</title></metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="chapter"/></spine></package>""",
        )
        archive.writestr(
            f"{prefix}nav.xhtml",
            '<html><body><nav epub:type="toc"><a href="Text/chapter.xhtml#start">Chapter</a></nav></body></html>',
        )
        archive.writestr(
            f"{prefix}Text/chapter.xhtml",
            '<html><body><h1 id="start">Chapter</h1></body></html>',
        )


def test_epub_navigation_href_is_relative_to_the_publication_root(
    tmp_path: Path,
) -> None:
    epub = tmp_path / "nested-package.epub"
    _write_epub(epub, opf_path="OEBPS/content.opf")

    metadata = parse_epub_metadata(epub)

    assert metadata["chapters"][0]["href"] == "OEBPS/Text/chapter.xhtml#start"


def test_epub_navigation_href_stays_unchanged_for_a_root_package(
    tmp_path: Path,
) -> None:
    epub = tmp_path / "root-package.epub"
    _write_epub(epub, opf_path="content.opf")

    metadata = parse_epub_metadata(epub)

    assert metadata["chapters"][0]["href"] == "Text/chapter.xhtml#start"
