"""Actual offline uv operations with small packages; no Web/container build."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import test_dependency_preparation as prepare

from app.modules.updates.application.models import UpdateError
from app.modules.updates.infrastructure.install_plan import validate_prepared
from app.modules.updates.presentation.http import use_cases
from shuku_dependencies import generate, installed_records

packages = prepare.packages
program_package = prepare.program_package
downloads = prepare.downloads

sys.path.insert(0, str(Path(__file__).resolve().parents[6] / "scripts"))
from dependency_install import DependencyInstallation
from dependency_update_fixture import wheel

UV = os.environ.get("SHUKU_TEST_UV", shutil.which("uv") or "uv")


@pytest.fixture()
def installed(packages):
    assert subprocess.check_output([UV, "--version"], text=True).startswith(
        "uv 0.11.29"
    )
    python = packages.storage / "dependencies/python/bin/python"
    wheels = []
    for name in ("a", "b", "c", "d"):
        files = {f"shared/{name}.py": b"VALUE = 1\n"}
        if name == "a":
            files["a-1.dist-info/entry_points.txt"] = (
                b"[console_scripts]\na-cli = shared.a:main\n"
            )
        if name == "b":
            files["shared/obsolete.py"] = b"old"
        wheels.append(wheel(packages.seed / "wheels", name, "1", files))
    subprocess.run(
        [
            UV,
            "--offline",
            "--no-cache",
            "--no-config",
            "--no-python-downloads",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--no-index",
            "--no-build",
            *map(str, wheels),
        ],
        check=True,
    )
    local = generate(packages.storage / "runtime", packages.seed)
    (packages.storage / "dependencies/installed.json").write_text(
        json.dumps({**local, "python_records": installed_records(python.parent.parent)})
    )
    current = packages.storage / "runtime/application.json"
    value = json.loads(current.read_text())
    value["version"] = "1.0.0"
    current.write_text(json.dumps(value))
    return packages


def keep_snapshot(storage):
    result = {}
    for p in storage.rglob("*"):
        if p.is_file() and (
            "shared/a.py" in str(p)
            or "shared/d.py" in str(p)
            or "/node_modules/a/" in str(p)
            or "/node_modules/d/" in str(p)
        ):
            result[str(p)] = (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino)
    return result


def prepare_install(packages, downloads, monkeypatch):
    packages.build()
    downloads.updates.prepare(True, "1.0.4")
    state = prepare.finish(downloads)
    assert state.phase == "ready", state
    downloads.updates.install(
        True, "1.0.4", packages.reference.sha256, state.summary.plan_sha256
    )
    assert downloads.worker.status().phase == "requested"
    validate_prepared(
        packages.storage,
        state,
        downloads.worker.environment,
        state.summary.plan_sha256,
        extract=True,
    )
    request = json.loads(
        (packages.storage / "update-tmp/install-request.json").read_text()
    )
    installer = DependencyInstallation(
        packages.storage, request, state.model_dump(), packages.fixed, uv=UV
    )
    return installer


@pytest.mark.parametrize("change", ["mixed", "code", "remove", "same-version"])
def test_real_offline_install(installed, downloads, monkeypatch, change):
    p = installed
    before = keep_snapshot(p.storage)
    if change in ("mixed", "remove"):
        (p.seed / "wheels/c-1-py3-none-any.whl").unlink()
        shutil.rmtree(p.image / "node_modules/c")
    if change in ("mixed", "same-version"):
        (p.seed / "wheels/b-1-py3-none-any.whl").unlink()
        version = "2" if change == "mixed" else "1"
        wheel(p.seed / "wheels", "b", version, {"shared/b.py": b"VALUE = 2\n"})
        prepare.node(p.image, "b", version)
    if change == "mixed":
        wheel(p.seed / "wheels", "e", "1", {"shared/e.py": b"VALUE = 1\n"})
        prepare.node(p.image, "e", "1")
    installer = prepare_install(p, downloads, monkeypatch)
    # Make a full reinstall impossible: only prepared selected artifacts survive.
    shutil.rmtree(p.seed)
    shutil.rmtree(p.output)
    (p.storage / "runtime/deleted-code.py").write_text("old")
    installer.synchronize_code()
    installer.apply()
    assert before == keep_snapshot(p.storage)
    assert not (p.storage / "runtime/deleted-code.py").exists()
    records = {r["name"]: r for r in installer.result["python_records"]}
    if change in ("mixed", "same-version"):
        assert (
            not next(
                (p.storage / "dependencies/python").glob("lib/python*/site-packages")
            )
            .joinpath("shared/obsolete.py")
            .exists()
        )
        assert (
            subprocess.check_output(
                [
                    str(installer.python),
                    "-c",
                    "from shared.b import VALUE; print(VALUE)",
                ],
                text=True,
            ).strip()
            == "2"
        )
    if change == "mixed":
        assert set(records) == {"a", "b", "d", "e", "demo"}
        assert records["b"]["version"] == "2"
    log = p.storage / "update-tmp/installation.log"
    operations = log.read_text() if log.exists() else ""
    assert '"a"' not in operations and '"d"' not in operations
    if change == "code":
        assert "dependency_operation=install" not in operations
        assert "dependency_operation=uninstall" not in operations
    if change == "remove":
        assert "dependency_operation=install" not in operations
        assert 'packages=["c"]' in operations
    assert (
        json.loads((p.storage / "dependencies/installed.json").read_text())["identity"]
        != installer.target["identity"]
        or change == "code"
    )
    print("Actual uv log:", operations)


@pytest.mark.parametrize("damage", ["plan", "baseline", "missing", "identity"])
def test_confirmation_revalidates_before_reservation(installed, downloads, damage):
    p = installed
    prepare.change_target(p)
    downloads.updates.prepare(True, "1.0.4")
    state = prepare.finish(downloads)
    work = p.storage / "update-tmp/prepared"
    if damage == "plan":
        plan = json.loads((work / "plan.json").read_text())
        plan["difference"]["remove"] = []
        (work / "plan.json").write_text(json.dumps(plan))
    elif damage == "baseline":
        (p.storage / "runtime/node_modules/a/index.js").write_text("changed")
    elif damage == "missing":
        (
            work / json.loads((work / "release.json").read_text())["code"]["filename"]
        ).unlink()
    else:
        (work / "release.json").write_text("{}")
    before = prepare.snapshot(p.storage)
    if damage in {"plan", "baseline"}:
        assert (
            downloads.updates.install(True, "1.0.4", p.reference.sha256, None).phase
            == "requested"
        )
        assert prepare.snapshot(p.storage) == before
        return
    with pytest.raises(UpdateError):
        downloads.updates.install(
            True, "1.0.4", p.reference.sha256, state.summary.plan_sha256
        )
    assert not (p.storage / "update-tmp/install-request.json").exists()
    assert prepare.snapshot(p.storage) == before


def test_api_confirmation_and_mutex(client, db_session, installed, downloads):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    p = installed
    prepare.change_target(p)
    downloads.updates.prepare(True, "1.0.4")
    state = prepare.finish(downloads)
    user = _create_user(db_session, email="d3@example.com", role="admin")
    _login(client, user.email)
    client.app.dependency_overrides[use_cases] = lambda: downloads.updates
    try:
        payload = {
            "version": "1.0.4",
            "sha256": p.reference.sha256,
            "plan_sha256": state.summary.plan_sha256,
        }
        assert (
            client.post(
                "/api/updates/install", json={**payload, "sha256": "0" * 64}
            ).status_code
            == 400
        )
        assert client.post("/api/updates/install", json=payload).status_code == 202
        assert client.post("/api/updates/install", json=payload).status_code == 409
        assert (
            client.post("/api/updates/prepare", json={"version": "1.0.4"}).status_code
            == 409
        )
        assert (p.storage / "update-tmp/install-request.json").exists()
    finally:
        client.app.dependency_overrides.pop(use_cases, None)


def test_node_parent_removal_preserves_nested_instance_and_links(
    installed, downloads, monkeypatch
):
    p = installed
    for root in (p.image, p.storage / "runtime"):
        prepare.node(
            root, "@scope/same", "1", "node_modules/b/node_modules/@scope/same"
        )
        prepare.node(
            root, "@scope/same", "2", "node_modules/d/node_modules/@scope/same"
        )
        (root / "node_modules/alias").symlink_to("b/node_modules/@scope/same")
    local = generate(p.storage / "runtime", p.seed)
    (p.storage / "dependencies/installed.json").write_text(
        json.dumps(
            {
                **local,
                "python_records": installed_records(p.storage / "dependencies/python"),
            }
        )
    )
    for name in ("package.json", "index.js"):
        (p.image / "node_modules/b" / name).unlink()
    nested_files = [
        file
        for parent in ("b", "d")
        for file in (p.storage / f"runtime/node_modules/{parent}/node_modules").rglob(
            "*"
        )
        if file.is_file()
    ]
    before = {
        file: (file.read_bytes(), file.stat().st_ino, file.stat().st_mtime_ns)
        for file in nested_files
    }
    installer = prepare_install(p, downloads, monkeypatch)
    installer.synchronize_code()
    installer.apply()
    assert before == {
        file: (file.read_bytes(), file.stat().st_ino, file.stat().st_mtime_ns)
        for file in nested_files
    }
    assert (
        p.storage / "runtime/node_modules/alias/index.js"
    ).read_text() == 'module.exports="1"'
    assert not (p.storage / "runtime/node_modules/b/package.json").exists()
    assert (
        len([x for x in installer.result["packages"] if x["name"] == "@scope/same"])
        == 2
    )


def test_dependency_failure_keeps_old_record_and_incomplete_marker(
    installed, downloads, monkeypatch
):
    from container_install import Installation
    from dependency_install import DependencyInstallError

    p = installed
    (p.seed / "wheels/b-1-py3-none-any.whl").unlink()
    wheel(p.seed / "wheels", "b", "2", {"shared/b.py": b"VALUE=2\n"})
    executor = prepare_install(p, downloads, monkeypatch)
    previous = (p.storage / "dependencies/installed.json").read_bytes()
    executor.uv = "/usr/bin/false"
    (p.storage / "runtime/.initialized").write_text("1\n")
    installer = Installation(p.storage)
    installer.state = downloads.worker.status().model_dump()
    installer.dependencies = executor
    with pytest.raises(DependencyInstallError, match="DEPENDENCY_OPERATION_FAILED"):
        installer.synchronize()
    installer.fail("DEPENDENCY_OPERATION_FAILED")
    assert (p.storage / "update-tmp/installation-incomplete").exists()
    assert (p.storage / "dependencies/installed.json").read_bytes() == previous
    assert installer.state["failed_phase"] == "copying"
    assert not (p.storage / "update-tmp/worker-ready").exists()


@pytest.mark.parametrize("damage", ["baseline", "artifact"])
def test_fixed_entry_rechecks_after_confirmation(
    installed, downloads, monkeypatch, damage
):
    from dependency_install import DependencyInstallError

    p = installed
    prepare.node(p.image, "b", "2")
    executor = prepare_install(p, downloads, monkeypatch)
    if damage == "baseline":
        (p.storage / "runtime/node_modules/a/index.js").write_text("drift")
    else:
        artifact = executor.new["node:node_modules/b"]["artifact"]["filename"]
        (executor.work / artifact).write_bytes(b"bad")
    before = prepare.snapshot(p.storage)
    if damage == "artifact":
        with pytest.raises(DependencyInstallError, match="DIGEST_MISMATCH"):
            executor.recheck()
    else:
        executor.recheck()
    assert prepare.snapshot(p.storage) == before
    assert not (p.storage / "update-tmp/installation-incomplete").exists()


@pytest.mark.parametrize("collision", ["data", "script"])
def test_wheel_installation_paths_cannot_overwrite_keep(
    installed, downloads, collision
):
    p = installed
    (p.seed / "wheels/b-1-py3-none-any.whl").unlink()
    # .data files and normal purelib files map to the same final site-packages path.
    files = (
        {"b-2.data/data/lib/python3.11/site-packages/shared/a.py": b"overwrite"}
        if collision == "data"
        else {
            "b-2.dist-info/entry_points.txt": b"[console_scripts]\na-cli = shared.b:main\n"
        }
    )
    wheel(p.seed / "wheels", "b", "2", files)
    p.build()
    downloads.updates.prepare(True, "1.0.4")
    state = prepare.finish(downloads)
    before = prepare.snapshot(p.storage)
    with pytest.raises(UpdateError, match="DEPENDENCY_OWNERSHIP_CONFLICT"):
        downloads.updates.install(
            True, "1.0.4", p.reference.sha256, state.summary.plan_sha256
        )
    assert prepare.snapshot(p.storage) == before
    assert not (p.storage / "update-tmp/install-request.json").exists()


@pytest.mark.parametrize("transition", ["link", "file"])
def test_node_directory_type_transition(installed, downloads, monkeypatch, transition):
    p = installed
    runtime = p.storage / "runtime"
    if transition == "file":
        for root in (p.image, runtime):
            data = root / "node_modules/b/data"
            data.mkdir()
            (data / "old.txt").write_text("obsolete")
    local = generate(runtime, p.seed)
    record = p.storage / "dependencies/installed.json"
    record.write_text(
        json.dumps(
            {
                **local,
                "python_records": installed_records(p.storage / "dependencies/python"),
            }
        )
    )
    previous_record = record.read_bytes()
    before = keep_snapshot(p.storage)
    protected = {
        name: (p.storage / name).read_bytes()
        for name in (
            "database/shuku.sqlite3",
            "secrets/session-secret",
            "covers/book",
            "books/book",
            "configuration",
        )
    }
    (runtime / ".initialized").write_text("1\n")
    # No removed leaf belongs to this directory: the installer must leave it alone.
    unrelated = runtime / "node_modules/a/empty"
    unrelated.mkdir()
    unrelated_stat = unrelated.stat()
    if transition == "link":
        shutil.rmtree(p.image / "node_modules/b")
        prepare.node(p.image, "b", "2", "node_modules/.pnpm/b@2/node_modules/b")
        (p.image / "node_modules/b").symlink_to(".pnpm/b@2/node_modules/b")
    else:
        shutil.rmtree(p.image / "node_modules/b/data")
        (p.image / "node_modules/b/data").write_text("new regular file")
    installer = prepare_install(p, downloads, monkeypatch)
    installer.synchronize_code()
    installer.apply()
    if transition == "link":
        link = runtime / "node_modules/b"
        assert link.is_symlink()
        assert os.readlink(link) == ".pnpm/b@2/node_modules/b"
        assert (link / "index.js").read_text() == 'module.exports="2"'
        assert json.loads((link / "package.json").read_text())["version"] == "2"
    else:
        data = runtime / "node_modules/b/data"
        assert data.is_file() and not data.is_symlink()
        assert data.read_text() == "new regular file"
    assert installer.result["identity"] == installer.target["identity"]
    assert before == keep_snapshot(p.storage)
    assert record.read_bytes() == previous_record  # Only later health checks commit it.
    assert (runtime / ".initialized").read_text() == "1\n"
    assert protected == {name: (p.storage / name).read_bytes() for name in protected}
    assert (unrelated.stat().st_ino, unrelated.stat().st_mtime_ns) == (
        unrelated_stat.st_ino,
        unrelated_stat.st_mtime_ns,
    )
    print(
        f"Node directory -> {transition}: uid={os.getuid()}, target verified; keep bytes/inode/mtime unchanged"
    )


@pytest.mark.parametrize("transition", ["file", "link"])
def test_node_type_conflict_with_kept_nested_instance_rejected(
    installed, downloads, transition
):
    p = installed
    for root in (p.image, p.storage / "runtime"):
        prepare.node(root, "nested", "1", "node_modules/b/data/node_modules/nested")
    local = generate(p.storage / "runtime", p.seed)
    (p.storage / "dependencies/installed.json").write_text(
        json.dumps(
            {
                **local,
                "python_records": installed_records(p.storage / "dependencies/python"),
            }
        )
    )
    p.build()
    # A conflicting manifest cannot be represented by a real filesystem. Inject
    # it at the HTTP asset boundary, retaining the nested instance as a keep target.
    manifest_path = p.output / p.reference.filename
    manifest = json.loads(manifest_path.read_text())
    dependencies = manifest["dependencies"]
    if transition == "file":
        package = next(
            x for x in dependencies["packages"] if x["location"] == "node_modules/b"
        )
        package["files"].append("node_modules/b/data")
    else:
        dependencies["node_links"].append(
            {"path": "node_modules/b/data", "target": "../a"}
        )
    dependencies["identity"] = prepare.canonical_digest(
        {k: v for k, v in dependencies.items() if k != "identity"}
    )
    manifest_path.write_text(json.dumps(manifest))
    p.reference = p.reference.model_copy(
        update={
            "size": manifest_path.stat().st_size,
            "sha256": prepare.digest(manifest_path),
        }
    )
    before = prepare.snapshot(p.storage)
    keep = keep_snapshot(p.storage)
    nested = p.storage / "runtime/node_modules/b/data/node_modules/nested/index.js"
    nested_before = (
        nested.read_bytes(),
        nested.stat().st_ino,
        nested.stat().st_mtime_ns,
    )
    downloads.updates.prepare(True, "1.0.4")
    state = prepare.finish(downloads)
    assert state.phase == "failed"
    assert state.error == "INVALID_MANIFEST"
    assert prepare.snapshot(p.storage) == before
    assert keep_snapshot(p.storage) == keep
    assert (
        nested.read_bytes(),
        nested.stat().st_ino,
        nested.stat().st_mtime_ns,
    ) == nested_before
    assert not (p.storage / "update-tmp/install-request.json").exists()
    assert not (p.storage / "update-tmp/installation-incomplete").exists()


def test_missing_fixed_install_capability_refuses_request(installed, downloads):
    p = installed
    p.build()
    downloads.updates.prepare(True, "1.0.4")
    state = prepare.finish(downloads)
    downloads.updates.install_protocol = 0
    before = prepare.snapshot(p.storage)
    with pytest.raises(UpdateError, match="INSTALLATION_NOT_SUPPORTED"):
        downloads.updates.install(
            True, "1.0.4", p.reference.sha256, state.summary.plan_sha256
        )
    assert prepare.snapshot(p.storage) == before
    assert not (p.storage / "update-tmp/install-request.json").exists()


def test_code_only_install_does_not_rescan_kept_python(
    installed, downloads, monkeypatch
):
    p = installed
    executor = prepare_install(p, downloads, monkeypatch)
    site = next((p.storage / "dependencies/python").glob("lib/python*/site-packages"))
    (site / "shared/a.py").unlink()
    before = (p.storage / "dependencies/installed.json").read_bytes()
    executor.recheck()
    executor.synchronize_code()
    executor.apply()
    assert executor.result["python_records"] == json.loads(before)["python_records"]
    assert not (site / "shared/a.py").exists()
