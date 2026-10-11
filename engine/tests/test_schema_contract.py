"""Contract tests: shared fixtures must match the JSON Schemas and the generated models."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from engine.schema.alert_schema import Alert
from engine.schema.command_schema import PlaybackCommand
from engine.schema.event_schema import MatchEvent
from engine.schema.feed_schema import FeedMessage
from engine.schema.match_list_schema import MatchList
from engine.schema.metric_schema import MetricSnapshot
from engine.schema.status_schema import PlaybackStatus

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schema"
JSONSCHEMA_DIR = SCHEMA_ROOT / "jsonschema"
FIXTURES_DIR = SCHEMA_ROOT / "fixtures"

MODELS: dict[str, type[BaseModel]] = {
    "alert": Alert,
    "command": PlaybackCommand,
    "event": MatchEvent,
    "feed": FeedMessage,
    "match_list": MatchList,
    "metric": MetricSnapshot,
    "status": PlaybackStatus,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


REGISTRY: Registry[Any] = Registry().with_resources(
    (path.name, Resource.from_contents(_load(path), default_specification=DRAFT7))
    for path in JSONSCHEMA_DIR.glob("*.schema.json")
)


def _validator(kind: str) -> Draft7Validator:
    return Draft7Validator({"$ref": f"{kind}.schema.json"}, registry=REGISTRY)


def _cases(fixture_set: str) -> list[Any]:
    paths = sorted((FIXTURES_DIR / fixture_set).glob("*/*.json"))
    return [pytest.param(p.parent.name, p, id=f"{p.parent.name}/{p.stem}") for p in paths]


def test_every_schema_has_a_model_and_fixtures() -> None:
    schemas = {p.name.removesuffix(".schema.json") for p in JSONSCHEMA_DIR.glob("*.schema.json")}
    schemas.discard("common")
    with_fixtures = {p.name for p in (FIXTURES_DIR / "valid").iterdir() if p.is_dir()}
    assert schemas == set(MODELS)
    assert with_fixtures == schemas


@pytest.mark.parametrize(("kind", "path"), _cases("valid"))
def test_valid_fixture_round_trips(kind: str, path: Path) -> None:
    data = _load(path)
    _validator(kind).validate(data)
    model = MODELS[kind].model_validate(data)
    assert model.model_dump(mode="json", exclude_unset=True) == data


@pytest.mark.parametrize(("kind", "path"), _cases("invalid"))
def test_invalid_fixture_is_rejected(kind: str, path: Path) -> None:
    data = _load(path)
    assert not _validator(kind).is_valid(data)
    with pytest.raises(ValidationError):
        MODELS[kind].model_validate(data)
