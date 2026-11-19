from datetime import UTC, datetime

from tutor_api.services.learning_jobs import enqueue


def test_learning_job_is_private_and_cancel_is_replayable(db, student, new_student):
    other = new_student()
    job = enqueue(db, student.user_id, "test-pack", datetime.now(UTC))
    db.commit()
    path = f"/learning/jobs/{job}"
    assert student.data("GET", path) == {"id": job, "status": "queued", "attempts": 0}
    other.error("GET", path, expect=404)
    other.error("POST", f"{path}/cancel", expect=404)
    first = student.data("POST", f"{path}/cancel", key="learning-cancel")
    assert first["status"] == "cancelled"
    assert student.data("POST", f"{path}/cancel", key="learning-cancel") == first
    student.error("POST", f"{path}/cancel", expect=409)
