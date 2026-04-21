from __future__ import annotations

import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path


def test_distribution_artifacts_include_controlmesh_runtime(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = tmp_path / "dist"
    uv_bin = shutil.which("uv")
    assert uv_bin is not None
    project_version = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]

    subprocess.run(
        [uv_bin, "build", "--out-dir", str(out_dir)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    sdist_path = out_dir / f"controlmesh-{project_version}.tar.gz"
    wheel_path = out_dir / f"controlmesh-{project_version}-py3-none-any.whl"
    assert sdist_path.exists()
    assert wheel_path.exists()

    with tarfile.open(sdist_path) as sdist:
        sdist_hits = [name for name in sdist.getnames() if "controlmesh_runtime/" in name]
    with zipfile.ZipFile(wheel_path) as wheel:
        wheel_hits = [name for name in wheel.namelist() if name.startswith("controlmesh_runtime/")]

    assert sdist_hits
    assert wheel_hits
