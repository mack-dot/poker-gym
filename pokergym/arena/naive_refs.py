"""Reference bots that IGNORE the variant: identical to the sparring bots
except ``configure`` is a no-op. The gap between a configured bot and its
naive twin is what "adapting to the rule" is worth; the hidden evaluator
uses it to separate rule adaptation from general strength."""
from __future__ import annotations

from ..bots.sparring import IcmBot, TagBot


class NaiveTag(TagBot):
    name = "naive-tag"

    def configure(self, rules) -> None:  # noqa: D401 - deliberately ignores the rules
        return None


class NaiveIcm(IcmBot):
    name = "naive-icm"

    def configure(self, rules) -> None:
        return None
