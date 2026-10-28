"""Enforceable isolation for the competitor's processes.

macOS: ``sandbox-exec`` with a generated profile that denies reading the
Poker Gym repository (research bots, hidden opponents, generator, this
module) and the challenge's host-only directories, and denies network.
Paths are resolved with ``realpath`` because the kernel sees ``/private/tmp``
where Python says ``/tmp``.

Other platforms: no kernel sandbox is available without Docker/bwrap, so
``run`` falls back to a *weak* mode (fresh env, ``python -I -S``, cwd set)
and records ``level="weak"`` in the challenge so a postmortem cannot claim
isolation it did not have.

The competitor's interpreter is the real binary behind ``sys.executable``
(outside the repo's ``.venv``), run with ``-I -S`` so neither the venv nor
user site-packages (where ``pokergym`` may be installed) are importable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

REPO_ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX_EXEC = shutil.which("sandbox-exec") or ("/usr/bin/sandbox-exec" if os.path.exists("/usr/bin/sandbox-exec") else None)


def competitor_python() -> str:
    """An interpreter that is not inside the repository."""
    cand = os.path.realpath(sys.executable)
    if not cand.startswith(REPO_ROOT + os.sep):
        return cand
    for name in ("python3.12", "python3.13", "python3.11", "python3"):
        p = shutil.which(name)
        if p and not os.path.realpath(p).startswith(REPO_ROOT + os.sep):
            return os.path.realpath(p)
    raise RuntimeError("no interpreter outside the repository found")


@dataclass
class Policy:
    deny_read: list[str] = field(default_factory=list)      # realpaths denied for read and write
    allow: list[str] = field(default_factory=list)          # informational (not denied)
    network: bool = False

    def profile(self) -> str:
        lines = ["(version 1)", "(allow default)"]
        if not self.network:
            lines.append("(deny network*)")
        for p in self.deny_read:
            rp = os.path.realpath(p)
            lines.append(f'(deny file-read* file-write* (subpath "{rp}"))')
        return "\n".join(lines) + "\n"


def level() -> str:
    return "sandbox-exec" if SANDBOX_EXEC and sys.platform == "darwin" else "weak"


def run(policy: Policy, argv: list[str], cwd: str, timeout: float | None = None, env: dict | None = None,
        profile_path: str | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    """Run ``argv`` under the policy. ``argv[0]`` should be ``competitor_python()``
    or a system binary. Raises ``subprocess.TimeoutExpired`` on timeout."""
    base_env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": cwd, "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1"}
    if env:
        base_env.update(env)
    if level() == "sandbox-exec":
        if profile_path is None:
            profile_path = os.path.join(cwd, ".sandbox.sb")
        with open(profile_path, "w") as f:
            f.write(policy.profile())
        cmd = [SANDBOX_EXEC, "-f", profile_path] + argv
    else:
        cmd = argv
    return subprocess.run(cmd, cwd=cwd, env=base_env, timeout=timeout, capture_output=capture, text=True)


def python_argv(script_or_code: str, *args: str, code: bool = False) -> list[str]:
    py = competitor_python()
    return [py, "-I", "-S", "-c" if code else script_or_code, *([script_or_code] if code else []), *args] if code \
        else [py, "-I", "-S", script_or_code, *args]


def self_test(policy: Policy, workspace: str, must_fail: list[str], must_pass: list[str]) -> dict:
    """Prove the policy from inside: every ``must_fail`` path is unreadable,
    every ``must_pass`` path is readable, ``pokergym`` is not importable,
    and the network is closed. Returns a dict for the challenge record."""
    probe = (
        "import sys, json, os\n"
        "out = {}\n"
        "for p in %r:\n"
        "    try:\n"
        "        open(p, 'rb').read(1) if os.path.isfile(p) else os.listdir(p)\n"
        "        out[p] = 'READABLE'\n"
        "    except Exception as e:\n"
        "        out[p] = type(e).__name__\n"
        "sys.path.insert(0, %r)\n"
        "try:\n"
        "    import pokergym\n"
        "    out['import_pokergym'] = 'IMPORTED'\n"
        "except Exception as e:\n"
        "    out['import_pokergym'] = type(e).__name__\n"
        "try:\n"
        "    import socket\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2).close()\n"
        "    out['network'] = 'OPEN'\n"
        "except Exception as e:\n"
        "    out['network'] = type(e).__name__\n"
        "print(json.dumps(out))\n"
    ) % (must_fail + must_pass, REPO_ROOT)
    cp = run(policy, [competitor_python(), "-I", "-S", "-c", probe], cwd=workspace, timeout=30)
    import json

    try:
        res = json.loads(cp.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {"level": level(), "ok": False, "error": cp.stderr[-500:]}
    ok = all(res[p] != "READABLE" for p in must_fail) and all(res[p] == "READABLE" for p in must_pass) \
        and res["import_pokergym"] != "IMPORTED" and res["network"] != "OPEN"
    return {"level": level(), "ok": ok, "probe": res}
