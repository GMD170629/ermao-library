from __future__ import annotations

import sys


def test_python_runtime_matches_production() -> None:
    assert sys.version_info[:2] == (3, 11), (
        "后端测试必须使用与生产镜像一致的 Python 3.11，"
        f"当前为 {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
