"""Baseline fixture bots. These are functional test fixtures, not strong play."""
from .callbot import CallBot
from .randombot import RandomBot
from .heuristic import HeuristicBot

BOT_REGISTRY = {
    "call": CallBot,
    "random": RandomBot,
    "heuristic": HeuristicBot,
}

__all__ = ["CallBot", "RandomBot", "HeuristicBot", "BOT_REGISTRY"]
