from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.modules.media.infrastructure.resource_preview import (
    ResourcePreviewRenderCoordinator,
)


def test_rejects_an_invalid_pdf_render_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        ResourcePreviewRenderCoordinator(max_concurrent_pdf_renders=0)


def test_serializes_pdf_render_slots() -> None:
    coordinator = ResourcePreviewRenderCoordinator(max_concurrent_pdf_renders=1)
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def render() -> None:
        nonlocal active, maximum_active
        with coordinator.pdf_render_slot():
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.01)
            with state_lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda _: render(), range(6)))

    assert maximum_active == 1
