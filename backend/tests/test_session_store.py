"""Contract tests for the Session_Store backends (R-01.2, R-10.1, R-10.2, R-10.5-R-10.8; NFR-08).

The same contract runs against the in-memory store and local DynamoDB. The DynamoDB
variant is skipped gracefully when the local endpoint is unreachable or ``boto3`` is not
installed, so the suite always exercises at least the in-memory backend.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pytest
from app.adapters.session_store import (
    DEFAULT_TTL,
    AlreadyExists,
    DynamoDBSessionStore,
    Expired,
    InMemorySessionStore,
    NotFound,
    VersionConflict,
    new_session_id,
)
from app.domain.models import (
    ActivityStatus,
    AgeBand,
    IdempotencyRecord,
    ObjectItem,
    SessionRecord,
    Subject,
)

BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
LOCAL_DDB_ENDPOINT = os.environ.get("IC_DDB_ENDPOINT", "http://localhost:8000")
LOCAL_DDB_REGION = "us-east-1"


class StoreFactory(Protocol):
    def __call__(self) -> object: ...


def make_record(session_id: str | None = None, created: datetime = BASE_TIME) -> SessionRecord:
    """Build a valid record using only permitted attributes."""
    return SessionRecord(
        session_id=session_id or new_session_id(),
        token_hash="hash-of-capability-token",  # noqa: S106 - a hash, not a secret
        state="created",
        age_band=AgeBand.B6_8,
        subject=Subject.ARITHMETIC,
        language="en",
        objects=[ObjectItem(original="Stone", normalized="stone")],
        activity_status=[ActivityStatus(activity_id="a1")],
        current_index=0,
        idempotency=[
            IdempotencyRecord(key="k1", route="/sessions", payload_hash="ph", created_at=created)
        ],
        generation_count=0,
        created_at=created,
        updated_at=created,
        expires_at=created,  # refreshed to updated_at + TTL by the store on persist
        version=0,
    )


# --- Backend parameterization ---------------------------------------------------------------


def _in_memory_store() -> InMemorySessionStore:
    return InMemorySessionStore(ttl=DEFAULT_TTL)


def _dynamodb_store_or_skip() -> DynamoDBSessionStore:
    """Build a DynamoDB-backed store against a local endpoint, else skip the variant."""
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import (
            BotoCoreError,
            ClientError,
        )
    except ImportError:
        pytest.skip("boto3 not installed; skipping DynamoDB contract variant")

    fast = Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 0})
    resource = boto3.resource(
        "dynamodb",
        region_name=LOCAL_DDB_REGION,
        endpoint_url=LOCAL_DDB_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",  # noqa: S106 - dummy credential for local DynamoDB
        config=fast,
    )
    table_name = DynamoDBSessionStore.TABLE_NAME
    try:
        existing = {t.name for t in resource.tables.all()}
        if table_name not in existing:
            resource.create_table(
                TableName=table_name,
                KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            resource.Table(table_name).wait_until_exists()
    except (BotoCoreError, ClientError, OSError) as exc:  # endpoint unreachable
        pytest.skip(f"local DynamoDB unavailable at {LOCAL_DDB_ENDPOINT}: {exc}")

    return DynamoDBSessionStore(table=resource.Table(table_name), ttl=DEFAULT_TTL)


@pytest.fixture(params=["in_memory", "dynamodb"])
def store(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "in_memory":
        yield _in_memory_store()
    else:
        s = _dynamodb_store_or_skip()
        yield s


# --- Contract tests (run against every backend) ---------------------------------------------


def test_create_then_get_returns_record(store: InMemorySessionStore) -> None:
    """A created record is retrievable before expiry. Validates: R-10.1."""
    record = make_record()
    store.create(record)
    got = store.get(record.session_id, BASE_TIME)
    assert got.session_id == record.session_id
    assert got.token_hash == record.token_hash


def test_create_refreshes_expiry_to_updated_plus_ttl(store: InMemorySessionStore) -> None:
    """create sets expires_at = updated_at + 24 h. Validates: R-10.7."""
    record = make_record()
    store.create(record)
    got = store.get(record.session_id, BASE_TIME)
    assert got.expires_at == record.updated_at + DEFAULT_TTL


def test_get_missing_raises_not_found(store: InMemorySessionStore) -> None:
    """Absent Session_ID raises NotFound. Validates: R-10.5, R-10.6."""
    with pytest.raises(NotFound):
        store.get("does-not-exist", BASE_TIME)


def test_get_at_or_after_expiry_raises_expired(store: InMemorySessionStore) -> None:
    """Read at/after expires_at raises Expired without TTL removal. Validates: R-10.7, R-10.8."""
    record = make_record()
    store.create(record)
    just_before = record.updated_at + DEFAULT_TTL - timedelta(seconds=1)
    at_expiry = record.updated_at + DEFAULT_TTL
    after = record.updated_at + DEFAULT_TTL + timedelta(hours=1)

    assert store.get(record.session_id, just_before).session_id == record.session_id
    with pytest.raises(Expired):
        store.get(record.session_id, at_expiry)
    # Expired record is rejected but NOT removed: a later read still rejects (not NotFound).
    with pytest.raises(Expired):
        store.get(record.session_id, after)


def test_create_duplicate_raises_already_exists(store: InMemorySessionStore) -> None:
    """Re-creating an existing Session_ID fails. Validates: R-10.1."""
    record = make_record()
    store.create(record)
    with pytest.raises(AlreadyExists):
        store.create(record)


def test_put_if_version_success_increments_version(store: InMemorySessionStore) -> None:
    """A conditional write at the expected version succeeds and bumps version."""
    record = make_record()
    store.create(record)  # stored at version 0
    updated = store.get(record.session_id, BASE_TIME).model_copy(update={"state": "generating"})
    store.put_if_version(updated, expected=0)
    got = store.get(record.session_id, BASE_TIME)
    assert got.version == 1
    assert got.state == "generating"


def test_put_if_version_stale_write_fails(store: InMemorySessionStore) -> None:
    """A stale version write fails and changes nothing. Validates: optimistic concurrency."""
    record = make_record()
    store.create(record)  # version 0
    first = store.get(record.session_id, BASE_TIME).model_copy(update={"state": "generating"})
    store.put_if_version(first, expected=0)  # -> version 1

    stale = first.model_copy(update={"state": "ready"})
    with pytest.raises(VersionConflict):
        store.put_if_version(stale, expected=0)  # expects 0, store is at 1

    got = store.get(record.session_id, BASE_TIME)
    assert got.version == 1
    assert got.state == "generating"  # unchanged by the failed write


def test_put_if_version_refreshes_expiry(store: InMemorySessionStore) -> None:
    """Each persist refreshes expires_at off updated_at. Validates: R-10.7."""
    record = make_record()
    store.create(record)
    later = record.updated_at + timedelta(hours=3)
    updated = store.get(record.session_id, BASE_TIME).model_copy(
        update={"updated_at": later, "state": "generating"}
    )
    store.put_if_version(updated, expected=0)
    got = store.get(record.session_id, later)
    assert got.expires_at == later + DEFAULT_TTL


def test_put_if_version_missing_raises_not_found(store: InMemorySessionStore) -> None:
    """Conditional write on an absent record raises NotFound."""
    with pytest.raises(NotFound):
        store.put_if_version(make_record("ghost"), expected=0)


def test_delete_removes_record(store: InMemorySessionStore) -> None:
    """Delete permanently removes a record. Validates: R-10.5, R-10.6."""
    record = make_record()
    store.create(record)
    store.delete(record.session_id)
    with pytest.raises(NotFound):
        store.get(record.session_id, BASE_TIME)


def test_delete_absent_is_noop(store: InMemorySessionStore) -> None:
    """Deleting an absent record does not raise. Validates: R-10.5."""
    store.delete("never-existed")  # must not raise


def test_stored_item_has_no_attributes_outside_allowed_list(store: InMemorySessionStore) -> None:
    """The stored record exposes only permitted attributes. Validates: R-10.1, R-10.2."""
    allowed = {
        "session_id",
        "token_hash",
        "state",
        "age_band",
        "subject",
        "language",
        "objects",
        "lesson",
        "activity_status",
        "answers",
        "baseline",
        "end_answer",
        "current_index",
        "stage_events",
        "idempotency",
        "generation_count",
        "created_at",
        "updated_at",
        "expires_at",
        "version",
    }
    forbidden = {"name", "birthday", "address", "school", "email", "image", "images"}
    record = make_record()
    store.create(record)
    got = store.get(record.session_id, BASE_TIME)
    keys = set(got.model_dump().keys())
    assert keys == allowed
    assert keys.isdisjoint(forbidden)


# --- ID generation (in-memory-agnostic) -----------------------------------------------------


def test_session_ids_are_unique_and_input_independent() -> None:
    """IDs are distinct across calls with no inputs. Validates: R-01.2."""
    ids = {new_session_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_session_id_has_at_least_128_bits_of_entropy() -> None:
    """token_urlsafe(32) yields >=128 bits of randomness. Validates: R-01.2."""
    token = new_session_id()
    # token_urlsafe(32) encodes 32 random bytes (256 bits) as base64url without padding.
    assert len(token) >= 43  # ceil(32 * 4 / 3)


def test_forbidden_attribute_cannot_be_constructed() -> None:
    """SessionRecord rejects any attribute outside the allowed list. Validates: R-10.2."""
    with pytest.raises(ValueError):
        SessionRecord(
            session_id="s1",
            token_hash="h",  # noqa: S106 - a hash, not a secret
            state="created",
            age_band=AgeBand.B6_8,
            subject=Subject.ARITHMETIC,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
            expires_at=BASE_TIME,
            child_name="Alice",  # type: ignore[call-arg]  # forbidden identity field
        )
