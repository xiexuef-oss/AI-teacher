from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tutor_api.db import new_id
from tutor_api.models import ContentFactorySource, ContentFactorySourcePermission
from tutor_api.services.content_factory_sources import source_permits


def test_source_permission_requires_matching_active_grant(db, reviewer, clock):
    now = clock.now()
    source = ContentFactorySource(
        id=new_id(),
        title="教研工程样张",
        source_class="original",
        sha256="a" * 64,
        created_by=reviewer.user_id,
        created_at=now,
    )
    db.add(source)
    db.flush()
    scope = (source.id, "print_pdf", "CN-51")
    assert not source_permits(db, *scope, now)
    grant = ContentFactorySourcePermission(
        source_id=source.id,
        operation="print_pdf",
        region_code="CN-51",
        evidence_ref="review-evidence-1",
        reviewed_by=reviewer.user_id,
        valid_from=now,
        valid_until=now + timedelta(days=1),
    )
    db.add(grant)
    db.flush()
    assert not source_permits(db, *scope, now - timedelta(seconds=1))
    assert source_permits(db, *scope, now)
    assert not source_permits(db, source.id, "print_pdf", "CN-50", now)
    assert not source_permits(db, source.id, "generate_variants", "CN-51", now)
    assert not source_permits(db, source.id, "send_to_external_ai", "CN-51", now)
    assert not source_permits(db, *scope, grant.valid_until)
    grant.revoked_at = now
    assert not source_permits(db, *scope, now)


def test_private_student_sources_cannot_enter_content_factory(db, reviewer, clock):
    db.add(
        ContentFactorySource(
            id=new_id(),
            title="私域资料",
            source_class="private_student",
            sha256="a" * 64,
            created_by=reviewer.user_id,
            created_at=clock.now(),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
