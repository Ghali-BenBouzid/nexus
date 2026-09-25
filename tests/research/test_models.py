"""Which model thinks how hard, for each role of a run."""

from app.core.config import settings
from app.research.service import models_for
from tests.agents.fakes import ScriptedModel


def test_each_role_gets_its_model_and_effort(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "z-ai/glm-5.3-flash")

    main, worker, writer = models_for(None, "xhigh")

    assert (main.model_name, main.extra_body["reasoning"]) == (
        "z-ai/glm-5.3-flash",
        {"effort": "xhigh"},
    )
    assert (worker.model_name, worker.extra_body["reasoning"]) == (
        settings.worker_model,
        {"effort": settings.worker_effort},
    )
    assert (writer.model_name, writer.extra_body["reasoning"]) == (
        "z-ai/glm-5.3-flash",
        {"effort": settings.writer_effort},
    )
    # the provider routing still rides along with the effort
    assert "provider" in main.extra_body


def test_an_injected_model_plays_every_role() -> None:
    fake = ScriptedModel(responses=[])
    assert models_for(fake, "low") == (fake, fake, fake)
