"""Build and prepare an isolated real protocol-2 code update; no production switches."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

sys.path[:0] = ["/app/storage/runtime/apps/api-python", "/tooling/scripts"]
from app.modules.updates.application.models import ReleaseReference
from app.modules.updates.infrastructure.preparation_worker import PreparationWorker

storage = Path("/app/storage")
fault = globals()["fault"]
assert (storage / ".acceptance-volume").is_file()
current = json.loads((storage / "runtime/application.json").read_text())["version"]
major, minor, patch = map(int, current.split("."))
target = f"{major}.{minor}.{patch + 1}"
root = Path("/tmp") / f"startup-update-{target}"
image = root / "image"
shutil.copytree("/opt/shuku-image", image, symlinks=True)
original = json.loads((image / "application.json").read_text())["version"]
for name in (
    "application.json",
    "apps/web/package.json",
    "apps/web/public/sw.js",
    "apps/api-python/pyproject.toml",
    "apps/api-python/app/core/config.py",
):
    p = image / name
    p.write_text(p.read_text().replace(original, target))
if fault == "recovery":
    p = image / "apps/api-python/app/services/metadata_lookup_queue.py"
    p.write_text(
        p.read_text()
        + "\n"
        + Path("/tooling/scripts/fixtures/metadata-startup-faults.py").read_text()
    )
elif fault == "worker":
    (image / "apps/api-python/app/worker/main.py").write_text(
        "if __name__ == '__main__':\n    raise RuntimeError('acceptance invalid worker update')\n"
    )
spec = importlib.util.spec_from_file_location(
    "startup_builder", "/tooling/scripts/build-application-package.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
output = root / "output"
reference = ReleaseReference.model_validate(
    builder.build_release(
        image,
        output,
        Path("/opt/shuku-dependency-seed"),
        Path("/opt/shuku-launcher/environment.json"),
    )
)


class LocalArtifacts:
    def chunks(self, url, size, timeout):
        # Only transport is replaced; digest, archive, plan and installer checks run.
        with (output / url.rsplit("/", 1)[-1]).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk


worker = PreparationWorker(storage, LocalArtifacts(), reference.environment)
try:
    worker.submit(reference)
    worker.thread.join(120)
    state = worker.status()
    assert state.phase == "ready", state
    worker.install(
        target,
        reference.sha256,
        reference.environment,
        current,
        state.summary.plan_sha256,
    )
    print(json.dumps({"version": target, "sha256": reference.sha256, "fault": fault}))
finally:
    worker.close()
