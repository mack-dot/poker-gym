"""Competition rehearsal CLI.

    python -m pokergym.arena reserve                       # list the concealed mutation reserve (host only)
    python -m pokergym.arena rehearse ROOT --seed N        # THE 60-minute exercise: create + start + serve
    python -m pokergym.arena create ROOT --seed N [--family F] [--duration-min 60] [--cadence-min 5]
    python -m pokergym.arena start ROOT
    python -m pokergym.arena serve ROOT                    # host loop: validates inbox requests, freezes on time
    python -m pokergym.arena status ROOT
    python -m pokergym.arena check|submit ROOT BOT.py      # host-side equivalents of workspace/submit.py
    python -m pokergym.arena note ROOT "text"
    python -m pokergym.arena freeze ROOT
    python -m pokergym.arena rollback ROOT INDEX
    python -m pokergym.arena grade ROOT [--tables 1000] [--workers 8] [--all-accepted]
    python -m pokergym.arena postmortem ROOT
    python -m pokergym.arena smoke [--root DIR] [--duration-s 75] [--cadence-s 8] [--seed N]   # bounded end-to-end

The competitor works in ROOT/workspace and talks to the host only through
ROOT/inbox (workspace/submit.py). Start `serve` before the competitor starts.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import time

from .grade import grade
from .mutations import reserve
from .session import Challenge
from .validator import ValidationReport


def _report(sub) -> str:
    if isinstance(sub, dict):
        return sub["summary"]
    r = sub.report
    return ValidationReport(**{k: r[k] for k in ("accepted", "stages", "metrics", "sha256", "size_bytes", "seconds", "error", "config")}).summary()


def cmd_reserve(a):
    for m in reserve():
        print(f"{m.family:13s} {m.name:36s} signal: {m.signal_name}")
    print(f"{len(reserve())} mutations; generate(seed) picks one deterministically")


def cmd_create(a):
    ch = Challenge.create(a.root, seed=a.seed, family=a.family, duration_s=a.duration_min * 60, cadence_s=a.cadence_min * 60,
                          validation={"tables": a.validation_tables})
    print(f"created {ch.root}")
    print(f"  commitment {ch.public['commitment'][:16]}...  isolation {ch.public['isolation_level']} "
          f"self-test ok={ch.public.get('isolation_self_test', {}).get('ok')}")
    if ch.public.get("clock_warning"):
        print("  " + ch.public["clock_warning"])
    print(f"  workspace: {ch.ws}")
    print("  next: `python -m pokergym.arena serve ROOT` in one terminal, `start ROOT` when the competitor is ready")


def cmd_start(a):
    ch = Challenge(a.root)
    ev = ch.start()
    print(f"started at {ev['iso']}; variant revealed in {ch.ws}/BRIEFING.md; freeze at +{ch.public['duration_s']:.0f}s")


def cmd_serve(a):
    ch = Challenge(a.root)
    print(f"[serve] {ch.root} status={ch.public['status']}; waiting for inbox requests (Ctrl-C to stop)")
    try:
        ch.serve(until_frozen=not a.forever)
    except KeyboardInterrupt:
        pass
    print("[serve] stopped")


def cmd_status(a):
    print(json.dumps(Challenge(a.root).status(), indent=1, default=str))


def cmd_check(a):
    print(_report(Challenge(a.root).check(a.bot, os.path.basename(a.bot))))


def cmd_submit(a):
    print(_report(Challenge(a.root).submit(a.bot, os.path.basename(a.bot))))


def cmd_note(a):
    Challenge(a.root).note(a.text)
    print("noted")


def cmd_freeze(a):
    print(Challenge(a.root).freeze("manual"))


def cmd_rollback(a):
    print(Challenge(a.root).rollback(a.index))


def cmd_grade(a):
    grade(Challenge(a.root), tables=a.tables, workers=a.workers, all_accepted=a.all_accepted)


def cmd_postmortem(a):
    from . import postmortem

    ch = Challenge(a.root)
    print(open(postmortem.write(ch)).read())


def cmd_rehearse(a):
    """The real thing: 60 minutes, real clock. Nothing automated plays for you."""
    ch = Challenge.create(a.root, seed=a.seed, family=a.family)
    print(f"created {ch.root}; isolation {ch.public['isolation_level']} ok={ch.public.get('isolation_self_test', {}).get('ok')}")
    print("Open a competitor shell in:", ch.ws)
    print("  (run competitor commands under the sandbox: `sandbox-exec -f workspace/.sandbox.sb <python> -I -S ...`;")
    print("   the host writes the profile on the first validation; before that, use `python -m pokergym.arena sandbox-profile ROOT`)")
    input("Press Enter to START the 60-minute clock and reveal the variant... ")
    ev = ch.start()
    print(f"STARTED {ev['iso']}  variant revealed; freeze at +3600s. Serving inbox until freeze.")
    ch.serve(until_frozen=True)
    print("FROZEN. Grading...")
    grade(ch, tables=a.tables, workers=a.workers, all_accepted=True)


def cmd_sandbox_profile(a):
    ch = Challenge(a.root)
    p = os.path.join(ch.ws, ".sandbox.sb")
    with open(p, "w") as f:
        f.write(ch.policy().profile())
    print(p)


def cmd_smoke(a):
    """Bounded end-to-end rehearsal with the stand-in competitor. Real clock,
    short window (recorded as NON-STANDARD in challenge.json)."""
    from . import standin

    root = a.root or os.path.join(os.path.expanduser("~"), "pokergym-arena", f"smoke-{int(time.time())}")
    if os.path.exists(root):
        shutil.rmtree(root)
    t0 = time.time()
    ch = Challenge.create(root, seed=a.seed, family=a.family, duration_s=a.duration_s, cadence_s=a.cadence_s,
                          validation={"tables": 3})
    print(f"[smoke] created {root}  isolation={ch.public['isolation_level']} ok={ch.public.get('isolation_self_test', {}).get('ok')}")
    assert not os.path.exists(os.path.join(ch.ws, "variant.json")), "variant leaked before start"
    ch.start()
    print(f"[smoke] started; variant {ch.mutation().name}; window {a.duration_s}s cadence {a.cadence_s}s")
    host = Challenge(root)
    th = threading.Thread(target=host.serve, kwargs={"until_frozen": True, "quiet": True}, daemon=True)
    th.start()
    standin.run_script(ch)
    print(f"[smoke] stand-in done at +{time.time() - t0:.0f}s; waiting for the freeze")
    th.join(timeout=a.duration_s + 60)
    ch = Challenge(root)
    print(f"[smoke] frozen={ch.state['frozen']} active={ch.state.get('active')} at +{time.time() - t0:.0f}s")
    grade(ch, tables=a.tables, workers=a.workers, all_accepted=True)
    print(f"[smoke] total wall {time.time() - t0:.0f}s; root {root}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pokergym.arena", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("reserve").set_defaults(fn=cmd_reserve)
    p = sp.add_parser("create")
    p.add_argument("root")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--family")
    p.add_argument("--duration-min", type=float, default=60.0)
    p.add_argument("--cadence-min", type=float, default=5.0)
    p.add_argument("--validation-tables", type=int, default=6)
    p.set_defaults(fn=cmd_create)
    for name, fn in (("start", cmd_start), ("status", cmd_status), ("freeze", cmd_freeze), ("postmortem", cmd_postmortem),
                     ("sandbox-profile", cmd_sandbox_profile)):
        p = sp.add_parser(name)
        p.add_argument("root")
        p.set_defaults(fn=fn)
    p = sp.add_parser("serve")
    p.add_argument("root")
    p.add_argument("--forever", action="store_true")
    p.set_defaults(fn=cmd_serve)
    for name, fn in (("check", cmd_check), ("submit", cmd_submit)):
        p = sp.add_parser(name)
        p.add_argument("root")
        p.add_argument("bot")
        p.set_defaults(fn=fn)
    p = sp.add_parser("note")
    p.add_argument("root")
    p.add_argument("text")
    p.set_defaults(fn=cmd_note)
    p = sp.add_parser("rollback")
    p.add_argument("root")
    p.add_argument("index", type=int)
    p.set_defaults(fn=cmd_rollback)
    p = sp.add_parser("grade")
    p.add_argument("root")
    p.add_argument("--tables", type=int, default=1000)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--all-accepted", action="store_true")
    p.set_defaults(fn=cmd_grade)
    p = sp.add_parser("rehearse")
    p.add_argument("root")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--family")
    p.add_argument("--tables", type=int, default=2000)
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=cmd_rehearse)
    p = sp.add_parser("smoke")
    p.add_argument("--root")
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--family")
    p.add_argument("--duration-s", type=float, default=75.0)
    p.add_argument("--cadence-s", type=float, default=8.0)
    p.add_argument("--tables", type=int, default=200)
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(fn=cmd_smoke)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
