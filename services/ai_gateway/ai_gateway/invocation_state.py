"""Pure metadata transitions; callers must persist with an atomic fence/state CAS.

No operation authorizes network dispatch until its returned snapshot and budget
reservation commit together. This module neither persists nor sends requests.
"""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class InvocationTransitions:
    def stale(self, record: dict, *, expected_fence: int, context_digest: str) -> dict:
        state = record.get("state")
        if state not in ("prepared", "dispatch_unknown", "outcome_unknown", "settled_metadata"):
            raise ValueError("Invocation is not active")
        result = self._checked(record, expected_fence, state)
        if result["context_digest"] == context_digest:
            raise ValueError("Invocation context is still current")
        result["state"] = "stale"
        return self._result(result)

    def close_unknown(self, record: dict, *, expected_fence: int, context_digest: str) -> dict:
        result = self._checked(record, expected_fence, "outcome_unknown")
        if result["context_digest"] != context_digest:
            raise ValueError("Invocation context changed")
        result["state"] = "closed_unknown"
        return self._result(result)

    def applied(self, record: dict, *, expected_fence: int, context_digest: str) -> dict:
        result = self._checked(record, expected_fence, "settled_metadata")
        if result["context_digest"] != context_digest:
            raise ValueError("Invocation context changed")
        if any(attempt["state"] != "settled" for attempt in result["attempts"]):
            raise ValueError("Invocation audit not settled")
        result["state"] = "applied"
        return self._result(result)

    def settle_metadata(
        self,
        record: dict,
        *,
        expected_fence: int,
        attempt_id: str,
        retryable_failure: bool = False,
        retry_disposition: str = "none",
    ) -> dict:
        state = record.get("state")
        if state not in ("dispatch_unknown", "outcome_unknown", "closed_unknown", "stale"):
            raise ValueError("Invocation cannot settle")
        result = self._checked(record, expected_fence, state)
        if (
            not result["attempts"]
            or (result["schema_version"] != 3 and len(result["attempts"]) != 1)
            or result["attempts"][-1]["attempt_id"] != attempt_id
            or any(a["state"] != "settled" for a in result["attempts"][:-1])
        ):
            raise ValueError("Attempt identity conflict")
        if type(retryable_failure) is not bool or (
            retryable_failure and result["schema_version"] != 3
        ):
            raise ValueError("Retry evidence is SDK-only")
        result["attempts"][-1]["state"] = "settled"
        context = result["attempts"][-1].get("sdk_context")
        if context is not None:
            if retry_disposition not in ("none", "retry", "fallback") or (
                (retry_disposition != "none") != retryable_failure
            ):
                raise ValueError("Conflicting SDK continuation evidence")
            context["continuation"] = retry_disposition
        if retryable_failure:
            result["attempts"][-1]["retryable_failure"] = True
        result["state"] = state if state in ("closed_unknown", "stale") else "settled_metadata"
        return self._result(result)

    def __init__(self, schema_path: Path):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def _checked(self, record: dict, expected_fence: int, state: str) -> dict:
        if list(self._validator.iter_errors(record)):
            raise ValueError("Invalid invocation metadata")
        if type(expected_fence) is not int or record["fence"] != expected_fence:
            raise ValueError("Stale invocation fence")
        if record["state"] != state:
            raise ValueError("Invocation state does not permit this operation")
        return deepcopy(record)

    def _result(self, record: dict) -> dict:
        if list(self._validator.iter_errors(record)):
            raise ValueError("Invalid invocation transition")
        return record

    def claim(self, record: dict, *, expected_fence: int) -> dict:
        result = self._checked(record, expected_fence, "prepared")
        result["fence"] += 1
        return self._result(result)

    def cancel(self, record: dict, *, expected_fence: int) -> dict:
        result = self._checked(record, expected_fence, "prepared")
        result["state"] = "cancelled_unsent"
        return self._result(result)

    def dispatch(
        self,
        record: dict,
        *,
        expected_fence: int,
        attempt_id: str,
        estimated_cost_micros: int,
        sdk_context: dict | None = None,
    ) -> dict:
        next_attempt = (
            record.get("schema_version") == 3 and record.get("state") == "settled_metadata"
        )
        result = self._checked(
            record, expected_fence, "settled_metadata" if next_attempt else "prepared"
        )
        if next_attempt:
            if not result["attempts"][-1].get("retryable_failure") or any(
                a["state"] != "settled" for a in result["attempts"]
            ):
                raise ValueError("No confirmed retryable failure")
            result["fence"] += 1
        if any(a["attempt_id"] == attempt_id for a in result["attempts"]):
            raise ValueError("Attempt identity reused")
        previous = result["attempts"][-1].get("sdk_context") if result["attempts"] else None
        if previous is not None:
            if sdk_context is None or sdk_context["routing_digest"] != previous["routing_digest"]:
                raise ValueError("SDK routing context changed")
            same_retry = (
                previous["continuation"] == "retry"
                and sdk_context["candidate_index"] == previous["candidate_index"]
                and sdk_context["retry_index"] == previous["retry_index"] + 1
            )
            fallback = (
                previous["continuation"] in ("retry", "fallback")
                and sdk_context["candidate_index"] > previous["candidate_index"]
                and sdk_context["retry_index"] == 0
            )
            if not (same_retry or fallback):
                raise ValueError("SDK cursor cannot repeat or rewind an attempt")
        if sdk_context is not None and sdk_context.get("continuation") != "none":
            raise ValueError("An unsent SDK attempt has no outcome evidence")
        if type(estimated_cost_micros) is not int or estimated_cost_micros < 0:
            raise ValueError("Invalid attempt estimate")
        result["state"] = "dispatch_unknown"
        result["attempts"].append(
            dict(
                attempt_id=attempt_id,
                fence=result["fence"],
                estimated_cost_micros=estimated_cost_micros,
                state="dispatch_unknown",
            )
        )
        if sdk_context is not None:
            result["attempts"][-1]["sdk_context"] = deepcopy(sdk_context)
        return self._result(result)

    def mark_unknown(self, record: dict, *, expected_fence: int) -> dict:
        result = self._checked(record, expected_fence, "dispatch_unknown")
        result["state"] = "outcome_unknown"
        for attempt in result["attempts"]:
            if attempt["state"] == "dispatch_unknown":
                attempt["state"] = "outcome_unknown"
        return self._result(result)
