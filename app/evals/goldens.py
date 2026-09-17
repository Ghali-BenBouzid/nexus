"""The golden set: the queries every change to Nexus is measured against.

The goldens live in goldens.toml (plain data, reviewed like code); this module
loads and validates them.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

GOLDENS_PATH = Path(__file__).with_name("goldens.toml")


class Golden(BaseModel):
    id: str
    category: str
    input: str
    # The language name the reply must be in, as app.agents.language names them.
    language: str = "English"
    # answer = reply directly, research = run the pipeline, any = either is fine.
    expected_route: Literal["answer", "research", "any"] = "research"
    time_sensitive: bool = False
    expected_behavior: str
    expected_facts: list[str] = Field(default_factory=list)


def load_goldens(path: Path = GOLDENS_PATH) -> list[Golden]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    goldens = [Golden(**raw) for raw in data["golden"]]
    ids = [golden.id for golden in goldens]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate golden ids: {duplicates}")
    return goldens
