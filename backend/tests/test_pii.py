"""Unit tests for PII detection and redaction (R-08.6, R-08.7; NFR-08, NFR-10)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.adapters.session_store import InMemorySessionStore, new_session_id
from app.domain.models import ActivityStatus, AgeBand, ObjectItem, SessionRecord, Subject
from app.services.pii import (
    PiiNotRedactableError,
    PiiType,
    guarded_model_call,
    redact_pii,
)

NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


class ModelStub:
    """Records every input it receives so tests can count model calls."""

    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def __call__(self, texts: list[str]) -> str:
        self.inputs.append(texts)
        return "ok"


@pytest.mark.parametrize(
    ("text", "leaked", "pii_type"),
    [
        ("My name is Priya Sharma and I have five stones", "Priya", PiiType.NAME),
        ("Ask Mrs Johnson about the leaves", "Johnson", PiiType.NAME),
        ("my son Arjun collected two leaves", "Arjun", PiiType.NAME),
        ("Call me on +1 (555) 123-4567 about stones", "555", PiiType.PHONE),
        ("phone 020 7946 0958", "7946", PiiType.PHONE),
        ("Email jane.doe@example.com for leaves", "jane.doe@example.com", PiiType.EMAIL),
        ("We live at 42 Maple Street near the park", "Maple", PiiType.ADDRESS),
        ("Lives at 7 Oak Ave with five stones", "Oak", PiiType.ADDRESS),
        ("She attends Greenfield Elementary every day", "Greenfield", PiiType.SCHOOL),
        ("Goes to Riverdale Academy and has stones", "Riverdale", PiiType.SCHOOL),
        ("Her birthday is March 3, 2016 and she has stones", "2016", PiiType.BIRTH_DATE),
        ("Born on 03/04/2015, loves leaves", "2015", PiiType.BIRTH_DATE),
        ("birthday is 3 March", "March", PiiType.BIRTH_DATE),
    ],
)
def test_each_pii_type_is_redacted_before_model_call_with_warning(
    text: str, leaked: str, pii_type: PiiType
) -> None:
    """R-08.6: PII is redacted from model input and a warning is returned."""
    model = ModelStub()
    out = guarded_model_call([text], model)

    assert len(model.inputs) == 1
    sent = model.inputs[0][0]
    assert leaked not in sent
    assert f"[REDACTED_{pii_type.name}]" in sent
    assert out.warning is not None
    assert pii_type.value.replace("_", " ") in out.warning


def test_clean_text_is_unchanged_and_has_no_warning() -> None:
    """R-08.6: text without PII passes through untouched with no warning."""
    for text in ("five stones and two leaves", "2 small stones in the lane", "3 red cups"):
        result = redact_pii(text)
        assert result.text == text
        assert result.warning is None
        assert not result.redacted


def test_multiple_pii_types_in_one_text_are_all_redacted() -> None:
    """R-08.6: several PII types in one input are all redacted and reported."""
    text = "My name is Anil Rao, email anil@example.org, phone 555-123-4567"
    result = redact_pii(text)
    assert {PiiType.NAME, PiiType.EMAIL, PiiType.PHONE} <= set(result.types)
    for leaked in ("Anil", "anil@example.org", "123-4567"):
        assert leaked not in result.text


@pytest.mark.parametrize(
    "text",
    [
        "reach me at jo at example dot com",
        "call five five five one two three four",
    ],
)
def test_unredactable_pii_makes_no_model_call_and_leaves_session_unchanged(text: str) -> None:
    """R-08.7: unredactable PII -> zero model calls, error, Session data unchanged."""
    store = InMemorySessionStore()
    record = SessionRecord(
        session_id=new_session_id(),
        token_hash="hash-of-capability-token",  # noqa: S106 - a hash, not a secret
        state="created",
        age_band=AgeBand.B6_8,
        subject=Subject.ARITHMETIC,
        language="en",
        objects=[ObjectItem(original="Stone", normalized="stone")],
        activity_status=[ActivityStatus(activity_id="a1")],
        current_index=0,
        idempotency=[],
        generation_count=0,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW,
        version=0,
    )
    store.create(record)
    before = store.get(record.session_id, NOW)

    model = ModelStub()
    with pytest.raises(PiiNotRedactableError) as exc:
        guarded_model_call(["five stones", text], model)

    assert model.inputs == []
    assert "remove" in exc.value.message.lower()
    assert exc.value.code == "pii_not_redactable"
    assert store.get(record.session_id, NOW) == before


def test_partial_failure_blocks_all_texts() -> None:
    """R-08.7: if one text is unredactable none of the texts reach the model."""
    model = ModelStub()
    with pytest.raises(PiiNotRedactableError):
        guarded_model_call(["Email a@b.com", "x at y dot com"], model)
    assert model.inputs == []
