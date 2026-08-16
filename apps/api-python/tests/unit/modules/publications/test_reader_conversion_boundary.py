from pathlib import Path


def test_reader_publication_call_graph_does_not_reference_import_conversion() -> None:
    api_root = Path(__file__).resolve().parents[4]
    active_reader_paths = (
        api_root / "app" / "modules" / "reader",
        api_root / "app" / "modules" / "publications",
        api_root / "app" / "bootstrap" / "publications.py",
    )

    violations: list[str] = []
    for active_path in active_reader_paths:
        python_files = (
            active_path.rglob("*.py") if active_path.is_dir() else (active_path,)
        )
        for python_file in python_files:
            source = python_file.read_text(encoding="utf-8")
            if "convert_to_epub" in source or "app.services.text_conversion" in source:
                violations.append(str(python_file.relative_to(api_root)))

    assert violations == []
