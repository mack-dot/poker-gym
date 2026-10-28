from ..agent import CALL, CHECK, Action, Observation, TableInfo


class CallBot:
    """Always checks when possible, otherwise calls. Never folds, never raises."""

    name = "call"

    def reset(self, table: TableInfo) -> None:
        self.seat = table.seat

    def act(self, obs: Observation) -> Action:
        return CHECK if obs.can_check else CALL
