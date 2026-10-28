"""Stand-in competitor for the bounded smoke rehearsal.

Acts ONLY through the workspace, under the same sandbox policy a real
competitor gets: writes bot files into the workspace and runs
``submit.py`` with the sandboxed interpreter. Its script exercises every
branch the lifecycle must handle: a free check, a syntax error, an illegal
bot, an accepted safe bot, a hanging bot, and an adapted heuristic bot.
No AI inference is involved.
"""
from __future__ import annotations

import os
import time

from . import isolation
from .session import Challenge

BROKEN = "def Agent(:\n    pass\n"

ILLEGAL = '''class Action:
    __slots__ = ("kind", "amount")
    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount

class Agent:
    def reset(self, table):
        pass
    def act(self, obs):
        return Action(3, 1)  # raise to 1 chip: never legal
'''

HANGS_ONCE = '''import time

class Action:
    __slots__ = ("kind", "amount")
    def __init__(self, kind, amount=0):
        self.kind, self.amount = kind, amount

class Agent:
    def reset(self, table):
        self.n = 0
    def act(self, obs):
        self.n += 1
        if self.n == 3:
            time.sleep(0.4)  # one hung decision per table
        return Action(1) if obs.can_check else Action(0)
'''

ADAPTED_HEURISTIC = '''"""Kit heuristic, pointed at the variant's hand ranking."""
import kit
from kit.heuristic import HeuristicBot

_RULES = kit.load_rules()


class Agent(HeuristicBot):
    def __init__(self):
        super().__init__(aggression=1.1)
        self.evaluator = _RULES.ranking.evaluator()
'''


def _run_submit(ch: Challenge, *args: str, timeout: float = 240.0) -> str:
    argv = [isolation.competitor_python(), "-I", "-S", os.path.join(ch.ws, "submit.py"), *args]
    cp = isolation.run(ch.policy(), argv, cwd=ch.ws, timeout=timeout)
    return (cp.stdout + cp.stderr).strip()


def _write(ch: Challenge, name: str, text: str) -> str:
    p = os.path.join(ch.ws, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def _wait_slot(ch: Challenge, log) -> None:
    ch.reload()
    nxt = ch.next_slot_at()
    if nxt is not None:
        wait = nxt - time.time() + 0.3
        if wait > 0:
            log(f"[standin] waiting {wait:.1f}s for the next submission slot")
            time.sleep(wait)


def run_script(ch: Challenge, log=print) -> list[str]:
    """Returns the submit.py outputs in order."""
    outs = []

    def step(label, *args):
        log(f"[standin] {label}")
        out = _run_submit(ch, *args)
        log("   " + out.replace("\n", "\n   "))
        outs.append(out)
        return out

    step("check the template (free)", "my_agent.py", "--check")
    _write(ch, "broken.py", BROKEN)
    step("submit a file with a syntax error -> expect REJECTED (import)", "broken.py")
    step("submit again immediately -> expect cadence rejection", "my_agent.py")
    _wait_slot(ch, log)
    _write(ch, "illegal.py", ILLEGAL)
    step("submit an always-illegal bot -> expect REJECTED (legality)", "illegal.py")
    _wait_slot(ch, log)
    step("log a hypothesis", "--note", "hypothesis: the safe template is accepted; next adapt the kit heuristic to the variant")
    step("submit the safe template -> expect ACCEPTED (active)", "my_agent.py")
    _wait_slot(ch, log)
    _write(ch, "hangs.py", HANGS_ONCE)
    step("submit a bot that hangs one decision per table -> expect REJECTED (errors: watchdog)", "hangs.py")
    _wait_slot(ch, log)
    _write(ch, "adapted.py", ADAPTED_HEURISTIC)
    step("check the adapted heuristic (free)", "adapted.py", "--check")
    step("submit the adapted heuristic -> expect ACCEPTED (new active)", "adapted.py")
    return outs
