"""Verify and compile the complete pinned release without model-source edits."""

import hashlib
import json
from pathlib import Path
import subprocess

root = Path("/opt/richmond")
expected = json.loads(
    Path(
        "/app/src/coworld/research_sources/richmond_2023/source-manifest.json"
    ).read_bytes()
)
for name, entry in expected.items():
    checkout = root / name
    assert (
        subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        == entry["revision"]
    )
    assert not subprocess.check_output(
        ["git", "-C", str(checkout), "status", "--porcelain"], text=True
    ).strip()
    for relative, digest in entry["sha256"].items():
        assert (
            hashlib.sha256((checkout / relative).read_bytes()).hexdigest() == digest
        ), (name, relative)
assert (root / "benchmark/src/main.cu").read_bytes() == Path(
    "/app/src/coworld/research_sources/richmond_2023/main.cu"
).read_bytes()
subprocess.run(
    [
        "cmake",
        str(root / "benchmark"),
        "-B",
        str(root / "build"),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_CUDA_ARCHITECTURES=86;89;90",
        "-DFLAMEGPU_ROOT=" + str(root / "engine"),
        "-DFLAMEGPU_SEATBELTS=OFF",
        "-DFLAMEGPU_SHARE_USAGE_STATISTICS=OFF",
        "-DBUILD_TESTS=OFF",
    ],
    check=True,
    timeout=600,
)
subprocess.run(
    ["cmake", "--build", str(root / "build"), "-j", "8"], check=True, timeout=3000
)
for checkout in [root / "benchmark", root / "engine"]:
    subprocess.run(
        ["git", "-C", str(checkout), "diff", "--exit-code", "HEAD", "--"], check=True
    )
(root / "bin").mkdir()
binary = root / "bin/submodel-benchmark"
binary.write_bytes((root / "build/bin/Release/submodel-benchmark").read_bytes())
binary.chmod(0o755)
subprocess.run(
    [
        "nvcc",
        "-std=c++17",
        "/app/tools/richmond_gpu_probe.cu",
        "-o",
        str(root / "bin/gpu-probe"),
    ],
    check=True,
    timeout=120,
)
qualification = {
    "source": json.loads(
        Path(
            "/app/src/coworld/research_sources/richmond_2023/catalog-entry.json"
        ).read_bytes()
    ),
    "original_sources": expected,
    "cuda": subprocess.check_output(["nvcc", "--version"], text=True),
    "compiler": subprocess.check_output(["g++", "--version"], text=True),
    "cmake_cache": (root / "build/CMakeCache.txt").read_text(),
    "architectures": [86, 89, 90],
    "seatbelts": False,
    "model_source_changes": [],
    "files_sha256": {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ["bin", "engine/include"]
        for p in sorted((root / folder).rglob("*"))
        if p.is_file()
    },
}
(root / "qualification.json").write_text(json.dumps(qualification, indent=2) + "\n")
