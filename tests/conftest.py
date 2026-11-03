import pytest


@pytest.fixture
def deck_off(monkeypatch):
    """Run a test with the card deck off by default, as before v0.4.0 and as a user can still choose."""
    import companion_ai.event_deck as event_deck
    monkeypatch.setattr(event_deck, 'DEFAULT_DECK_ENABLED', False)
