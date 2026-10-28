"""The single-file bundle must behave exactly like the source bot."""
import importlib.util
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import bundle as bundler  # noqa: E402

from pokergym.agent import TableInfo  # noqa: E402
from pokergym.bots import BOT_REGISTRY, TagBot  # noqa: E402
from pokergym.rules import BASELINE_RULES  # noqa: E402
from pokergym.tournament import run_tournament  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _observations(n=2):
    class Rec:
        def __init__(self, b):
            self.b, self.seen = b, []

        def reset(self, t):
            self.b.reset(t)

        def act(self, o):
            self.seen.append(o)
            return self.b.act(o)

    seen = []
    for seed in range(n):
        recs = [Rec(BOT_REGISTRY[k]()) for k in ("tag", "lag", "shortstack", "icm", "adaptive", "heuristic", "random", "call")]
        run_tournament(recs, BASELINE_RULES, seed=seed)
        for r in recs:
            seen.extend(r.seen)
    return seen


@pytest.mark.parametrize("spec,cls", [("tag", "TagBot"), ("adaptive", "AdaptiveBot"), ("icm", "IcmBot"),
                                      (os.path.join(ROOT, "examples", "my_bot.py") + ":MyBot", "MyBot")])
def test_bundle_matches_source_decisions(tmp_path, spec, cls):
    src, cls_name = bundler.bundle(spec)
    assert cls_name == cls
    path = tmp_path / "b.py"
    path.write_text(src)
    mod = _load(str(path), f"bundle_{cls}")
    assert not any(line.startswith(("from pokergym", "import pokergym")) for line in src.splitlines())
    bundled = getattr(mod, cls)()
    if ":" in spec:
        from pokergym.gym import load_bot_class

        orig = load_bot_class(spec)()
    else:
        orig = BOT_REGISTRY[spec]()
    bundled.reset(mod.TableInfo(seat=0, num_players=8, starting_stack=2000, rules_name="x", seed=7))
    orig.reset(TableInfo(seat=0, num_players=8, starting_stack=2000, rules_name="x", seed=7))
    for o in _observations()[:1200]:
        a, b = orig.act(o), bundled.act(o)
        assert (int(a.kind), a.amount) == (int(b.kind), b.amount), (spec, a, b)
    assert mod.preflop_equity(48, 49, 1) > 0.84  # embedded table works


def test_bundle_cli_writes_and_smokes(tmp_path):
    out = tmp_path / "sub" / "bot.py"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "bundle.py"), "--bot", "tag", "--out", str(out)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 illegal, 0 errors" in r.stdout
    assert out.exists() and out.stat().st_size < 1_000_000
    r2 = subprocess.run([sys.executable, str(out)], capture_output=True, text=True)
    assert r2.returncode == 0 and "self-test action" in r2.stdout


def test_bundle_rejects_name_collisions(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from pokergym.agent import CHECK, FOLD\n"
                   "def card_str(x): return 'collides with cards.card_str'\n"
                   "class B:\n    def reset(self, t): pass\n    def act(self, o): return CHECK if o.can_check else FOLD\n")
    with pytest.raises(SystemExit, match="collision"):
        bundler.bundle(f"{bad}:B")


def test_source_tag_unchanged_by_bundling():
    """Guard: bundling must not mutate the importable package."""
    assert TagBot.__module__ == "pokergym.bots.sparring"
