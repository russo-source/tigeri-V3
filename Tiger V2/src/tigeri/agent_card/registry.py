from pathlib import Path

import yaml

from tigeri.agent_card.schema import AgentCard

_CARDS_DIR = Path(__file__).parent / "cards"


class AgentCardRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}

    def load_from_disk(self, directory: Path | None = None) -> None:
        directory = directory or _CARDS_DIR
        for path in sorted(directory.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            card = AgentCard.model_validate(data)
            self._cards[card.agent_id] = card

    def get(self, agent_id: str) -> AgentCard:
        if agent_id not in self._cards:
            raise KeyError(f"agent_card not registered: {agent_id}")
        return self._cards[agent_id]

    def all(self) -> list[AgentCard]:
        return sorted(self._cards.values(), key=lambda c: c.priority)


_registry: AgentCardRegistry | None = None


def get_registry() -> AgentCardRegistry:
    global _registry
    if _registry is None:
        _registry = AgentCardRegistry()
        _registry.load_from_disk()
    return _registry
