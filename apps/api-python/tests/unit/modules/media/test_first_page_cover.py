from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app.modules.media.infrastructure import page_image
from app.modules.media.infrastructure.first_page_cover import FilesystemFirstPageCover
from app.modules.media.infrastructure.page_image import (
    PageImageRenderer,
    ResourcePreviewRenderCoordinator,
)


def test_real_pdf_renders_only_physical_page_zero(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "pages.pdf"
    with (
        Image.new("RGB", (100, 200), "red") as first,
        Image.new("RGB", (100, 200), "blue") as second,
    ):
        first.save(path, format="PDF", save_all=True, append_images=[second])
    pages = []
    closed = []
    get_page = pdfium.PdfDocument.__getitem__

    def getitem(self, index):
        pages.append(index)
        return get_page(self, index)

    monkeypatch.setattr(pdfium.PdfDocument, "__getitem__", getitem)
    # Track native lifetime as well as visible output.
    for cls in (pdfium.PdfDocument, pdfium.PdfPage, pdfium.PdfBitmap):
        original = cls.close

        def close(self, *args, _original=original, _name=cls.__name__, **kwargs):
            if self.raw:
                closed.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "close", close)
    renderer = PageImageRenderer(ResourcePreviewRenderCoordinator())
    content = FilesystemFirstPageCover(renderer).extract(path=path, source_format="PDF")
    assert content is not None
    with Image.open(BytesIO(content)) as image:
        red, green, blue = image.convert("RGB").getpixel((30, 30))
        assert red > 200 and green < 35 and blue < 35
        assert max(image.size) <= 480
    assert pages == [0]
    assert closed[:3] == ["PdfBitmap", "PdfPage", "PdfDocument"]


@pytest.mark.parametrize("failure", ["open", "render", "bitmap", "empty"])
def test_pdf_failure_releases_resources_and_render_slot(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    closed = []

    class Bitmap:
        def to_pil(self):
            raise RuntimeError("bitmap conversion failed")

        def close(self):
            closed.append("bitmap")

    class Page:
        def render(self, *, scale):
            if failure == "render":
                raise RuntimeError("render failed")
            return Bitmap()

        def close(self):
            closed.append("page")

    class Document:
        def __len__(self):
            return 0 if failure == "empty" else 2

        def __getitem__(self, index):
            assert index == 0
            return Page()

        def close(self):
            closed.append("document")

    def document(path):
        if failure == "open":
            raise RuntimeError("open failed")
        return Document()

    monkeypatch.setattr(
        page_image, "import_module", lambda name: SimpleNamespace(PdfDocument=document)
    )
    coordinator = ResourcePreviewRenderCoordinator()
    extractor = FilesystemFirstPageCover(PageImageRenderer(coordinator))
    assert extractor.extract(path=tmp_path / "book.pdf", source_format="PDF") is None
    assert (
        closed
        == {
            "open": [],
            "empty": ["document"],
            "render": ["page", "document"],
            "bitmap": ["bitmap", "page", "document"],
        }[failure]
    )
    # A subsequent nonblocking acquire proves the failed attempt returned its slot.
    assert coordinator._pdf_slots.acquire(blocking=False)
    coordinator._pdf_slots.release()
