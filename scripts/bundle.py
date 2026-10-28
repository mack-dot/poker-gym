"""Bundle a bot and everything it imports from pokergym into ONE Python file.

    python scripts/bundle.py --bot examples/my_bot.py:MyBot --out submission/bot.py
    python scripts/bundle.py --bot tag --out submission/tag.py --no-smoke

The output has no imports outside the standard library, embeds the preflop
equity table, defines ``BOT_CLASS`` (the bot) and keeps ``build_observation``
/ ``action_from_text`` / ``action_to_text`` from ``pokergym.bridge`` so the
tournament-day adapter has everything in one place. Size is reported against
the 100 MB limit (rule 3.7).

After writing, the bundle is loaded in a fresh module and smoke-tested: the
bundled bot plays two eight-player tournaments against the sparring roster
(through a tiny adapter, which is exactly the shape of the day's adapter) and
must produce zero illegal actions and zero errors.

How it works: modules are inlined in dependency order into one namespace.
Relative/``pokergym.*`` imports are deleted (names are now globals);
``import x as ALIAS`` of a module becomes a ``SimpleNamespace`` shim; any
top-level name defined by two different modules aborts the bundle.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "pokergym")
sys.path.insert(0, ROOT)

ALWAYS = ["pokergym.bridge"]  # the day's adapter lives here; always ship it


# --------------------------------------------------------------------------
# module graph
# --------------------------------------------------------------------------
def mod_path(name: str) -> str | None:
    rel = name.split(".")
    if rel[0] != "pokergym":
        return None
    p = os.path.join(ROOT, *rel)
    if os.path.isdir(p):
        return os.path.join(p, "__init__.py")
    if os.path.exists(p + ".py"):
        return p + ".py"
    return None


def resolve(node: ast.ImportFrom, current: str) -> str | None:
    """Absolute module name an ImportFrom refers to, or None if not ours."""
    if node.level == 0:
        return node.module if node.module and node.module.split(".")[0] == "pokergym" else None
    parts = current.split(".")
    is_pkg = mod_path(current) is not None and mod_path(current).endswith("__init__.py")
    base = parts if is_pkg else parts[:-1]
    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
    return ".".join(base + ([node.module] if node.module else []))


class Mod:
    def __init__(self, name: str, path: str):
        self.name, self.path = name, path
        self.src = open(path, encoding="utf-8").read()
        self.tree = ast.parse(self.src)
        self.deps: list[str] = []
        self.remove: list[tuple[int, int]] = []       # (lineno, end_lineno) to delete
        self.prelude: list[str] = []                   # lines to emit before the body (shims, aliases)
        self.defined: set[str] = set()
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    self.remove.append((node.lineno, node.end_lineno))
                    continue
                target = resolve(node, name)
                if target is None:
                    continue
                self.remove.append((node.lineno, node.end_lineno))
                for alias in node.names:
                    sub = f"{target}.{alias.name}"
                    if mod_path(sub):           # from pkg import submodule [as X]
                        self.deps.append(sub)
                        self.prelude.append(("__SHIM__", alias.asname or alias.name, sub))
                    else:                        # from module import name [as X]
                        self.deps.append(target)
                        if alias.asname and alias.asname != alias.name:
                            self.prelude.append(f"{alias.asname} = {alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "pokergym":
                        raise SystemExit(f"{name}: 'import {alias.name}' not supported; use 'from ... import'")
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                self.defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            self.defined.add(n.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.defined.add(node.target.id)

    def public_names(self) -> list[str]:
        names = set(self.defined)
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom) and node.module != "__future__":
                for a in node.names:
                    names.add(a.asname or a.name)
        return sorted(n for n in names if n != "__all__")

    def body(self) -> str:
        lines = self.src.split("\n")
        drop = set()
        for a, b in self.remove:
            drop.update(range(a - 1, b))
        return "\n".join(l for i, l in enumerate(lines) if i not in drop)


def load_graph(entry_path: str, entry_name: str) -> tuple[dict[str, Mod], list[str]]:
    mods: dict[str, Mod] = {}
    order: list[str] = []

    def visit(name: str, path: str):
        if name in mods:
            return
        m = Mod(name, path)
        mods[name] = m
        for d in m.deps:
            p = mod_path(d)
            if p is None:
                raise SystemExit(f"{name}: cannot resolve {d}")
            visit(d, p)
        order.append(name)

    for a in ALWAYS:
        visit(a, mod_path(a))
    visit(entry_name, entry_path)
    return mods, order


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------
def embed_equity(src: str) -> str:
    with open(os.path.join(PKG, "data", "preflop_equity.json")) as f:
        table = json.load(f)
    needle = "        with open(_DATA_PATH) as f:\n            d = json.load(f)\n"
    if needle not in src:
        raise SystemExit("equity.py changed; update the embedding needle in bundle.py")
    src = src.replace(needle, "        d = _EMBEDDED_TABLE\n")
    return "_EMBEDDED_TABLE = " + json.dumps(table, separators=(",", ":")) + "\n\n" + src


def bundle(bot_spec: str) -> tuple[str, str]:
    if ":" in bot_spec:
        path, cls = bot_spec.rsplit(":", 1)
        if not (path.endswith(".py") or os.sep in path):
            raise SystemExit("use path/to/file.py:Class or a registry name")
        entry_path, entry_name = os.path.abspath(path), "__entry__"
    else:
        from pokergym.bots import BOT_REGISTRY

        if bot_spec not in BOT_REGISTRY:
            raise SystemExit(f"unknown bot {bot_spec!r}")
        cls = BOT_REGISTRY[bot_spec].__name__
        module = BOT_REGISTRY[bot_spec].__module__
        entry_path, entry_name = mod_path(module), module
    mods, order = load_graph(entry_path, entry_name)

    owners: dict[str, str] = {}
    for name in order:
        for d in mods[name].defined:
            if d.startswith("__"):
                continue  # __all__ and friends are harmless duplicates
            if d in owners and owners[d] != name:
                raise SystemExit(f"name collision: {d!r} defined in {owners[d]} and {name}")
            owners[d] = name

    out = [
        '"""Single-file bundle generated by scripts/bundle.py. Do not edit; edit the sources.',
        f"bot: {bot_spec}   modules: {', '.join(order)}",
        f"generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        '"""',
        "from __future__ import annotations",
        "import types as _types",
        "",
    ]
    for name in order:
        m = mods[name]
        out.append(f"# {'=' * 70}\n# module {name}\n# {'=' * 70}")
        for item in m.prelude:
            if isinstance(item, tuple):
                _, alias, sub = item
                names = mods[sub].public_names()
                out.append(f"{alias} = _types.SimpleNamespace(**{{k: globals()[k] for k in {names!r} if k in globals()}})")
            else:
                out.append(item)
        body = m.body()
        if name == "pokergym.equity":
            body = embed_equity(body)
        out.append(body)
    out.append(f"\nBOT_CLASS = {cls}\n")
    out.append(
        "\nif __name__ == '__main__':\n"
        "    _b = BOT_CLASS()\n"
        "    _b.reset(TableInfo(seat=0, num_players=8, starting_stack=2000, rules_name='selftest', seed=1))\n"
        "    _o = build_observation(seat=0, button=7, hole_cards=['As', 'Kd'], board=[], stacks=[2000] * 8,\n"
        "                           bets=[0, 10, 20, 0, 0, 0, 0, 0], big_blind=20)\n"
        "    print('self-test action:', action_to_text(_b.act(_o), _o))\n"
    )
    return "\n".join(out), cls


