# SPDX-License-Identifier: AGPL-3.0-only
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SpeechPolicy(StrictModel):
    enabled: bool = True
    event_responses: bool = True
    min_interval_seconds: float = Field(default=45.0, ge=0, le=3600)
    interruption: Literal["drop", "interrupt"] = "drop"
    per_event_cooldown_seconds: float = Field(default=60.0, ge=0, le=3600)
    user_grace_seconds: float = Field(default=15.0, ge=0, le=120)
    event_ttl_seconds: float = Field(default=60.0, ge=1, le=300)
    pending_event_limit: int = Field(default=8, ge=1, le=32)
    sustained_trend_seconds: float = Field(default=4.0, ge=0, le=30)
    significant_hr_delta: int = Field(default=6, ge=2, le=30)


class AIConfig(StrictModel):
    provider: str = Field(default="ollama", pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    model: str = Field(default="qwen3:8b", min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:/-]+$")
    context_length: int = Field(default=8192, ge=512, le=8192)
    max_tokens: int = Field(default=2048, ge=16, le=4096)
    cpu_threads: int = Field(default=8, ge=1, le=16)
    idle_unload_seconds: int = Field(default=120, ge=0, le=1800)
    # Sampling belongs to each companion's Modelfile (PARAMETER lines). None means "not sent",
    # so Ollama applies the model's own values. Only code that sets a value on purpose (for
    # example a temperature-0 evaluation) overrides it for that request; see stored_config().
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    top_k: int | None = Field(default=None, ge=0, le=200)
    repeat_penalty: float | None = Field(default=None, ge=0, le=2)
    timeout_seconds: float = Field(default=120.0, ge=1, le=300)
    thinking: bool = False
    explicit_expressions: bool = True
    # Legacy saved configs remain readable; this preference is no longer injected.
    response_length: Literal["inherit", "brief", "normal", "detailed"] = "inherit"


class MemoryConfig(StrictModel):
    enabled: bool = True
    max_messages: int = Field(default=8, ge=2, le=64)
    persist_between_sessions: bool = False


SAMPLING_KEYS = ('temperature', 'top_p', 'top_k', 'repeat_penalty')


def stored_config(values):
    """A config read back from saved settings (selection.json, model-presets.json).

    Earlier versions saved the app's own sampling defaults (temperature 0.4, top_p 0.95, ...)
    with every selection although no player could set them. Ignoring stored sampling lets each
    Modelfile's PARAMETER values apply again, also for installs that saved those defaults."""
    return {k: v for k, v in (values or {}).items() if k not in SAMPLING_KEYS}


class ModelSelection(StrictModel):
    model: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:/-]+$")
    context_length: int | None = Field(default=None, ge=512, le=8192)
    context_policy: Literal["reject", "adapt"] = "reject"
