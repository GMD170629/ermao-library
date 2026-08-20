"""Folder-tree helpers for library HTTP adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _path_tree(paths: list[str], root_label: str) -> dict[str, Any]:
    root: dict[str, Any] = {
        "name": root_label,
        "path": root_label,
        "type": "folder",
        "children": [],
        "fileCount": 0,
        "sizeBytes": 0,
    }
    children_by_path: dict[str, dict[str, Any]] = {root_label: root}
    for raw_path in sorted({path for path in paths if path}):
        parts = [part for part in Path(raw_path).parts if part not in {"/", ""}]
        current = root
        current_path = root_label
        for index, part in enumerate(parts):
            current_path = f"{current_path}/{part}"
            node = children_by_path.get(current_path)
            if not node:
                node = {
                    "name": part,
                    "path": current_path,
                    "type": "file" if index == len(parts) - 1 else "folder",
                    "children": [],
                    "fileCount": 0,
                    "sizeBytes": 0,
                }
                children_by_path[current_path] = node
                current["children"].append(node)
            current = node
            current["fileCount"] = int(current.get("fileCount") or 0) + (
                1 if index == len(parts) - 1 else 0
            )
    return root


def _source_folder_preview(root_path: str) -> dict[str, Any]:
    path = Path(root_path)
    readable = path.exists() and path.is_dir() and os.access(path, os.R_OK)
    writable = path.exists() and path.is_dir() and os.access(path, os.W_OK)
    children: list[dict[str, Any]] = []
    if readable:
        try:
            for child in sorted(
                path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
            )[:80]:
                try:
                    stat = child.stat()
                    children.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "type": "folder" if child.is_dir() else "file",
                            "sizeBytes": 0 if child.is_dir() else stat.st_size,
                            "mtimeMs": int(stat.st_mtime * 1000),
                        }
                    )
                except OSError:
                    children.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "type": "unknown",
                            "sizeBytes": 0,
                            "error": "无法读取",
                        }
                    )
        except OSError:
            readable = False
    return {"readable": readable, "writable": writable, "children": children}