# --------------------------------------------------------------------------
# smoke test
# --------------------------------------------------------------------------
def smoke(path: str, cls_name: str, tournaments: int = 2) -> dict:
    from pokergym.agent import Action, ActionType
    from pokergym.bots import BOT_REGISTRY
    from pokergym.rules import BASELINE_RULES
    from pokergym.tournament import run_tournament

    spec = importlib.util.spec_from_file_location("_bundle_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bundle_under_test"] = mod
    spec.loader.exec_module(mod)
    Bundled = getattr(mod, cls_name)

    class Adapter:
        """The bundle has its own Action/TableInfo classes; translate at the edge."""

        def __init__(self):
            self.bot = Bundled()

        def reset(self, t):
            self.bot.reset(mod.TableInfo(seat=t.seat, num_players=t.num_players, starting_stack=t.starting_stack,
                                         rules_name=t.rules_name, seed=t.seed))

        def act(self, o):
            a = self.bot.act(o)  # the Observation is duck-typed: attribute access only
            return Action(ActionType(int(a.kind)), int(a.amount))

    calls = illegal = errors = 0
    for seed in range(tournaments):
        bots = [Adapter()] + [BOT_REGISTRY[n]() for n in ("tag", "lag", "shortstack", "icm", "adaptive", "tag", "lag")]
        res = run_tournament(bots, BASELINE_RULES, seed=100 + seed, keep_hands=False)
        st = res.agent_stats[0]
        calls += st["calls"]
        illegal += st["illegal"]
        errors += st["errors"]
    return {"calls": calls, "illegal": illegal, "errors": errors}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True, help="path/to/file.py:Class or a registry name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-smoke", action="store_true")
    a = ap.parse_args()
    src, cls = bundle(a.bot)
    compile(src, a.out, "exec")  # syntax check before writing
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(src)
    size = os.path.getsize(a.out)
    print(f"wrote {a.out}: {size/1024:.0f} KB ({size/100e6*100:.3f}% of the 100 MB limit), class {cls}")
    if not a.no_smoke:
        r = smoke(a.out, cls)
        print(f"smoke test: {r['calls']} decisions, {r['illegal']} illegal, {r['errors']} errors")
        if r["illegal"] or r["errors"]:
            sys.exit("BUNDLE FAILED SMOKE TEST")


if __name__ == "__main__":
    main()
