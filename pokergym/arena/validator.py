"""Host side of submission validation.

Copies nothing from the research code into the sandbox: the runner
(``kit/validate_runner.py``) is part of the competitor's kit and is executed
under the isolation policy with a wall-clock limit, so a hung or malicious
submission cannot hang the host.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field

from . import isolation

SIZE_LIMIT = 100 * 1024 * 1024  # rule 3.7

DEFAULT_CONFIG = {
    "tables": 6,            # complete tournaments per mode (x2 modes)
    "deadline_ms": 1.0,     # rule 3.7
    "hard_ms": 200,         # watchdog: a decision this slow is treated as hung (REHEARSAL value)
    "max_timeout_frac": 0.02,  # REHEARSAL acceptance threshold; the organizer's is unknown
    "max_startup_s": 10.0,     # REHEARSAL
    "wall_timeout_s": 180.0,   # host kills the validator process after this
}


@dataclass
class ValidationReport:
    accepted: bool
    stages: list[dict]
    metrics: dict
    sha256: str
    size_bytes: int
    seconds: float
    error: str | None = None
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def summary(self) -> str:
        lines = [f"{'ACCEPTED' if self.accepted else 'REJECTED'}  sha256 {self.sha256[:12]}  {self.size_bytes/1024:.1f} KB  {self.seconds:.1f}s"]
        for s in self.stages:
            lines.append(f"  [{'ok' if s['passed'] else 'FAIL'}] {s['name']:<10} {s['detail']}")
        if self.error:
            lines.append(f"  error: {self.error}")
        return "\n".join(lines)

    def stage_passed(self, name: str) -> bool:
        return any(s["name"] == name and s["passed"] for s in self.stages)


def sha256_file(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(bot_path: str, workspace: str, policy: isolation.Policy, config: dict | None = None,
             seed: int = 0) -> ValidationReport:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(config or {})
    cfg["seed"] = seed
    t0 = time.perf_counter()
    size = os.path.getsize(bot_path)
    digest = sha256_file(bot_path)
    stages: list[dict] = []
    if size > SIZE_LIMIT:
        stages.append({"name": "size", "passed": False, "detail": f"{size} bytes > 100 MB"})
        return ValidationReport(False, stages, {}, digest, size, time.perf_counter() - t0, config=cfg)
    stages.append({"name": "size", "passed": True, "detail": f"{size/1024:.1f} KB of 100 MB"})
    runner = os.path.join(workspace, "kit", "validate_runner.py")
    argv = [isolation.competitor_python(), "-I", "-S", runner, bot_path, json.dumps({k: v for k, v in cfg.items() if k != "wall_timeout_s"})]
    try:
        cp = isolation.run(policy, argv, cwd=workspace, timeout=cfg["wall_timeout_s"])
    except subprocess.TimeoutExpired:
        stages.append({"name": "games", "passed": False, "detail": f"validator exceeded {cfg['wall_timeout_s']:.0f}s wall clock: hung submission"})
        return ValidationReport(False, stages, {}, digest, size, time.perf_counter() - t0, error="hung", config=cfg)
    try:
        payload = json.loads(cp.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        err = (cp.stderr or cp.stdout)[-800:]
        stages.append({"name": "import", "passed": False, "detail": "validator crashed (see error)"})
        return ValidationReport(False, stages, {}, digest, size, time.perf_counter() - t0, error=err, config=cfg)
    stages.extend(payload["stages"])
    required = {"size", "import", "interface", "legality", "games", "errors", "timing"}
    passed = {s["name"] for s in stages if s["passed"]}
    return ValidationReport(required <= passed, stages, payload.get("metrics", {}), digest, size,
                            time.perf_counter() - t0, config=cfg)
