import csv
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fieldbook.errors import AmbiguityError, NotFoundError, ValidationError
from fieldbook.freshness import attrs_with_local_capture, experiment_freshness, local_artifact_metadata
from fieldbook.git_info import current_git_revision
from fieldbook.ids import new_id
from fieldbook.time_utils import utc_now
from fieldbook.validation import (
    ARTIFACT_TYPES,
    ENTITY_TYPES,
    EXPERIMENT_STATUSES,
    JOB_RUN_ROLES,
    JOB_RUN_STATUSES,
    JOB_STATUSES,
    NOTE_STATUSES,
    NOTE_BODY_FORMATS,
    NOTE_TYPES,
    RUN_STATUSES,
    RUN_KINDS,
    VALIDATION_STATUSES,
    attrs_json,
    file_sha256,
    load_attrs,
    normalize_tag,
    require_choice,
    validate_attrs_dict,
    validate_content_hash,
    validate_idempotency_key,
    validate_metric_value,
    validate_note_body,
    validate_note_title,
    validate_utc_z,
)


STATUS_NOTE_LIMIT = 10
STATUS_RECENT_NOTE_LIMIT = 5
CONTEXT_ACTIVE_NOTE_LIMIT = 20
CONTEXT_RECENT_NOTE_LIMIT = 5
NOTE_PREVIEW_CHARS = 200


