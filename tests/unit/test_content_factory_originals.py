from hashlib import sha256
from types import SimpleNamespace

import pytest

from tutor_api.db import new_id
from tutor_api.errors import ApiError
from tutor_api.models import ContentFactorySource, ContentFactorySourcePermission
from tutor_api.services.content_factory_originals import purge_expired, store_original


def test_original_requires_scoped_permission_and_registered_digest(db, reviewer, clock, settings):
    data = b"%PDF-1.4\nfixture"
    now = clock.now()
    source = ContentFactorySource(
        id=new_id(),
        title="工程样张",
        source_class="original",
        sha256=sha256(data).hexdigest(),
        created_by=reviewer.user_id,
        created_at=now,
    )
    db.add(source)
    db.flush()
    ctx = SimpleNamespace(db=db, actor_id=reviewer.user_id, now=clock.now, settings=settings)
    with pytest.raises(ApiError) as denied:
        store_original(ctx, source.id, "CN-51", "sample.pdf", data)
    assert denied.value.status_code == 403
    from datetime import timedelta

    end = now + timedelta(minutes=10)
    db.add(
        ContentFactorySourcePermission(
            source_id=source.id,
            operation="store_original",
            region_code="CN-51",
            evidence_ref="test-license",
            reviewed_by=reviewer.user_id,
            valid_from=now,
            valid_until=end,
        )
    )
    db.flush()
    with pytest.raises(ApiError) as mismatch:
        store_original(ctx, source.id, "CN-51", "sample.pdf", data + b"wrong")
    assert mismatch.value.status_code == 422
    original = store_original(ctx, source.id, "CN-51", "sample.pdf", data)
    assert original.expires_at == end
    assert original.content == data
    assert purge_expired(db, end) == 1
