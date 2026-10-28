"""The replaceable boundary between our research simulator and the official kit.

Four seams are kept separate on purpose:

1. Research simulator      -> ``pokergym.engine`` / ``pokergym.tournament``
2. Game-rule specification -> ``pokergym.rules`` (+ ``pokergym.variants``)
3. Agent observation protocol -> ``pokergym.agent`` (``Observation``/``Action``)
4. Tournament scoring engine -> ``pokergym.tournament.run_round`` / ``final_score`` / ``pokergym.icm``

When the starter kit arrives, the plan is:

* Write ``OfficialObservationAdapter`` here: a function from the kit's state
  object to our ``Observation`` (and our ``Action`` to the kit's action
  encoding). Bots written against ``pokergym.agent`` then run unchanged inside
  the official simulator via ``OfficialAgentShim``.
* Write ``KitRulesAdapter``: build a ``GameRules`` from the kit's payout
  structure, blind schedule and variant description, replacing the
  ``SYNTHETIC`` defaults in ``pokergym.rules``.
* Run the parity harness: the same bots, the same seats and (if the kit
  exposes the deck) the same cards through both simulators; compare final
  stacks, finishing points and ICM allocations hand by hand (see
  ``tests/test_differential_pokerkit.py`` for the pattern used against
  PokerKit).

Nothing below invents official method names. ``OfficialAgentShim`` is a
template with a single injected translation function so the real signature
can be bound without touching bots or the engine.
"""
from __future__ import annotations

from typing import Any, Callable

from .agent import Action, Agent, Observation, TableInfo, fallback_action

ObservationTranslator = Callable[[Any], Observation]
ActionTranslator = Callable[[Action, Any], Any]


class OfficialAgentShim:
    """Hosts one of our bots inside a foreign simulator.

    ``to_obs`` converts the foreign per-decision state into our ``Observation``;
    ``to_action`` converts our ``Action`` back (it also receives the foreign
    state so it can map e.g. raise-to amounts to raise-by amounts). ``on_table``
    optionally converts the foreign table-start payload into ``TableInfo``.
    Errors fall back to check/fold, mirroring organizer rule 3.7.
    """

    def __init__(self, bot: Agent, to_obs: ObservationTranslator, to_action: ActionTranslator,
                 on_table: Callable[[Any], TableInfo] | None = None):
        self.bot = bot
        self.to_obs = to_obs
        self.to_action = to_action
        self.on_table = on_table

    def table_started(self, payload: Any) -> None:
        if self.on_table is not None:
            try:
                self.bot.reset(self.on_table(payload))
            except Exception:  # noqa: BLE001
                pass

    def decide(self, foreign_state: Any) -> Any:
        obs = self.to_obs(foreign_state)
        try:
            a = self.bot.act(obs)
            if not obs.is_legal(a):
                a = fallback_action(obs)
        except Exception:  # noqa: BLE001
            a = fallback_action(obs)
        return self.to_action(a, foreign_state)
