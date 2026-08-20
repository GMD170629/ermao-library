from __future__ import annotations

import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.library import Library


def add_library(
    db: Session,
    root_path: Path,
    *,
    library_id: str = "test-library",
) -> None:
    db.add(
        Library(
            organization_mode="FLAT",
            id=library_id,
            name=root_path.name,
            root_path=str(root_path),
            enabled=True,
        )
    )
    db.commit()


def write_epub_metadata_fixture(
    path: Path,
    title: str,
    author: str,
    identifiers: list[str] | None = None,
    *,
    description: str | None = None,
    subjects: tuple[str, ...] = (),
) -> None:
    identifier_xml = "\n".join(
        f"<dc:identifier>{identifier}</dc:identifier>"
        for identifier in identifiers or []
    )
    description_xml = (
        f"<dc:description>{description}</dc:description>" if description else ""
    )
    subject_xml = "\n".join(
        f"<dc:subject>{subject}</dc:subject>" for subject in subjects
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles><rootfile '
            'full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0"?><package><metadata
            xmlns:dc="http://purl.org/dc/elements/1.1/">
            {identifier_xml}<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
            {description_xml}{subject_xml}
            </metadata><manifest>
            <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="c1"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/one.xhtml",
            "<html><body><h1>正文</h1></body></html>",
        )
