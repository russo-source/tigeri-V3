from pathlib import Path

from tigeri.agent_card.registry import AgentCardRegistry


def test_invoice_card_loads_with_catalog_strings():
    reg = AgentCardRegistry()
    reg.load_from_disk(
        Path(__file__).resolve().parents[2] / "src" / "tigeri" / "agent_card" / "cards"
    )
    card = reg.get("invoice_agent")

    # Verbatim catalog strings (section 6.1)
    assert card.function == (
        "Captures, validates, routes and posts invoices. Eliminates AP data entry."
    )
    assert card.roi_baseline == "$8K–12K per yr per finance FTE"
    assert card.priority == 1
    assert card.phase.value == "Phase 1 — Core MVP"
    assert card.status.value == "In Development"
    assert card.default_trust_tier.value == "ACTOR_GATED"
    assert "web" in card.delivery_surfaces
    assert "mobile" in card.delivery_surfaces
    assert len(card.capabilities) == 6