class Repository:
    def __init__(self, conn: sqlite3.Connection, *, current_session_id: str | None = None):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.current_session_id = self._valid_open_session_id(current_session_id)

    def create_experiment(
        self,
        *,
        name: str,
        description: str | None,
        tags: list[str],
        attrs: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        idempotency_key = validate_idempotency_key(idempotency_key)
        if idempotency_key is not None:
            existing = self.conn.execute(
                "SELECT * FROM experiments WHERE idempotency_key = ? AND deleted_at IS NULL ORDER BY id LIMIT 1",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                result = self._experiment_dict(existing)
                result["existed"] = True
                return result
        now = utc_now()
        experiment_id = new_id("exp")
        normalized_tags = sorted({normalize_tag(tag) for tag in tags})
        with self.conn:
            self.conn.execute(
                "INSERT INTO experiments (id, name, description, idempotency_key, created_at, updated_at, attrs_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (experiment_id, name, description, idempotency_key, now, now, attrs_json(attrs)),
            )
            self._replace_experiment_tags(experiment_id, normalized_tags)
        result = self.get_experiment(experiment_id)
        result["existed"] = False
        return result

    def list_experiments(self, *, tag: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
        params: list[Any] = []
        query = (
            "SELECT e.* FROM experiments e "
            "WHERE (? OR e.deleted_at IS NULL)"
        )
        params.append(1 if include_archived else 0)
        if tag:
            query += " AND EXISTS (SELECT 1 FROM experiment_tags t WHERE t.experiment_id = e.id AND t.tag = ?)"
            params.append(normalize_tag(tag))
        query += " ORDER BY e.updated_at DESC, e.id"
        rows = self.conn.execute(query, params).fetchall()
        return [self._experiment_dict(row) for row in rows]

    def get_experiment(self, ref: str) -> dict[str, Any]:
        row = self._resolve_row("experiments", ref, name_column="name")
        return self._experiment_dict(row)

    def archive_experiment(self, ref: str) -> dict[str, Any]:
        experiment = self.get_experiment(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE experiments SET status = 'archived', deleted_at = COALESCE(deleted_at, ?), "
                "updated_at = ? WHERE id = ?",
                (now, now, experiment["id"]),
            )
        return self.get_experiment(experiment["id"])

    def checkpoint_experiment(
        self,
        ref: str,
        *,
        body: str | None,
        archive: bool,
        errata: bool,
        stale_hours: float = 24.0,
    ) -> dict[str, Any]:
        experiment = self.get_experiment(ref)
        freshness = experiment_freshness(
            self.conn,
            experiment_id=experiment["id"],
            cwd=Path.cwd(),
            stale_checkpoint_hours=stale_hours,
        )
        note_body = self._checkpoint_body(body=body, freshness=freshness)
        note = self.add_note(
            entity_type="experiment",
            entity_ref=experiment["id"],
            note_type="checkpoint",
            status="open",
            title="Experiment checkpoint",
            body=note_body,
            body_format="markdown",
            author=None,
            attrs={},
            errata=errata,
        )
        if archive:
            experiment = self.archive_experiment(experiment["id"])
        else:
            experiment = self.get_experiment(experiment["id"])
        return {
            "experiment": experiment,
            "note": note,
            "freshness": freshness,
        }

    def experiment_status(self, ref: str, *, stale_hours: float = 24.0) -> dict[str, Any]:
        experiment = self.get_experiment(ref)
        experiment_id = experiment["id"]
        run_count = self.conn.execute(
            "SELECT COUNT(*) FROM experiment_runs er JOIN runs r ON r.id = er.run_id "
            "WHERE er.experiment_id = ? AND r.deleted_at IS NULL",
            (experiment_id,),
        ).fetchone()[0]
        job_counts = dict(
            self.conn.execute(
                "SELECT status, COUNT(*) FROM jobs WHERE experiment_id = ? AND deleted_at IS NULL GROUP BY status",
                (experiment_id,),
            ).fetchall()
        )
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=stale_hours)).isoformat().replace("+00:00", "Z")
        stale_rows = self.conn.execute(
            "SELECT * FROM jobs WHERE experiment_id = ? AND status IN ('queued', 'running') "
            "AND updated_at < ? AND deleted_at IS NULL ORDER BY updated_at LIMIT 20",
            (experiment_id, cutoff),
        ).fetchall()
        failed_rows = self.conn.execute(
            "SELECT * FROM jobs WHERE experiment_id = ? AND status = 'failed' AND deleted_at IS NULL "
            "ORDER BY updated_at DESC LIMIT 20",
            (experiment_id,),
        ).fetchall()
        blocker_rows = self.conn.execute(
            "SELECT * FROM v_jobs_with_recovery_v1 WHERE experiment_id = ? AND is_blocking_failed = 1 "
            "ORDER BY updated_at DESC, job_id LIMIT 20",
            (experiment_id,),
        ).fetchall()
        recovery_rows = self.conn.execute(
            "SELECT * FROM v_jobs_with_recovery_v1 WHERE experiment_id = ? AND is_recovery_in_progress = 1 "
            "ORDER BY updated_at DESC, job_id LIMIT 20",
            (experiment_id,),
        ).fetchall()
        recovered_rows = self.conn.execute(
            "SELECT * FROM v_jobs_with_recovery_v1 WHERE experiment_id = ? AND is_recovered_failed = 1 "
            "ORDER BY updated_at DESC, job_id LIMIT 20",
            (experiment_id,),
        ).fetchall()
        submitting_rows = self.conn.execute(
            "SELECT * FROM jobs WHERE experiment_id = ? AND status = 'submitting' AND deleted_at IS NULL "
            "ORDER BY updated_at DESC, id LIMIT 20",
            (experiment_id,),
        ).fetchall()
        unknown_submit_rows = self.conn.execute(
            "SELECT * FROM jobs WHERE experiment_id = ? AND status = 'unknown_submit' AND deleted_at IS NULL "
            "ORDER BY updated_at DESC, id LIMIT 20",
            (experiment_id,),
        ).fetchall()
        validation_rows = self.conn.execute(
            "SELECT * FROM validations WHERE entity_type = 'experiment' AND entity_id = ? AND deleted_at IS NULL "
            "ORDER BY updated_at DESC, id",
            (experiment_id,),
        ).fetchall()
        validation_summary = self._validation_summary(validation_rows)
        artifact_rows = self._experiment_artifact_rows(experiment_id, limit=20)
        errata_rows = self._experiment_errata_rows(experiment_id, limit=20)
        freshness = experiment_freshness(self.conn, experiment_id=experiment_id, cwd=Path.cwd(), stale_checkpoint_hours=stale_hours)
        active_job_count = sum(job_counts.get(status, 0) for status in ("submitting", "unknown_submit", "queued", "running"))
        has_active_blockers = bool(blocker_rows or validation_summary["failed"] or validation_summary["unknown_blocking"])
        run_progress = self._experiment_run_progress(experiment_id, experiment_attrs=experiment["attrs"])
        return {
            "experiment": experiment,
            "run_count": run_count,
            "runs": run_progress,
            "job_counts": job_counts,
            "ready": {
                "is_ready": not has_active_blockers and active_job_count == 0,
                "has_active_blockers": has_active_blockers,
                "blocker_count": len(blocker_rows) + len(validation_summary["failed"]) + len(validation_summary["unknown_blocking"]),
                "active_job_count": active_job_count,
                "recovery_in_progress_count": len(recovery_rows),
                "recovered_failed_count": len(recovered_rows),
                "submission_uncertainty_count": len(submitting_rows) + len(unknown_submit_rows),
                "validation_status": validation_summary["status"],
            },
            "note_counts": self._experiment_note_counts(experiment_id),
            "notes": self._experiment_compact_notes(experiment_id),
            "stale_threshold_hours": stale_hours,
            "stale_jobs": [self._job_dict(row) for row in stale_rows],
            "failed_jobs": [self._job_dict(row) for row in failed_rows],
            "blocking_failed_jobs": [self._job_dict(row) for row in blocker_rows],
            "recovery_in_progress_failed_jobs": [self._job_dict(row) for row in recovery_rows],
            "recovered_failed_jobs": [self._job_dict(row) for row in recovered_rows],
            "submission_in_progress_jobs": [self._job_dict(row) for row in submitting_rows],
            "submission_unknown_jobs": [self._job_dict(row) for row in unknown_submit_rows],
            "validations": validation_summary,
            "key_artifacts": [self._artifact_dict(row) for row in artifact_rows],
            "freshness": {
                key: value
                for key, value in freshness.items()
                if key not in {"drifted_artifacts", "stale_validations"}
            },
            "historical": {
                "erratum_count": self._experiment_errata_count(experiment_id),
                "recent_errata": errata_rows,
            },
        }

    def experiment_context(self, ref: str, *, stale_hours: float = 24.0) -> dict[str, Any]:
        status = self.experiment_status(ref, stale_hours=stale_hours)
        experiment_id = status["experiment"]["id"]
        status["notes"] = {
            "open_handoffs": [
                self._note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="handoff",
                    status="open",
                    limit=CONTEXT_ACTIVE_NOTE_LIMIT,
                )
            ],
            "open_next_actions": [
                self._note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="next-action",
                    status="open",
                    limit=CONTEXT_ACTIVE_NOTE_LIMIT,
                )
            ],
            "open_debug": [
                self._note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="debug",
                    status="open",
                    limit=CONTEXT_ACTIVE_NOTE_LIMIT,
                )
            ],
            "recent_research": [
                self._note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="research",
                    status=None,
                    limit=CONTEXT_RECENT_NOTE_LIMIT,
                )
            ],
            "recent_decisions": [
                self._note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="decision",
                    status=None,
                    limit=CONTEXT_RECENT_NOTE_LIMIT,
                )
            ],
            "recent_checkpoints": [
                self._note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="checkpoint",
                    status=None,
                    limit=CONTEXT_RECENT_NOTE_LIMIT,
                )
            ],
        }
        freshness = experiment_freshness(self.conn, experiment_id=experiment_id, cwd=Path.cwd(), stale_checkpoint_hours=stale_hours)
        status["freshness"] = freshness
        return status

    def cleanup_experiment(self, ref: str, *, apply: bool) -> dict[str, Any]:
        experiment = self.get_experiment(ref)
        experiment_id = experiment["id"]
        if apply and experiment["deleted_at"] is not None:
            raise ValidationError("experiment cleanup requires an active experiment")
        planned = self._experiment_cleanup_plan(experiment_id)
        counts = {
            "debug_notes_resolved": 0,
            "validations_archived": 0,
        }
        checkpoint: dict[str, Any] | None = None
        if apply:
            now = utc_now()
            with self.conn:
                for note in planned["debug_notes"]:
                    self.conn.execute(
                        "UPDATE notes SET status = 'resolved', resolved_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, note["id"]),
                    )
                    counts["debug_notes_resolved"] += 1
                for validation in planned["validations"]:
                    self.conn.execute(
                        "UPDATE validations SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                        (now, now, validation["id"]),
                    )
                    counts["validations_archived"] += 1
            if counts["debug_notes_resolved"] or counts["validations_archived"]:
                checkpoint = self.add_note(
                    entity_type="experiment",
                    entity_ref=experiment_id,
                    note_type="checkpoint",
                    status="open",
                    title="Experiment cleanup",
                    body=self._cleanup_checkpoint_body(planned=planned, counts=counts),
                    body_format="markdown",
                    author=None,
                    attrs={"fieldbook.cleanup": True},
                    errata=False,
                )
        return {
            "experiment": self.get_experiment(experiment_id),
            "applied": apply,
            "planned": planned,
            "counts": counts,
            "checkpoint": checkpoint,
        }

    def add_run(
        self,
        *,
        name: str,
        description: str | None,
        experiment_ref: str | None,
        status: str,
        kind: str,
        idempotency_key: str | None,
        external_system: str | None,
        external_id: str | None,
        parent_run_ref: str | None,
        attrs: dict[str, Any],
        update_existing: bool,
    ) -> dict[str, Any]:
        require_choice(status, RUN_STATUSES, "run status")
        require_choice(kind, RUN_KINDS, "run kind")
        idempotency_key = validate_idempotency_key(idempotency_key)
        existing = self._existing_external("runs", external_system, external_id)
        now = utc_now()
        experiment_id = self._active_experiment_id(experiment_ref) if experiment_ref else None
        if idempotency_key is not None and experiment_id is not None:
            idempotent_existing = self.conn.execute(
                "SELECT * FROM runs WHERE experiment_id = ? AND idempotency_key = ? AND deleted_at IS NULL "
                "ORDER BY id LIMIT 1",
                (experiment_id, idempotency_key),
            ).fetchone()
            if idempotent_existing is not None:
                result = self._run_dict(idempotent_existing)
                result["existed"] = True
                return result
        if existing and not update_existing:
            raise AmbiguityError(
                f"run external identifier {external_system}:{external_id} already exists as {existing['id']}"
            )
        parent_run_id = self._parent_run_id(parent_run_ref)
        if existing and parent_run_id == existing["id"]:
            raise ValidationError("parent_run_id cannot reference the run itself")
        with self.conn:
            if existing:
                run_id = existing["id"]
                self.conn.execute(
                    "UPDATE runs SET name = ?, description = ?, status = ?, kind = ?, "
                    "experiment_id = COALESCE(?, experiment_id), idempotency_key = COALESCE(?, idempotency_key), "
                    "parent_run_id = COALESCE(?, parent_run_id), updated_at = ?, attrs_json = ? WHERE id = ?",
                    (
                        name,
                        description,
                        status,
                        kind,
                        experiment_id,
                        idempotency_key,
                        parent_run_id,
                        now,
                        attrs_json(attrs),
                        run_id,
                    ),
                )
                existed = True
            else:
                run_id = new_id("run")
                self.conn.execute(
                    "INSERT INTO runs (id, experiment_id, name, description, status, kind, idempotency_key, "
                    "external_system, external_id, parent_run_id, created_at, updated_at, attrs_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        experiment_id,
                        name,
                        description,
                        status,
                        kind,
                        idempotency_key,
                        external_system,
                        external_id,
                        parent_run_id,
                        now,
                        now,
                        attrs_json(attrs),
                    ),
                )
                existed = False
            if experiment_id:
                self._link_run_ids(experiment_id, run_id)
        result = self.get_run(run_id)
        result["existed"] = existed
        return result

    def list_runs(self, *, experiment_ref: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
        params: list[Any] = [1 if include_archived else 0]
        query = "SELECT DISTINCT r.* FROM runs r"
        if experiment_ref:
            experiment_id = self.get_experiment(experiment_ref)["id"]
            query += " JOIN experiment_runs er ON er.run_id = r.id"
            params.append(experiment_id)
        query += " WHERE (? OR r.deleted_at IS NULL)"
        if experiment_ref:
            query += " AND er.experiment_id = ?"
        query += " ORDER BY r.updated_at DESC, r.id"
        return [self._run_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_run(self, ref: str) -> dict[str, Any]:
        return self._run_dict(self._resolve_row("runs", ref, name_column="name"))

    def link_run(self, *, run_ref: str, experiment_ref: str) -> dict[str, Any]:
        run_id = self.get_run(run_ref)["id"]
        experiment_id = self._active_experiment_id(experiment_ref)
        with self.conn:
            self._link_run_ids(experiment_id, run_id)
        return self.get_run(run_id)

    def archive_run(self, ref: str) -> dict[str, Any]:
        run = self.get_run(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET status = 'archived', deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                (now, now, run["id"]),
            )
        return self.get_run(run["id"])

    def add_job(
        self,
        *,
        experiment_ref: str | None,
        run_ref: str | None,
        name: str | None,
        status: str,
        command: str | None,
        launcher: str | None,
        external_system: str | None,
        external_id: str | None,
        failure_reason: str | None,
        started_at: str | None,
        finished_at: str | None,
        retry_of_ref: str | None,
        attrs: dict[str, Any],
        update_existing: bool,
    ) -> dict[str, Any]:
        require_choice(status, JOB_STATUSES, "job status")
        validate_utc_z(started_at, "started_at")
        validate_utc_z(finished_at, "finished_at")
        existing = self._existing_external("jobs", external_system, external_id)
        if existing and not update_existing:
            raise AmbiguityError(
                f"job external identifier {external_system}:{external_id} already exists as {existing['id']}"
            )
        run_id = self.get_run(run_ref)["id"] if run_ref else None
        experiment_id = self._active_experiment_id(experiment_ref) if experiment_ref else None
        if run_id and not experiment_id:
            experiment_ids = self._run_experiment_ids(run_id)
            if len(experiment_ids) == 1:
                experiment_id = self._active_experiment_id(experiment_ids[0])
        code_commit, code_dirty = current_git_revision()
        now = utc_now()
        with self.conn:
            if existing:
                job_id = existing["id"]
                retry_of_id = self._retry_of_id(job_id=job_id, retry_of_ref=retry_of_ref)
                self.conn.execute(
                    "UPDATE jobs SET experiment_id = ?, run_id = ?, name = ?, status = ?, command = ?, launcher = ?, "
                    "failure_reason = ?, code_commit = ?, code_dirty = ?, started_at = ?, finished_at = ?, "
                    "retry_of = COALESCE(?, retry_of), updated_at = ?, attrs_json = ? WHERE id = ?",
                    (
                        experiment_id,
                        run_id,
                        name,
                        status,
                        command,
                        launcher,
                        failure_reason,
                        code_commit,
                        code_dirty,
                        started_at,
                        finished_at,
                        retry_of_id,
                        now,
                        attrs_json(attrs),
                        job_id,
                    ),
                )
            else:
                job_id = new_id("job")
                retry_of_id = self._retry_of_id(job_id=job_id, retry_of_ref=retry_of_ref)
                self.conn.execute(
                    "INSERT INTO jobs (id, experiment_id, run_id, name, status, command, launcher, external_system, "
                    "external_id, retry_of, failure_reason, code_commit, code_dirty, created_at, updated_at, started_at, "
                    "finished_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job_id,
                        experiment_id,
                        run_id,
                        name,
                        status,
                        command,
                        launcher,
                        external_system,
                        external_id,
                        retry_of_id,
                        failure_reason,
                        code_commit,
                        code_dirty,
                        now,
                        now,
                        started_at,
                        finished_at,
                        attrs_json(attrs),
                    ),
                )
            if run_id:
                self._upsert_job_run(
                    job_id=job_id,
                    run_id=run_id,
                    role="other",
                    status=status,
                    failure_reason=failure_reason,
                    started_at=started_at,
                    finished_at=finished_at,
                    attrs={},
                )
        return self.get_job(job_id)

    def link_job_run(
        self,
        *,
        job_ref: str,
        run_ref: str,
        role: str,
        status: str,
        failure_reason: str | None,
        started_at: str | None = None,
        finished_at: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = self.get_job(job_ref)["id"]
        run_id = self.get_run(run_ref)["id"]
        require_choice(role, JOB_RUN_ROLES, "job-run role")
        require_choice(status, JOB_RUN_STATUSES, "job-run status")
        validate_utc_z(started_at, "started_at")
        validate_utc_z(finished_at, "finished_at")
        with self.conn:
            self._upsert_job_run(
                job_id=job_id,
                run_id=run_id,
                role=role,
                status=status,
                failure_reason=failure_reason,
                started_at=started_at,
                finished_at=finished_at,
                attrs=attrs or {},
            )
        return self.get_job_run(job_ref=job_id, run_ref=run_id)

    def get_job_run(self, *, job_ref: str, run_ref: str) -> dict[str, Any]:
        job_id = self.get_job(job_ref)["id"]
        run_id = self.get_run(run_ref)["id"]
        row = self.conn.execute(
            "SELECT * FROM job_runs WHERE job_id = ? AND run_id = ? AND deleted_at IS NULL",
            (job_id, run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"job/run link not found: {job_id} -> {run_id}")
        return self._job_run_dict(row)

    def link_job_retry(self, *, job_ref: str, retry_of_ref: str) -> dict[str, Any]:
        job = self.get_job(job_ref)
        retry_of_id = self._retry_of_id(job_id=job["id"], retry_of_ref=retry_of_ref)
        now = utc_now()
        with self.conn:
            self.conn.execute("UPDATE jobs SET retry_of = ?, updated_at = ? WHERE id = ?", (retry_of_id, now, job["id"]))
        return self.get_job(job["id"])

    def update_job_status(
        self,
        *,
        job_ref: str,
        status: str,
        failure_reason: str | None,
        started_at: str | None,
        finished_at: str | None,
        external_system: str | None = None,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        require_choice(status, JOB_STATUSES, "job status")
        validate_utc_z(started_at, "started_at")
        validate_utc_z(finished_at, "finished_at")
        job = self.get_job(job_ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE jobs SET status = ?, failure_reason = COALESCE(?, failure_reason), "
                "started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at), "
                "external_system = COALESCE(?, external_system), external_id = COALESCE(?, external_id), updated_at = ? "
                "WHERE id = ?",
                (status, failure_reason, started_at, finished_at, external_system, external_id, now, job["id"]),
            )
        return self.get_job(job["id"])

    def list_jobs(
        self,
        *,
        experiment_ref: str | None = None,
        run_ref: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [1 if include_archived else 0]
        query = "SELECT * FROM jobs WHERE (? OR deleted_at IS NULL)"
        if experiment_ref:
            query += " AND experiment_id = ?"
            params.append(self.get_experiment(experiment_ref)["id"])
        if run_ref:
            query += " AND run_id = ?"
            params.append(self.get_run(run_ref)["id"])
        if status:
            require_choice(status, JOB_STATUSES, "job status")
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, id"
        return [self._job_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_job(self, ref: str) -> dict[str, Any]:
        return self._job_dict(self._resolve_row("jobs", ref, name_column="name"))

    def archive_job(self, ref: str) -> dict[str, Any]:
        job = self.get_job(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute("UPDATE jobs SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?", (now, now, job["id"]))
        return self.get_job(job["id"])

    def add_validation(
        self,
        *,
        entity_type: str,
        entity_ref: str,
        check_name: str,
        status: str,
        expected_value: str | None,
        measured_value: str | None,
        details: dict[str, Any],
        source_artifact_ref: str | None,
        source_job_ref: str | None,
        attrs: dict[str, Any],
        errata: bool = False,
    ) -> dict[str, Any]:
        entity_id = self._resolve_entity_id(entity_type, entity_ref) if errata else self._active_entity_id(entity_type, entity_ref)
        self._validate_post_archive_write(entity_type, entity_id, errata=errata, label="validation")
        require_choice(status, VALIDATION_STATUSES, "validation status")
        if not check_name.strip():
            raise ValidationError("validation check_name must not be empty")
        validate_attrs_dict(attrs)
        if not isinstance(details, dict):
            raise ValidationError("validation details must be a JSON object")
        source_artifact_id = self.get_artifact(source_artifact_ref)["id"] if source_artifact_ref else None
        source_job_id = self.get_job(source_job_ref)["id"] if source_job_ref else None
        now = utc_now()
        existing = self.conn.execute(
            "SELECT * FROM validations WHERE entity_type = ? AND entity_id = ? AND check_name = ? AND deleted_at IS NULL",
            (entity_type, entity_id, check_name),
        ).fetchone()
        if errata:
            attrs = self._errata_attrs(attrs, now=now, replaces=existing["id"] if existing else None)
        with self.conn:
            if existing and errata:
                self.conn.execute(
                    "UPDATE validations SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                    (now, now, existing["id"]),
                )
                validation_id = new_id("val")
                self.conn.execute(
                    "INSERT INTO validations (id, entity_type, entity_id, check_name, status, expected_value, "
                    "measured_value, details_json, source_artifact_id, source_job_id, session_id, created_at, "
                    "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        validation_id,
                        entity_type,
                        entity_id,
                        check_name,
                        status,
                        expected_value,
                        measured_value,
                        attrs_json(details),
                        source_artifact_id,
                        source_job_id,
                        self.current_session_id,
                        now,
                        now,
                        attrs_json(attrs),
                    ),
                )
            elif existing:
                validation_id = existing["id"]
                self.conn.execute(
                    "UPDATE validations SET status = ?, expected_value = ?, measured_value = ?, details_json = ?, "
                    "source_artifact_id = COALESCE(?, source_artifact_id), source_job_id = COALESCE(?, source_job_id), "
                    "session_id = COALESCE(?, session_id), updated_at = ?, attrs_json = ? WHERE id = ?",
                    (
                        status,
                        expected_value,
                        measured_value,
                        attrs_json(details),
                        source_artifact_id,
                        source_job_id,
                        self.current_session_id,
                        now,
                        attrs_json(attrs),
                        validation_id,
                    ),
                )
            else:
                validation_id = new_id("val")
                self.conn.execute(
                    "INSERT INTO validations (id, entity_type, entity_id, check_name, status, expected_value, "
                    "measured_value, details_json, source_artifact_id, source_job_id, session_id, created_at, "
                    "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        validation_id,
                        entity_type,
                        entity_id,
                        check_name,
                        status,
                        expected_value,
                        measured_value,
                        attrs_json(details),
                        source_artifact_id,
                        source_job_id,
                        self.current_session_id,
                        now,
                        now,
                        attrs_json(attrs),
                    ),
                )
        return self.get_validation(validation_id)

    def list_validations(
        self,
        *,
        entity_type: str | None = None,
        entity_ref: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [1 if include_archived else 0]
        query = "SELECT * FROM validations WHERE (? OR deleted_at IS NULL)"
        if entity_type:
            require_choice(entity_type, ENTITY_TYPES, "entity type")
            query += " AND entity_type = ?"
            params.append(entity_type)
        if entity_ref:
            if not entity_type:
                raise ValidationError("--entity-id requires --entity-type")
            query += " AND entity_id = ?"
            params.append(self._resolve_entity_id(entity_type, entity_ref))
        if status:
            require_choice(status, VALIDATION_STATUSES, "validation status")
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, id"
        return [self._validation_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_validation(self, ref: str) -> dict[str, Any]:
        return self._validation_dict(self._resolve_row("validations", ref))

    def archive_validation(self, ref: str) -> dict[str, Any]:
        validation = self.get_validation(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE validations SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                (now, now, validation["id"]),
            )
        return self.get_validation(validation["id"])

    def add_artifact(
        self,
        *,
        experiment_ref: str | None = None,
        run_ref: str | None,
        job_ref: str | None,
        artifact_type: str,
        uri: str,
        content_hash: str | None,
        attrs: dict[str, Any],
        update_existing: bool = False,
        errata: bool = False,
    ) -> dict[str, Any]:
        require_choice(artifact_type, ARTIFACT_TYPES, "artifact type")
        validate_content_hash(content_hash)
        experiment_id = self._experiment_id_for_artifact_target(experiment_ref, errata=errata) if experiment_ref else None
        run_id = self.get_run(run_ref)["id"] if run_ref else None
        job_id = self.get_job(job_ref)["id"] if job_ref else None
        if not experiment_id and not run_id and not job_id:
            raise ValidationError("artifact requires --experiment, --run, or --job")
        self._validate_artifact_targets_post_archive(
            experiment_id=experiment_id,
            run_id=run_id,
            job_id=job_id,
            errata=errata,
        )
        attrs = attrs_with_local_capture(attrs, uri=uri, cwd=Path.cwd())
        existing = self.conn.execute(
            "SELECT * FROM artifacts WHERE uri = ? AND deleted_at IS NULL",
            (uri,),
        ).fetchone()
        if existing and errata:
            target_owner_ids = self._artifact_target_experiment_ids(experiment_id=experiment_id, run_id=run_id, job_id=job_id)
            existing_owner_ids = self._artifact_row_experiment_ids(existing)
            if target_owner_ids and existing_owner_ids and not (target_owner_ids & existing_owner_ids):
                raise AmbiguityError(f"artifact URI already exists outside the errata target experiments as {existing['id']}: {uri}")
        if existing and not update_existing:
            if not errata:
                raise AmbiguityError(f"artifact URI already exists as {existing['id']}: {uri}")
        now = utc_now()
        if errata:
            attrs = self._errata_attrs(attrs, now=now, replaces=existing["id"] if existing else None)
        with self.conn:
            if existing and errata:
                self.conn.execute(
                    "UPDATE artifacts SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                    (now, now, existing["id"]),
                )
                artifact_id = new_id("art")
                self.conn.execute(
                    "INSERT INTO artifacts (id, experiment_id, run_id, job_id, type, uri, content_hash, created_at, "
                    "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact_id,
                        experiment_id,
                        run_id,
                        job_id,
                        artifact_type,
                        uri,
                        content_hash,
                        now,
                        now,
                        attrs_json(attrs),
                    ),
                )
            elif existing:
                artifact_id = existing["id"]
                self.conn.execute(
                    "UPDATE artifacts SET experiment_id = COALESCE(?, experiment_id), run_id = COALESCE(?, run_id), "
                    "job_id = COALESCE(?, job_id), type = ?, content_hash = COALESCE(?, content_hash), "
                    "updated_at = ?, attrs_json = ? WHERE id = ?",
                    (experiment_id, run_id, job_id, artifact_type, content_hash, now, attrs_json(attrs), artifact_id),
                )
            else:
                artifact_id = new_id("art")
                self.conn.execute(
                    "INSERT INTO artifacts (id, experiment_id, run_id, job_id, type, uri, content_hash, created_at, "
                    "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact_id,
                        experiment_id,
                        run_id,
                        job_id,
                        artifact_type,
                        uri,
                        content_hash,
                        now,
                        now,
                        attrs_json(attrs),
                    ),
                )
        return self.get_artifact(artifact_id)

    def refresh_local_artifact(self, artifact_ref: str, *, update_hash: bool = False) -> dict[str, Any]:
        artifact = self.get_artifact(artifact_ref)
        metadata = local_artifact_metadata(artifact["uri"], cwd=Path.cwd())
        if metadata is None:
            raise ValidationError(f"artifact URI is not a readable local file: {artifact['uri']}")
        attrs = {**artifact["attrs"], **metadata}
        content_hash = file_sha256(Path(metadata["fieldbook.local_path_at_capture"])) if update_hash else artifact["content_hash"]
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE artifacts SET content_hash = ?, attrs_json = ?, updated_at = ? WHERE id = ?",
                (content_hash, attrs_json(attrs), now, artifact["id"]),
            )
        return self.get_artifact(artifact["id"])

    def list_artifacts(
        self,
        *,
        experiment_ref: str | None = None,
        run_ref: str | None = None,
        job_ref: str | None = None,
        artifact_type: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        if experiment_ref and not run_ref and not job_ref and not include_archived:
            experiment_id = self.get_experiment(experiment_ref)["id"]
            rows = self._experiment_artifact_rows(experiment_id, limit=1_000_000)
            artifacts = [self._artifact_dict(row) for row in rows]
            if artifact_type:
                require_choice(artifact_type, ARTIFACT_TYPES, "artifact type")
                artifacts = [artifact for artifact in artifacts if artifact["type"] == artifact_type]
            return artifacts
        params: list[Any] = [1 if include_archived else 0]
        query = "SELECT * FROM artifacts WHERE (? OR deleted_at IS NULL)"
        if experiment_ref:
            query += " AND experiment_id = ?"
            params.append(self.get_experiment(experiment_ref)["id"])
        if run_ref:
            query += " AND run_id = ?"
            params.append(self.get_run(run_ref)["id"])
        if job_ref:
            query += " AND job_id = ?"
            params.append(self.get_job(job_ref)["id"])
        if artifact_type:
            require_choice(artifact_type, ARTIFACT_TYPES, "artifact type")
            query += " AND type = ?"
            params.append(artifact_type)
        query += " ORDER BY updated_at DESC, id"
        return [self._artifact_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def export_metrics_long(
        self,
        *,
        experiment_ref: str,
        output_path: Path,
        metric_names: list[str] | None,
    ) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_ref)
        rows = self._metric_export_rows(experiment["id"], metric_names)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "experiment_id",
            "run_id",
            "run_name",
            "metric_id",
            "metric_name",
            "value",
            "step",
            "split",
            "source_job_id",
            "source_artifact_id",
            "updated_at",
        ]
        with output_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        artifact = self.add_artifact(
            experiment_ref=experiment["id"],
            run_ref=None,
            job_ref=None,
            artifact_type="metric-table",
            uri=str(output_path),
            content_hash=file_sha256(output_path),
            attrs={"fieldbook.export": "metrics-long"},
            update_existing=True,
        )
        return {"path": str(output_path), "row_count": len(rows), "artifact": artifact}

    def export_runs_wide(
        self,
        *,
        experiment_ref: str,
        output_path: Path,
        metric_names: list[str] | None,
    ) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_ref)
        runs = self.list_runs(experiment_ref=experiment["id"], include_archived=False)
        export_rows = self._metric_export_rows(experiment["id"], metric_names)
        metric_columns = self._wide_metric_columns(export_rows, metric_names)
        provenance_columns = [
            f"{column}__source_job_id" for column in metric_columns
        ] + [
            f"{column}__source_job_code_commit" for column in metric_columns
        ] + [
            f"{column}__source_artifact_id" for column in metric_columns
        ] + [
            f"{column}__source_artifact_uri" for column in metric_columns
        ]
        values: dict[tuple[str, str], float] = {}
        provenance: dict[tuple[str, str], dict[str, Any]] = {}
        for row in export_rows:
            column = row["metric_name"] if metric_names else self._wide_metric_column(row)
            if (row["run_id"], column) in values:
                raise ValidationError(
                    f"multiple metric rows match wide export column {column!r} for run {row['run_id']}; "
                    "select a less ambiguous metric set"
                )
            values[(row["run_id"], column)] = row["value"]
            provenance[(row["run_id"], column)] = self._metric_provenance(row)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "experiment_id",
            "run_id",
            "run_name",
            "status",
            "external_system",
            "external_id",
            *metric_columns,
            *provenance_columns,
        ]
        with output_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for run in runs:
                row = {
                    "experiment_id": experiment["id"],
                    "run_id": run["id"],
                    "run_name": run["name"],
                    "status": run["status"],
                    "external_system": run["external_system"],
                    "external_id": run["external_id"],
                }
                row.update({column: values.get((run["id"], column)) for column in metric_columns})
                for column in metric_columns:
                    source = provenance.get((run["id"], column), {})
                    row[f"{column}__source_job_id"] = source.get("source_job_id")
                    row[f"{column}__source_job_code_commit"] = source.get("source_job_code_commit")
                    row[f"{column}__source_artifact_id"] = source.get("source_artifact_id")
                    row[f"{column}__source_artifact_uri"] = source.get("source_artifact_uri")
                writer.writerow(row)
        artifact = self.add_artifact(
            experiment_ref=experiment["id"],
            run_ref=None,
            job_ref=None,
            artifact_type="metric-table",
            uri=str(output_path),
            content_hash=file_sha256(output_path),
            attrs={"fieldbook.export": "runs-wide"},
            update_existing=True,
        )
        return {"path": str(output_path), "row_count": len(runs), "metric_columns": metric_columns, "artifact": artifact}

    def export_metric_coverage(
        self,
        *,
        experiment_ref: str,
        output_path: Path | None,
        metric_names: list[str] | None,
    ) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_ref)
        total_runs = self.conn.execute(
            "SELECT COUNT(*) FROM experiment_runs er JOIN runs r ON r.id = er.run_id "
            "WHERE er.experiment_id = ? AND r.deleted_at IS NULL",
            (experiment["id"],),
        ).fetchone()[0]
        rows = self._metric_export_rows(experiment["id"], metric_names)
        metric_counts = Counter({(row["metric_name"], row["run_id"]) for row in rows})
        by_metric = Counter()
        for metric_name, _run_id in metric_counts:
            by_metric[metric_name] += 1
        metric_set = sorted(set(metric_names or by_metric.keys()))
        coverage_rows = [
            {
                "experiment_id": experiment["id"],
                "metric_name": metric_name,
                "run_count": by_metric.get(metric_name, 0),
                "total_runs": total_runs,
                "coverage": by_metric.get(metric_name, 0) / total_runs if total_runs else 0.0,
            }
            for metric_name in metric_set
        ]
        artifact = None
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["experiment_id", "metric_name", "run_count", "total_runs", "coverage"],
                )
                writer.writeheader()
                writer.writerows(coverage_rows)
            artifact = self.add_artifact(
                experiment_ref=experiment["id"],
                run_ref=None,
                job_ref=None,
                artifact_type="metric-table",
                uri=str(output_path),
                content_hash=file_sha256(output_path),
                attrs={"fieldbook.export": "coverage"},
                update_existing=True,
            )
        return {"rows": coverage_rows, "artifact": artifact}

    def get_artifact(self, ref: str) -> dict[str, Any]:
        return self._artifact_dict(self._resolve_row("artifacts", ref))

    def archive_artifact(self, ref: str) -> dict[str, Any]:
        artifact = self.get_artifact(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE artifacts SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                (now, now, artifact["id"]),
            )
        return self.get_artifact(artifact["id"])

    def add_metric(
        self,
        *,
        run_ref: str,
        metric_name: str,
        value: float,
        step: str | None,
        split: str | None,
        source_job_ref: str | None,
        source_artifact_ref: str | None,
    ) -> dict[str, Any]:
        run_id = self.get_run(run_ref)["id"]
        self._validate_post_archive_write("run", run_id, errata=False, label="metric")
        source_job_id = self.get_job(source_job_ref)["id"] if source_job_ref else None
        source_artifact_id = self.get_artifact(source_artifact_ref)["id"] if source_artifact_ref else None
        with self.conn:
            metric_id = self._upsert_metric(
                run_id=run_id,
                metric_name=metric_name,
                value=value,
                step=step,
                split=split,
                source_job_id=source_job_id,
                source_artifact_id=source_artifact_id,
            )
        return self.get_metric(metric_id)

    def import_metrics_csv(self, path: Path) -> list[dict[str, Any]]:
        planned: list[dict[str, Any]] = []
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                run_ref = row.get("run_id") or row.get("run")
                metric_name = row.get("metric_name") or row.get("name")
                raw_value = row.get("value")
                if not run_ref or not metric_name or raw_value is None:
                    raise ValidationError("metric CSV requires run_id/run, metric_name/name, and value columns")
                planned.append(
                    {
                        "run_id": self.get_run(run_ref)["id"],
                        "metric_name": metric_name,
                        "value": validate_metric_value(raw_value),
                        "step": row.get("step") or None,
                        "split": row.get("split") or None,
                        "source_job_id": self.get_job(row["source_job_id"])["id"] if row.get("source_job_id") else None,
                        "source_artifact_id": self.get_artifact(row["source_artifact_id"])["id"]
                        if row.get("source_artifact_id")
                        else None,
                    }
                )
        metric_ids: list[str] = []
        with self.conn:
            for row in planned:
                metric_ids.append(
                    self._upsert_metric(
                        run_id=row["run_id"],
                        metric_name=row["metric_name"],
                        value=row["value"],
                        step=row["step"],
                        split=row["split"],
                        source_job_id=row["source_job_id"],
                        source_artifact_id=row["source_artifact_id"],
                    )
                )
        return [self.get_metric(metric_id) for metric_id in metric_ids]

    def list_metrics(
        self,
        *,
        run_ref: str | None = None,
        metric_name: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [1 if include_archived else 0]
        query = "SELECT * FROM metrics WHERE (? OR deleted_at IS NULL)"
        if run_ref:
            query += " AND run_id = ?"
            params.append(self.get_run(run_ref)["id"])
        if metric_name:
            query += " AND metric_name = ?"
            params.append(metric_name)
        query += " ORDER BY run_id, metric_name, step, split"
        return [self._metric_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_metric(self, ref: str) -> dict[str, Any]:
        return self._metric_dict(self._resolve_row("metrics", ref))

    def archive_metric(self, ref: str) -> dict[str, Any]:
        metric = self.get_metric(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute("UPDATE metrics SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?", (now, now, metric["id"]))
        return self.get_metric(metric["id"])

    def add_note(
        self,
        *,
        entity_type: str,
        entity_ref: str,
        note_type: str,
        status: str,
        title: str | None,
        body: str,
        body_format: str,
        author: str | None,
        attrs: dict[str, Any],
        errata: bool = False,
    ) -> dict[str, Any]:
        require_choice(entity_type, ENTITY_TYPES, "entity type")
        require_choice(note_type, NOTE_TYPES, "note type")
        require_choice(status, NOTE_STATUSES, "note status")
        require_choice(body_format, NOTE_BODY_FORMATS, "note body format")
        title = validate_note_title(title)
        body = validate_note_body(body)
        entity_id = self._resolve_entity_id(entity_type, entity_ref)
        self._validate_post_archive_write(entity_type, entity_id, errata=errata, label="note")
        attrs = self._attrs_with_session(attrs)
        now = utc_now()
        if errata:
            attrs = self._errata_attrs(attrs, now=now)
        note_id = new_id("note")
        with self.conn:
            self.conn.execute(
                "INSERT INTO notes (id, entity_type, entity_id, note_type, status, title, body, body_format, "
                "author, created_at, updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    entity_type,
                    entity_id,
                    note_type,
                    status,
                    title,
                    body,
                    body_format,
                    author,
                    now,
                    now,
                    attrs_json(attrs),
                ),
            )
        return self.get_note(note_id)

    def list_notes(
        self,
        *,
        entity_type: str | None = None,
        entity_ref: str | None = None,
        note_type: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [1 if include_archived else 0]
        query = "SELECT * FROM notes WHERE (? OR deleted_at IS NULL)"
        if entity_type:
            require_choice(entity_type, ENTITY_TYPES, "entity type")
            query += " AND entity_type = ?"
            params.append(entity_type)
        if entity_ref:
            if not entity_type:
                raise ValidationError("--entity-id requires --entity-type")
            query += " AND entity_id = ?"
            params.append(self._resolve_entity_id(entity_type, entity_ref))
        if note_type:
            require_choice(note_type, NOTE_TYPES, "note type")
            query += " AND note_type = ?"
            params.append(note_type)
        if status:
            require_choice(status, NOTE_STATUSES, "note status")
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, id"
        return [self._note_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def get_note(self, ref: str) -> dict[str, Any]:
        return self._note_dict(self._resolve_row("notes", ref))

    def resolve_note(self, ref: str) -> dict[str, Any]:
        note = self.get_note(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE notes SET status = 'resolved', resolved_at = ?, updated_at = ? WHERE id = ?",
                (now, now, note["id"]),
            )
        return self.get_note(note["id"])

    def archive_note(self, ref: str) -> dict[str, Any]:
        note = self.get_note(ref)
        now = utc_now()
        with self.conn:
            self.conn.execute("UPDATE notes SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?", (now, now, note["id"]))
        return self.get_note(note["id"])

    def start_session(
        self,
        *,
        experiment_ref: str | None,
        agent: str,
        intent: str | None,
        cwd: str | None,
        git_root: str | None,
        git_worktree_dir: str | None,
        git_branch: str | None,
        git_commit: str | None,
        attrs: dict[str, Any],
        force_archived: bool = False,
    ) -> dict[str, Any]:
        experiment_id = self._session_experiment_id(experiment_ref, force_archived=force_archived)
        now = utc_now()
        session_id = new_id("ses")
        with self.conn:
            self.conn.execute(
                "INSERT INTO sessions (id, ledger_id, experiment_id, agent, cwd, git_root, git_worktree_dir, "
                "git_branch, git_commit, intent, started_at, last_touch_at, attrs_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    self._ledger_id(),
                    experiment_id,
                    agent,
                    cwd,
                    git_root,
                    git_worktree_dir,
                    git_branch,
                    git_commit,
                    intent,
                    now,
                    now,
                    attrs_json(attrs),
                ),
            )
        self.current_session_id = session_id
        return self.get_session(session_id)

    def get_session(self, ref: str) -> dict[str, Any]:
        return self._session_dict(self._resolve_row("sessions", ref))

    def current_session(self) -> dict[str, Any] | None:
        if self.current_session_id is None:
            return None
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (self.current_session_id,)).fetchone()
        return self._session_dict(row) if row else None

    def list_sessions(
        self,
        *,
        experiment_ref: str | None = None,
        agent: str | None = None,
        open_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        query = "SELECT * FROM sessions WHERE 1=1"
        if experiment_ref:
            query += " AND experiment_id = ?"
            params.append(self.get_experiment(experiment_ref)["id"])
        if agent:
            query += " AND agent = ?"
            params.append(agent)
        if open_only:
            query += " AND ended_at IS NULL"
        query += " ORDER BY started_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return [self._session_dict(row) for row in self.conn.execute(query, params).fetchall()]

    def end_session(self, *, session_ref: str | None = None, force: bool = False) -> dict[str, Any]:
        if session_ref is None and self.current_session_id is None:
            return {"closed": False, "reason": "no_current_session", "session": None}
        session_id = session_ref or self.current_session_id
        assert session_id is not None
        session = self.get_session(session_id)
        if session["ended_at"] is not None and not force:
            raise ValidationError(f"session is already closed: {session_id}")
        if session["ended_at"] is not None and force:
            return {"closed": False, "reason": "already_closed", "session": session}
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET ended_at = ?, last_touch_at = ? WHERE id = ?",
                (now, now, session_id),
            )
        if session_id == self.current_session_id:
            self.current_session_id = None
        return {"closed": True, "session": self.get_session(session_id)}

    def switch_session(
        self,
        *,
        to_experiment_ref: str,
        agent: str,
        intent: str | None,
        cwd: str | None,
        git_root: str | None,
        git_worktree_dir: str | None,
        git_branch: str | None,
        git_commit: str | None,
        attrs: dict[str, Any],
        force_archived: bool = False,
    ) -> dict[str, Any]:
        target_experiment_id = self._session_experiment_id(to_experiment_ref, force_archived=force_archived)
        old_session = self.current_session()
        handoff_body = None
        if old_session and old_session["experiment_id"]:
            handoff_body = self._session_handoff_body(old_session)

        now = utc_now()
        new_session_id = new_id("ses")
        handoff_note_id = None
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if old_session:
                self.conn.execute(
                    "UPDATE sessions SET ended_at = ?, last_touch_at = ? WHERE id = ?",
                    (now, now, old_session["id"]),
                )
                if old_session["experiment_id"] and handoff_body is not None:
                    handoff_note_id = new_id("note")
                    self.conn.execute(
                        "INSERT INTO notes (id, entity_type, entity_id, note_type, status, title, body, "
                        "body_format, created_at, updated_at, attrs_json) VALUES (?, 'experiment', ?, "
                        "'handoff', 'open', ?, ?, 'markdown', ?, ?, ?)",
                        (
                            handoff_note_id,
                            old_session["experiment_id"],
                            f"Session handoff from {old_session['agent']}",
                            handoff_body,
                            now,
                            now,
                            attrs_json({"session_id": old_session["id"]}),
                        ),
                    )
            self.conn.execute(
                "INSERT INTO sessions (id, ledger_id, experiment_id, agent, cwd, git_root, git_worktree_dir, "
                "git_branch, git_commit, intent, started_at, last_touch_at, attrs_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_session_id,
                    self._ledger_id(),
                    target_experiment_id,
                    agent,
                    cwd,
                    git_root,
                    git_worktree_dir,
                    git_branch,
                    git_commit,
                    intent,
                    now,
                    now,
                    attrs_json(attrs),
                ),
            )
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

        self.current_session_id = new_session_id
        return {
            "closed_session": self.get_session(old_session["id"]) if old_session else None,
            "handoff_note": self.get_note(handoff_note_id) if handoff_note_id else None,
            "session": self.get_session(new_session_id),
            "context": self.experiment_context(target_experiment_id),
        }

    def _active_experiment_id(self, ref: str) -> str:
        experiment = self.get_experiment(ref)
        if experiment["deleted_at"] is not None:
            raise ValidationError(f"experiment is archived/deleted and cannot be mutated: {experiment['id']}")
        return experiment["id"]

    def _experiment_id_for_artifact_target(self, ref: str, *, errata: bool) -> str:
        experiment = self.get_experiment(ref)
        if experiment["deleted_at"] is not None and not errata:
            raise ValidationError(f"experiment is archived/deleted and requires --errata: {experiment['id']}")
        return experiment["id"]

    def _active_entity_id(self, entity_type: str, ref: str) -> str:
        require_choice(entity_type, ENTITY_TYPES, "entity type")
        row = self._resolve_row(
            {
                "experiment": "experiments",
                "run": "runs",
                "job": "jobs",
                "artifact": "artifacts",
                "metric": "metrics",
            }[entity_type],
            ref,
            name_column="name" if entity_type in {"experiment", "run", "job"} else None,
        )
        if "deleted_at" in row.keys() and row["deleted_at"] is not None:
            raise ValidationError(f"{entity_type} is archived/deleted and cannot be validated: {ref}")
        return str(row["id"])

    def _validate_post_archive_write(self, entity_type: str, entity_id: str, *, errata: bool, label: str) -> None:
        archived_experiment_ids = self._archived_experiment_ids_for_entity(entity_type, entity_id)
        if archived_experiment_ids and not errata:
            joined = ", ".join(sorted(archived_experiment_ids))
            raise ValidationError(f"{label} targets archived experiment(s) and requires --errata: {joined}")

    def _validate_artifact_targets_post_archive(
        self,
        *,
        experiment_id: str | None,
        run_id: str | None,
        job_id: str | None,
        errata: bool,
    ) -> None:
        archived_ids: set[str] = set()
        if experiment_id:
            archived_ids.update(self._archived_experiment_ids_for_entity("experiment", experiment_id))
        if run_id:
            archived_ids.update(self._archived_experiment_ids_for_entity("run", run_id))
        if job_id:
            archived_ids.update(self._archived_experiment_ids_for_entity("job", job_id))
        if archived_ids and not errata:
            joined = ", ".join(sorted(archived_ids))
            raise ValidationError(f"artifact targets archived experiment(s) and requires --errata: {joined}")

    def _archived_experiment_ids_for_entity(self, entity_type: str, entity_id: str) -> set[str]:
        owner_ids = self._owner_experiment_ids_for_entity(entity_type, entity_id)
        if not owner_ids:
            return set()
        placeholders = ", ".join("?" for _ in owner_ids)
        rows = self.conn.execute(
            f"SELECT id FROM experiments WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL",
            tuple(owner_ids),
        ).fetchall()
        return {str(row["id"]) for row in rows}

    def _owner_experiment_ids_for_entity(self, entity_type: str, entity_id: str) -> set[str]:
        require_choice(entity_type, ENTITY_TYPES, "entity type")
        if entity_type == "experiment":
            return {entity_id}
        if entity_type == "run":
            return {
                str(row["experiment_id"])
                for row in self.conn.execute(
                    "SELECT experiment_id FROM experiment_runs WHERE run_id = ?",
                    (entity_id,),
                ).fetchall()
            }
        if entity_type == "job":
            row = self.conn.execute("SELECT experiment_id, run_id FROM jobs WHERE id = ?", (entity_id,)).fetchone()
            if row is None:
                return set()
            result = {str(row["experiment_id"])} if row["experiment_id"] else set()
            if row["run_id"]:
                result.update(self._owner_experiment_ids_for_entity("run", str(row["run_id"])))
            return result
        if entity_type == "artifact":
            row = self.conn.execute("SELECT * FROM artifacts WHERE id = ?", (entity_id,)).fetchone()
            return self._artifact_row_experiment_ids(row) if row else set()
        if entity_type == "metric":
            row = self.conn.execute("SELECT run_id FROM metrics WHERE id = ?", (entity_id,)).fetchone()
            return self._owner_experiment_ids_for_entity("run", str(row["run_id"])) if row else set()
        return set()

    def _artifact_target_experiment_ids(
        self,
        *,
        experiment_id: str | None,
        run_id: str | None,
        job_id: str | None,
    ) -> set[str]:
        result = {experiment_id} if experiment_id else set()
        if run_id:
            result.update(self._owner_experiment_ids_for_entity("run", run_id))
        if job_id:
            result.update(self._owner_experiment_ids_for_entity("job", job_id))
        return result

    def _artifact_row_experiment_ids(self, row: sqlite3.Row) -> set[str]:
        result = {str(row["experiment_id"])} if row["experiment_id"] else set()
        if row["run_id"]:
            result.update(self._owner_experiment_ids_for_entity("run", str(row["run_id"])))
        if row["job_id"]:
            result.update(self._owner_experiment_ids_for_entity("job", str(row["job_id"])))
        return result

    def _errata_attrs(self, attrs: dict[str, Any], *, now: str, replaces: str | None = None) -> dict[str, Any]:
        result = {
            **attrs,
            "fieldbook.erratum": True,
            "fieldbook.erratum_at": now,
        }
        if self.current_session_id:
            result["fieldbook.erratum_session_id"] = self.current_session_id
        if replaces:
            result["fieldbook.replaces"] = replaces
        return result

    def _retry_of_id(self, *, job_id: str, retry_of_ref: str | None) -> str | None:
        if retry_of_ref is None:
            return None
        try:
            retry_target = self.get_job(retry_of_ref)
        except NotFoundError as exc:
            raise ValidationError(f"retry_of does not reference an existing job: {retry_of_ref}") from exc
        retry_of_id = retry_target["id"]
        if retry_target["deleted_at"] is not None:
            raise ValidationError(f"retry_of references an archived/deleted job: {retry_of_id}")
        if retry_of_id == job_id:
            raise ValidationError("retry_of cannot reference the job itself")
        if self._retry_chain_contains(start_job_id=retry_of_id, needle_job_id=job_id):
            raise ValidationError("retry_of would create a retry cycle")
        return retry_of_id

    def _retry_chain_contains(self, *, start_job_id: str, needle_job_id: str) -> bool:
        current = start_job_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            row = self.conn.execute(
                "SELECT retry_of FROM jobs WHERE id = ? AND deleted_at IS NULL",
                (current,),
            ).fetchone()
            if row is None or row["retry_of"] is None:
                return False
            current = str(row["retry_of"])
            if current == needle_job_id:
                return True
        return False

    def _session_experiment_id(self, ref: str | None, *, force_archived: bool) -> str | None:
        if ref is None:
            return None
        experiment = self.get_experiment(ref)
        if experiment["deleted_at"] is not None and not force_archived:
            raise ValidationError(f"experiment is archived/deleted; pass --force-archived to start a session: {experiment['id']}")
        return experiment["id"]

    def _session_handoff_body(self, session: dict[str, Any]) -> str:
        assert session["experiment_id"] is not None
        context = self.experiment_context(session["experiment_id"])
        lines = [
            "# Fieldbook Session Handoff",
            "",
            f"- Closing session: `{session['id']}`",
            f"- Agent: `{session['agent']}`",
            f"- Experiment: `{context['experiment']['name']}` (`{context['experiment']['id']}`)",
            "",
            "## Open Handoffs",
            "",
            *_handoff_note_lines(context["notes"]["open_handoffs"]),
            "",
            "## Open Next Actions",
            "",
            *_handoff_note_lines(context["notes"]["open_next_actions"]),
            "",
            "## Open Debug Notes",
            "",
            *_handoff_note_lines(context["notes"]["open_debug"]),
            "",
            "## Stale Jobs",
            "",
            *_handoff_job_lines(context["stale_jobs"]),
            "",
            "## Failed Jobs",
            "",
            *_handoff_job_lines(context["failed_jobs"]),
            "",
            "## Key Artifacts",
            "",
            *_handoff_artifact_lines(context["key_artifacts"]),
        ]
        return "\n".join(lines).rstrip() + "\n"

    def _checkpoint_body(self, *, body: str | None, freshness: dict[str, Any]) -> str:
        lines: list[str] = []
        if body:
            lines.extend([body.rstrip(), ""])
        else:
            lines.extend(["# Experiment Checkpoint", ""])
        lines.extend(
            [
                "## Freshness",
                "",
                f"- Checkpoint status: `{freshness['checkpoint_status']}`",
                f"- Drifted artifacts: {freshness['drifted_artifact_count']}",
                f"- Stale validations: {freshness['stale_validation_count']}",
            ]
        )
        if freshness.get("drifted_artifacts"):
            lines.extend(["", "### Drifted Artifacts"])
            for artifact in freshness["drifted_artifacts"][:5]:
                lines.append(f"- `{artifact['id']}` {artifact['uri']} ({artifact['drift_kind']})")
        if freshness.get("stale_validations"):
            lines.extend(["", "### Stale Validations"])
            for validation in freshness["stale_validations"][:5]:
                lines.append(f"- `{validation['id']}` {validation['check_name']}")
        return "\n".join(lines).rstrip() + "\n"

    def _parent_run_id(self, ref: str | None) -> str | None:
        if ref is None:
            return None
        row = self.conn.execute("SELECT id FROM runs WHERE id = ?", (ref,)).fetchone()
        if row is None:
            rows = self.conn.execute(
                "SELECT id FROM runs WHERE name = ? AND deleted_at IS NULL ORDER BY id",
                (ref,),
            ).fetchall()
            if len(rows) == 1:
                return rows[0]["id"]
            if len(rows) > 1:
                raise ValidationError(f"parent_run_id reference {ref!r} matches multiple runs")
            raise ValidationError(f"parent_run_id does not reference an existing run: {ref}")
        return row["id"]

    def _experiment_artifact_rows(self, experiment_id: str, *, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT DISTINCT a.* FROM artifacts a "
            "LEFT JOIN experiment_runs er ON er.run_id = a.run_id AND er.experiment_id = ? "
            "LEFT JOIN jobs j ON j.id = a.job_id "
            "LEFT JOIN experiment_runs jer ON jer.run_id = j.run_id AND jer.experiment_id = ? "
            "WHERE a.deleted_at IS NULL AND (a.experiment_id = ? OR er.experiment_id IS NOT NULL "
            "OR j.experiment_id = ? OR jer.experiment_id IS NOT NULL) "
            "ORDER BY a.updated_at DESC LIMIT ?",
            (experiment_id, experiment_id, experiment_id, experiment_id, limit),
        ).fetchall()

    def _experiment_note_counts(self, experiment_id: str) -> dict[str, dict[str, int]]:
        counts = {note_type: {status: 0 for status in sorted(NOTE_STATUSES)} for note_type in sorted(NOTE_TYPES)}
        rows = self.conn.execute(
            "SELECT note_type, status, COUNT(*) AS count FROM notes "
            "WHERE entity_type = 'experiment' AND entity_id = ? AND deleted_at IS NULL "
            "GROUP BY note_type, status",
            (experiment_id,),
        ).fetchall()
        for row in rows:
            counts[row["note_type"]][row["status"]] = int(row["count"])
        return counts

    def _experiment_errata_count(self, experiment_id: str) -> int:
        return len(self._experiment_errata_rows(experiment_id, limit=1_000_000))

    def _experiment_errata_rows(self, experiment_id: str, *, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.conn.execute("SELECT * FROM notes WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall():
            attrs = load_attrs(row["attrs_json"])
            if attrs.get("fieldbook.erratum") is True and experiment_id in self._owner_experiment_ids_for_entity(row["entity_type"], row["entity_id"]):
                rows.append({"entity_type": "note", "entity_id": row["id"], "created_at": row["created_at"], "attrs": attrs})
        for row in self.conn.execute("SELECT * FROM artifacts WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall():
            attrs = load_attrs(row["attrs_json"])
            if attrs.get("fieldbook.erratum") is True and experiment_id in self._artifact_row_experiment_ids(row):
                rows.append({"entity_type": "artifact", "entity_id": row["id"], "created_at": row["created_at"], "attrs": attrs})
        for row in self.conn.execute("SELECT * FROM validations WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall():
            attrs = load_attrs(row["attrs_json"])
            if attrs.get("fieldbook.erratum") is True and experiment_id in self._owner_experiment_ids_for_entity(row["entity_type"], row["entity_id"]):
                rows.append({"entity_type": "validation", "entity_id": row["id"], "created_at": row["created_at"], "attrs": attrs})
        rows.sort(key=lambda item: (item["created_at"], item["entity_id"]), reverse=True)
        return rows[:limit]

    def _experiment_compact_notes(self, experiment_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "open_handoffs": [
                self._compact_note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="handoff",
                    status="open",
                    limit=STATUS_NOTE_LIMIT,
                )
            ],
            "open_next_actions": [
                self._compact_note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="next-action",
                    status="open",
                    limit=STATUS_NOTE_LIMIT,
                )
            ],
            "open_debug": [
                self._compact_note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="debug",
                    status="open",
                    limit=STATUS_NOTE_LIMIT,
                )
            ],
            "recent_research": [
                self._compact_note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="research",
                    status=None,
                    limit=STATUS_RECENT_NOTE_LIMIT,
                )
            ],
            "recent_decisions": [
                self._compact_note_dict(row)
                for row in self._note_rows(
                    experiment_id,
                    note_type="decision",
                    status=None,
                    limit=STATUS_RECENT_NOTE_LIMIT,
                )
            ],
        }

    def _note_rows(
        self,
        experiment_id: str,
        *,
        note_type: str,
        status: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        params: list[Any] = [experiment_id, note_type]
        query = (
            "SELECT * FROM notes WHERE entity_type = 'experiment' AND entity_id = ? "
            "AND note_type = ? AND deleted_at IS NULL"
        )
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, id LIMIT ?"
        params.append(limit)
        return self.conn.execute(query, params).fetchall()

    def _experiment_run_progress(self, experiment_id: str, *, experiment_attrs: dict[str, Any]) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM v_runs_progress_v1 WHERE experiment_id = ? ORDER BY name, run_id",
            (experiment_id,),
        ).fetchall()
        by_kind = Counter(row["kind"] for row in rows)
        by_phase = Counter(row["phase"] for row in rows)
        metric_rows = self.conn.execute(
            "SELECT m.metric_name, COUNT(DISTINCT m.run_id) AS run_count "
            "FROM metrics m "
            "JOIN runs r ON r.id = m.run_id "
            "WHERE r.experiment_id = ? AND m.deleted_at IS NULL AND r.deleted_at IS NULL "
            "GROUP BY m.metric_name ORDER BY m.metric_name",
            (experiment_id,),
        ).fetchall()
        expected = experiment_attrs.get("progress.expected_runs")
        expected_count = int(expected) if isinstance(expected, int | float) else None
        missing_expected_count = max(expected_count - len(rows), 0) if expected_count is not None else None
        return {
            "total": len(rows),
            "expected": expected_count,
            "missing_expected_count": missing_expected_count,
            "by_kind": dict(sorted(by_kind.items())),
            "by_phase": dict(sorted(by_phase.items())),
            "coverage": {
                "has_checkpoint": sum(int(row["has_checkpoint"]) for row in rows),
                "has_eval_result": sum(int(row["has_eval_result"]) for row in rows),
                "by_metric": {row["metric_name"]: int(row["run_count"]) for row in metric_rows},
            },
            "failed_examples": [
                self.get_run(row["run_id"])
                for row in rows
                if row["phase"] == "failed"
            ][:10],
            "missing_examples": [],
        }

    def _experiment_cleanup_plan(self, experiment_id: str) -> dict[str, list[dict[str, Any]]]:
        debug_notes = [
            self._note_dict(row)
            for row in self.conn.execute(
                "SELECT n.* FROM notes n "
                "JOIN v_jobs_with_recovery_v1 r ON r.job_id = n.entity_id "
                "WHERE r.experiment_id = ? AND r.is_recovered_failed = 1 "
                "AND n.entity_type = 'job' AND n.note_type = 'debug' AND n.status = 'open' "
                "AND n.deleted_at IS NULL "
                "ORDER BY n.updated_at DESC, n.id LIMIT 20",
                (experiment_id,),
            ).fetchall()
        ]
        return {
            "debug_notes": debug_notes,
            "validations": self._superseded_validation_rows(experiment_id),
        }

    def _superseded_validation_rows(self, experiment_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM validations WHERE entity_type = 'experiment' AND entity_id = ? "
            "AND deleted_at IS NULL ORDER BY check_name, updated_at DESC, id DESC",
            (experiment_id,),
        ).fetchall()
        latest_pass_by_key: dict[str, sqlite3.Row] = {}
        for row in rows:
            if row["status"] == "pass" and row["check_name"] not in latest_pass_by_key:
                latest_pass_by_key[str(row["check_name"])] = row
        superseded = [
            self._validation_dict(row)
            for row in rows
            if row["status"] in {"fail", "warning", "unknown"}
            and row["check_name"] in latest_pass_by_key
            and latest_pass_by_key[row["check_name"]]["updated_at"] >= row["updated_at"]
        ]
        return superseded[:20]

    def _cleanup_checkpoint_body(self, *, planned: dict[str, list[dict[str, Any]]], counts: dict[str, int]) -> str:
        lines = [
            "# Experiment Cleanup",
            "",
            "## Summary",
            "",
            f"- Debug notes resolved: {counts['debug_notes_resolved']}",
            f"- Validations archived: {counts['validations_archived']}",
        ]
        if planned["debug_notes"]:
            lines.extend(["", "## Resolved Debug Notes", ""])
            for note in planned["debug_notes"]:
                lines.append(f"- `{note['id']}` {note.get('title') or note.get('body_preview') or ''}".rstrip())
        if planned["validations"]:
            lines.extend(["", "## Archived Superseded Validations", ""])
            for validation in planned["validations"]:
                lines.append(f"- `{validation['id']}` {validation['check_name']} status=`{validation['status']}`")
        return "\n".join(lines).rstrip() + "\n"

    def _upsert_metric(
        self,
        *,
        run_id: str,
        metric_name: str,
        value: float,
        step: str | None,
        split: str | None,
        source_job_id: str | None,
        source_artifact_id: str | None,
    ) -> str:
        now = utc_now()
        existing = self.conn.execute(
            "SELECT id FROM metrics WHERE run_id = ? AND metric_name = ? AND COALESCE(step, '') = COALESCE(?, '') "
            "AND COALESCE(split, '') = COALESCE(?, '') AND COALESCE(source_job_id, '') = COALESCE(?, '') "
            "AND COALESCE(source_artifact_id, '') = COALESCE(?, '') AND deleted_at IS NULL",
            (run_id, metric_name, step, split, source_job_id, source_artifact_id),
        ).fetchone()
        if existing:
            metric_id = existing["id"]
            self.conn.execute(
                "UPDATE metrics SET value = ?, updated_at = ? WHERE id = ?",
                (value, now, metric_id),
            )
            return metric_id
        metric_id = new_id("met")
        self.conn.execute(
            "INSERT INTO metrics (id, run_id, metric_name, value, step, split, source_job_id, "
            "source_artifact_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (metric_id, run_id, metric_name, value, step, split, source_job_id, source_artifact_id, now, now),
        )
        return metric_id

    def _metric_provenance(self, row: dict[str, Any]) -> dict[str, Any]:
        job = None
        artifact = None
        if row.get("source_job_id"):
            job = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (row["source_job_id"],)).fetchone()
        if row.get("source_artifact_id"):
            artifact = self.conn.execute("SELECT * FROM artifacts WHERE id = ?", (row["source_artifact_id"],)).fetchone()
        return {
            "source_job_id": row.get("source_job_id"),
            "source_job_code_commit": job["code_commit"] if job else None,
            "source_artifact_id": row.get("source_artifact_id"),
            "source_artifact_uri": artifact["uri"] if artifact else None,
        }

    def _replace_experiment_tags(self, experiment_id: str, tags: list[str]) -> None:
        self.conn.execute("DELETE FROM experiment_tags WHERE experiment_id = ?", (experiment_id,))
        self.conn.executemany(
            "INSERT INTO experiment_tags (experiment_id, tag) VALUES (?, ?)",
            [(experiment_id, tag) for tag in tags],
        )

    def _upsert_job_run(
        self,
        *,
        job_id: str,
        run_id: str,
        role: str,
        status: str,
        failure_reason: str | None,
        started_at: str | None,
        finished_at: str | None,
        attrs: dict[str, Any],
    ) -> None:
        require_choice(role, JOB_RUN_ROLES, "job-run role")
        require_choice(status, JOB_RUN_STATUSES, "job-run status")
        existing = self.conn.execute(
            "SELECT * FROM job_runs WHERE job_id = ? AND run_id = ?",
            (job_id, run_id),
        ).fetchone()
        now = utc_now()
        if existing is not None:
            if existing["role"] != role:
                raise ValidationError("job/run link role is immutable; archive and create a new edge instead")
            self.conn.execute(
                "UPDATE job_runs SET status = ?, started_at = COALESCE(?, started_at), "
                "finished_at = COALESCE(?, finished_at), failure_reason = COALESCE(?, failure_reason), "
                "attrs_json = ?, deleted_at = NULL, updated_at = ? WHERE job_id = ? AND run_id = ?",
                (
                    status,
                    started_at,
                    finished_at,
                    failure_reason,
                    attrs_json(attrs),
                    now,
                    job_id,
                    run_id,
                ),
            )
            return
        self.conn.execute(
            "INSERT INTO job_runs (job_id, run_id, role, status, started_at, finished_at, failure_reason, "
            "created_at, updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                run_id,
                role,
                status,
                started_at,
                finished_at,
                failure_reason,
                now,
                now,
                attrs_json(attrs),
            ),
        )

    def _link_run_ids(self, experiment_id: str, run_id: str) -> None:
        now = utc_now()
        self.conn.execute(
            "INSERT OR IGNORE INTO experiment_runs (experiment_id, run_id, created_at) VALUES (?, ?, ?)",
            (experiment_id, run_id, now),
        )
        self.conn.execute(
            "UPDATE runs SET experiment_id = COALESCE(experiment_id, ?), updated_at = ? WHERE id = ?",
            (experiment_id, now, run_id),
        )

    def _existing_external(
        self,
        table: str,
        external_system: str | None,
        external_id: str | None,
    ) -> sqlite3.Row | None:
        if not external_system and not external_id:
            return None
        if not external_system or not external_id:
            raise ValidationError("external identifiers require both --external-system and --external-id")
        rows = self.conn.execute(
            f"SELECT * FROM {table} WHERE external_system = ? AND external_id = ? AND deleted_at IS NULL",
            (external_system, external_id),
        ).fetchall()
        if len(rows) > 1:
            raise AmbiguityError(f"multiple {table} rows match external identifier {external_system}:{external_id}")
        return rows[0] if rows else None

    def _run_experiment_ids(self, run_id: str) -> list[str]:
        return [
            row["experiment_id"]
            for row in self.conn.execute(
                "SELECT experiment_id FROM experiment_runs WHERE run_id = ? ORDER BY experiment_id",
                (run_id,),
            ).fetchall()
        ]

    def _resolve_entity_id(self, entity_type: str, ref: str) -> str:
        table = {
            "experiment": "experiments",
            "run": "runs",
            "job": "jobs",
            "artifact": "artifacts",
            "metric": "metrics",
            "note": "notes",
        }[entity_type]
        name_column = "name" if entity_type in {"experiment", "run", "job"} else None
        return self._resolve_row(table, ref, name_column=name_column)["id"]

    def _validation_summary(self, rows: list[sqlite3.Row]) -> dict[str, Any]:
        validations = [self._validation_dict(row) for row in rows]
        failed = [row for row in validations if row["status"] == "fail"]
        unknown_blocking = [
            row for row in validations if row["status"] == "unknown" and row["attrs"].get("validation.blocking") is True
        ]
        warnings = [row for row in validations if row["status"] == "warning"]
        if failed:
            status = "fail"
        elif unknown_blocking:
            status = "unknown"
        elif warnings:
            status = "warning"
        elif validations:
            status = "pass"
        else:
            status = "none"
        return {
            "status": status,
            "total": len(validations),
            "failed": failed,
            "unknown_blocking": unknown_blocking,
            "warnings": warnings,
            "rows": validations[:20],
        }

    def _resolve_row(self, table: str, ref: str, *, name_column: str | None = None) -> sqlite3.Row:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (ref,)).fetchone()
        if row:
            return row
        if name_column:
            rows = self.conn.execute(
                f"SELECT * FROM {table} WHERE {name_column} = ? AND deleted_at IS NULL ORDER BY id",
                (ref,),
            ).fetchall()
            if len(rows) == 1:
                return rows[0]
            if len(rows) > 1:
                raise AmbiguityError(f"{table} reference {ref!r} matches multiple rows")
        raise NotFoundError(f"{table} row not found: {ref}")

    def _experiment_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        data["tags"] = [
            tag_row["tag"]
            for tag_row in self.conn.execute(
                "SELECT tag FROM experiment_tags WHERE experiment_id = ? ORDER BY tag",
                (data["id"],),
            ).fetchall()
        ]
        return data

    def _run_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        data["experiment_ids"] = self._run_experiment_ids(data["id"])
        return data

    def _job_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        if "id" not in data and "job_id" in data:
            data["id"] = data["job_id"]
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        if "code_dirty" in data:
            data["code_dirty"] = bool(data["code_dirty"])
        return data

    def _job_run_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        return data

    def _artifact_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        return data

    def _metric_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def _note_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        return data

    def _validation_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["details"] = load_attrs(data.pop("details_json", "{}"))
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        return data

    def _session_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        return data

    def _compact_note_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        full = self._note_dict(row)
        return {
            "id": full["id"],
            "entity_type": full["entity_type"],
            "entity_id": full["entity_id"],
            "note_type": full["note_type"],
            "status": full["status"],
            "title": full["title"],
            "body_format": full["body_format"],
            "body_preview": note_body_preview(full["body"]),
            "updated_at": full["updated_at"],
        }

    def _ledger_id(self) -> str:
        row = self.conn.execute("SELECT value FROM schema_metadata WHERE key = 'ledger_id'").fetchone()
        if row is None:
            raise ValidationError("ledger is missing ledger_id metadata; run migrations with a write-capable command")
        return str(row["value"])

    def _valid_open_session_id(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        row = self.conn.execute(
            "SELECT id FROM sessions WHERE id = ? AND ended_at IS NULL",
            (session_id,),
        ).fetchone()
        return str(row["id"]) if row else None

    def _attrs_with_session(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.current_session_id is None:
            return attrs
        return {"session_id": self.current_session_id, **attrs}

    def _metric_export_rows(self, experiment_id: str, metric_names: list[str] | None) -> list[dict[str, Any]]:
        params: list[Any] = [experiment_id]
        query = (
            "SELECT er.experiment_id, r.id AS run_id, r.name AS run_name, m.id AS metric_id, m.metric_name, "
            "m.value, m.step, m.split, m.source_job_id, m.source_artifact_id, m.updated_at "
            "FROM experiment_runs er "
            "JOIN runs r ON r.id = er.run_id "
            "JOIN metrics m ON m.run_id = r.id "
            "WHERE er.experiment_id = ? AND r.deleted_at IS NULL AND m.deleted_at IS NULL"
        )
        if metric_names:
            placeholders = ", ".join("?" for _ in metric_names)
            query += f" AND m.metric_name IN ({placeholders})"
            params.extend(metric_names)
        query += " ORDER BY r.id, m.metric_name, m.step, m.split"
        return [dict(row) for row in self.conn.execute(query, params).fetchall()]

    def _wide_metric_columns(self, rows: list[dict[str, Any]], metric_names: list[str] | None) -> list[str]:
        if metric_names:
            return metric_names
        return sorted({self._wide_metric_column(row) for row in rows})

    def _wide_metric_column(self, row: dict[str, Any]) -> str:
        pieces = [row["metric_name"]]
        if row.get("step"):
            pieces.append(f"step={row['step']}")
        if row.get("split"):
            pieces.append(f"split={row['split']}")
        return "|".join(pieces)


def note_body_preview(body: str) -> str:
    for line in body.strip().splitlines():
        normalized = line.strip()
        if normalized:
            if len(normalized) > NOTE_PREVIEW_CHARS:
                return normalized[: NOTE_PREVIEW_CHARS - 1] + "…"
            return normalized
    return ""


def _handoff_note_lines(notes: list[dict[str, Any]]) -> list[str]:
    if not notes:
        return ["- none"]
    lines = []
    for note in notes:
        label = note.get("title") or note["note_type"]
        preview = note.get("body_preview") or ""
        suffix = f" — {preview}" if preview else ""
        lines.append(f"- `{note['id']}` {label}{suffix}")
    return lines


def _handoff_job_lines(jobs: list[dict[str, Any]]) -> list[str]:
    if not jobs:
        return ["- none"]
    return [
        f"- `{job['id']}` {job.get('name') or '(unnamed)'} status=`{job['status']}` updated_at=`{job['updated_at']}`"
        for job in jobs
    ]


def _handoff_artifact_lines(artifacts: list[dict[str, Any]]) -> list[str]:
    if not artifacts:
        return ["- none"]
    return [
        f"- `{artifact['id']}` {artifact['type']}: {artifact['uri']}"
        for artifact in artifacts
    ]
