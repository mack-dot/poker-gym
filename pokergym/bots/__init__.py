"""Bots shipped with the gym.

Fixtures (functional tests, weak play): ``call``, ``random``, ``heuristic``.
Sparring partners (hand-built styles, see ``sparring.py``): ``tag``, ``lag``,
``shortstack``, ``icm``, ``adaptive``.
"""
from .callbot import CallBot
from .randombot import RandomBot
from .heuristic import HeuristicBot
from .sparring import AdaptiveBot, IcmBot, LagBot, ShortStackBot, TagBot

FIXTURE_BOTS = {
    "call": CallBot,
    "random": RandomBot,
    "heuristic": HeuristicBot,
}
SPARRING_BOTS = {
    "tag": TagBot,
    "lag": LagBot,
    "shortstack": ShortStackBot,
    "icm": IcmBot,
    "adaptive": AdaptiveBot,
}
BOT_REGISTRY = {**FIXTURE_BOTS, **SPARRING_BOTS}

__all__ = [
    "CallBot", "RandomBot", "HeuristicBot", "TagBot", "LagBot", "ShortStackBot", "IcmBot", "AdaptiveBot",
    "BOT_REGISTRY", "FIXTURE_BOTS", "SPARRING_BOTS",
]
