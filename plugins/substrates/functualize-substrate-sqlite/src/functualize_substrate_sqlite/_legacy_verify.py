"""Steps 4 and 6 of the legacy import, and the undo a failed verification runs.

Step 4 rebuilds the snapshot's manifest from the tables — counts, identities,
terminal/live status, state keys, sequence order and payload digests — and
compares. Step 6 asks a fresh `SqliteRuntimeStore` the same questions through
its read ports. Either disagreeing raises :class:`VerifyError`, and the
importer deletes exactly what it wrote, cutover marker included, in one batch.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize.plugin import WorkflowView
    from functualize_substrate_sqlite._driver import SqlDriver
    from functualize_substrate_sqlite._legacy_source import LegacySnapshot
    from functualize_substrate_sqlite._runtime_store import SqliteRuntimeStore

__all__ = ["VerifyError", "table_manifest", "undo", "verify_ports", "verify_rows"]

SOURCE = "documents"


class VerifyError(Exception):
    """What the tables or the read ports hold is not what the documents said."""


def verify_rows(driver: SqlDriver, legacy: LegacySnapshot) -> None:
    """Step 4: the manifest rebuilt from the tables equals the snapshot's."""
    found = table_manifest(driver, legacy)
    missing = sorted(set(legacy.manifest) ^ set(found))
    differing = sorted(
        k for k in set(legacy.manifest) & set(found) if legacy.manifest[k] != found[k]
    )
    if missing or differing:
        raise VerifyError(f"records missing {missing[:5]}, differing {differing[:5]}")


def _text_digest(text: str | None) -> str:
    return hashlib.sha256((text or "null").encode("utf-8")).hexdigest()


def table_manifest(driver: SqlDriver, legacy: LegacySnapshot) -> dict[str, Any]:
    """What the tables hold for the snapshot's identities, in the manifest's shape."""
    ns, out = legacy.namespace, {}
    for scope_id in legacy.scope_ids:
        row = driver.query(
            "SELECT status, position, lease_generation, lease_owner FROM workflow_scopes "
            "WHERE namespace_id = ? AND id = ?",
            (ns, scope_id),
        )
        if not row:
            continue
        status, position, generation, owner = row[0]
        args = (ns, scope_id)
        out[f"scope:{scope_id}"] = {
            "status": status,
            "position": position,
            "generation": generation,
            "owner": owner,
            "steps": {
                k: _text_digest(v)
                for k, v in driver.query(
                    "SELECT step_key, result FROM workflow_steps WHERE namespace_id = ? AND scope_id = ?",
                    args,
                )
            },
            "branches": dict(
                driver.query(
                    "SELECT decision_key, chosen_target FROM workflow_branches "
                    "WHERE namespace_id = ? AND scope_id = ?",
                    args,
                )
            ),
            "state": {
                k: _text_digest(v)
                for k, v in driver.query(
                    "SELECT key, value FROM scope_state WHERE namespace_id = ? AND scope_id = ?",
                    args,
                )
            },
            "events": [
                [seq, kind, _text_digest(payload)]
                for seq, kind, payload in driver.query(
                    "SELECT seq, type, payload FROM scope_events WHERE namespace_id = ? AND scope_id = ? "
                    "ORDER BY seq",
                    args,
                )
            ],
            "requests": dict(
                driver.query(
                    "SELECT id, status FROM input_requests WHERE namespace_id = ? AND scope_id = ?",
                    args,
                )
            ),
        }
    for run_id in legacy.run_ids:
        row = driver.query(
            "SELECT status, job, scope_id, parent_run_id FROM runs WHERE namespace_id = ? AND id = ?",
            (ns, run_id),
        )
        if not row:
            continue
        status, job, scope_id, parent = row[0]
        out[f"run:{run_id}"] = {
            "status": status,
            "job": job,
            "scope_id": scope_id,
            "parent_run_id": parent,
            "events": [
                [seq, kind, _text_digest(payload)]
                for seq, kind, payload in driver.query(
                    "SELECT seq, type, payload FROM run_events WHERE namespace_id = ? AND run_id = ? "
                    "ORDER BY seq",
                    (ns, run_id),
                )
            ],
        }
    return out


def verify_ports(store: SqliteRuntimeStore, legacy: LegacySnapshot) -> None:
    """Step 6: the read ports answer what the documents said."""
    wrong: list[str] = []
    for key, expected in legacy.manifest.items():
        kind, identity = key.split(":", 1)
        if kind == "run":
            view = store.runs.run(identity)
            if view is None or (view.status, view.job) != (
                expected["status"],
                expected["job"],
            ):
                wrong.append(key)
            continue
        scope: WorkflowView | None = store.workflows.workflow(identity)
        if scope is None or (scope.status, scope.position) != (
            expected["status"],
            expected["position"],
        ):
            wrong.append(key)
            continue
        if [e.seq for e in store.workflows.events_after(identity, 0)] != [
            e[0] for e in expected["events"]
        ]:
            wrong.append(f"{key} events")
        for request_id, status in expected["requests"].items():
            request = store.inputs.request(request_id)
            if request is None or request.status != status:
                wrong.append(f"request:{request_id}")
    if wrong:
        raise VerifyError(f"the read ports disagree on {wrong[:5]}")


def undo(driver: SqlDriver, legacy: LegacySnapshot) -> None:
    """Delete exactly what the import wrote, marker included, in one batch."""
    ns = legacy.namespace
    driver.batch(
        [
            *[
                (
                    "DELETE FROM workflow_scopes WHERE namespace_id = ? AND id = ?",
                    (ns, s),
                )
                for s in legacy.scope_ids
            ],
            *[
                ("DELETE FROM runs WHERE namespace_id = ? AND id = ?", (ns, r))
                for r in legacy.run_ids
            ],
            ("DELETE FROM runtime_cutover WHERE source = ?", (SOURCE,)),
        ]
    )
