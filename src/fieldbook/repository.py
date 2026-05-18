import csv
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fieldbook.errors import AmbiguityError, NotFoundError, ValidationError
from fieldbook.git_info import current_git_revision
from fieldbook.ids import new_id
from fieldbook.time_utils import utc_now
from fieldbook.validation import (
    ARTIFACT_TYPES,
    ENTITY_TYPES,
    EXPERIMENT_STATUSES,
    JOB_STATUSES,
    NOTE_STATUSES,
    NOTE_TYPES,
    RUN_STATUSES,
    attrs_json,
    file_sha256,
    load_attrs,
    normalize_tag,
    require_choice,
    validate_content_hash,
    validate_metric_value,
    validate_utc_z,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def create_experiment(
        self,
        *,
        name: str,
        description: str | None,
        tags: list[str],
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        experiment_id = new_id("exp")
        normalized_tags = sorted({normalize_tag(tag) for tag in tags})
        with self.conn:
            self.conn.execute(
                "INSERT INTO experiments (id, name, description, created_at, updated_at, attrs_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (experiment_id, name, description, now, now, attrs_json(attrs)),
            )
            self._replace_experiment_tags(experiment_id, normalized_tags)
        return self.get_experiment(experiment_id)

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
        open_notes = self.conn.execute(
            "SELECT COUNT(*) FROM notes WHERE entity_type = 'experiment' AND entity_id = ? "
            "AND status = 'open' AND deleted_at IS NULL",
            (experiment_id,),
        ).fetchone()[0]
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
        artifact_rows = self.conn.execute(
            "SELECT * FROM artifacts WHERE experiment_id = ? AND deleted_at IS NULL "
            "ORDER BY updated_at DESC LIMIT 20",
            (experiment_id,),
        ).fetchall()
        next_actions = self.conn.execute(
            "SELECT * FROM notes WHERE entity_type = 'experiment' AND entity_id = ? "
            "AND note_type = 'next-action' AND status = 'open' AND deleted_at IS NULL "
            "ORDER BY updated_at DESC LIMIT 10",
            (experiment_id,),
        ).fetchall()
        recent_notes = self.conn.execute(
            "SELECT * FROM notes WHERE entity_type = 'experiment' AND entity_id = ? "
            "AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10",
            (experiment_id,),
        ).fetchall()
        return {
            "experiment": experiment,
            "run_count": run_count,
            "job_counts": job_counts,
            "open_note_count": open_notes,
            "stale_threshold_hours": stale_hours,
            "stale_jobs": [self._job_dict(row) for row in stale_rows],
            "failed_jobs": [self._job_dict(row) for row in failed_rows],
            "key_artifacts": [self._artifact_dict(row) for row in artifact_rows],
            "next_actions": [self._note_dict(row) for row in next_actions],
            "recent_notes": [self._note_dict(row) for row in recent_notes],
        }

    def add_run(
        self,
        *,
        name: str,
        description: str | None,
        experiment_ref: str | None,
        status: str,
        external_system: str | None,
        external_id: str | None,
        attrs: dict[str, Any],
        update_existing: bool,
    ) -> dict[str, Any]:
        require_choice(status, RUN_STATUSES, "run status")
        existing = self._existing_external("runs", external_system, external_id)
        now = utc_now()
        if existing and not update_existing:
            raise AmbiguityError(
                f"run external identifier {external_system}:{external_id} already exists as {existing['id']}"
            )
        experiment_id = self.get_experiment(experiment_ref)["id"] if experiment_ref else None
        with self.conn:
            if existing:
                run_id = existing["id"]
                self.conn.execute(
                    "UPDATE runs SET name = ?, description = ?, status = ?, updated_at = ?, attrs_json = ? "
                    "WHERE id = ?",
                    (name, description, status, now, attrs_json(attrs), run_id),
                )
            else:
                run_id = new_id("run")
                self.conn.execute(
                    "INSERT INTO runs (id, name, description, status, external_system, external_id, created_at, "
                    "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, name, description, status, external_system, external_id, now, now, attrs_json(attrs)),
                )
            if experiment_id:
                self._link_run_ids(experiment_id, run_id)
        return self.get_run(run_id)

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
        experiment_id = self.get_experiment(experiment_ref)["id"]
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
        experiment_id = self.get_experiment(experiment_ref)["id"] if experiment_ref else None
        if run_id and not experiment_id:
            experiment_ids = self._run_experiment_ids(run_id)
            if len(experiment_ids) == 1:
                experiment_id = experiment_ids[0]
        code_commit, code_dirty = current_git_revision()
        now = utc_now()
        with self.conn:
            if existing:
                job_id = existing["id"]
                self.conn.execute(
                    "UPDATE jobs SET experiment_id = ?, run_id = ?, name = ?, status = ?, command = ?, launcher = ?, "
                    "failure_reason = ?, code_commit = ?, code_dirty = ?, started_at = ?, finished_at = ?, "
                    "updated_at = ?, attrs_json = ? WHERE id = ?",
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
                        now,
                        attrs_json(attrs),
                        job_id,
                    ),
                )
            else:
                job_id = new_id("job")
                self.conn.execute(
                    "INSERT INTO jobs (id, experiment_id, run_id, name, status, command, launcher, external_system, "
                    "external_id, failure_reason, code_commit, code_dirty, created_at, updated_at, started_at, "
                    "finished_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        return self.get_job(job_id)

    def update_job_status(
        self,
        *,
        job_ref: str,
        status: str,
        failure_reason: str | None,
        started_at: str | None,
        finished_at: str | None,
    ) -> dict[str, Any]:
        require_choice(status, JOB_STATUSES, "job status")
        validate_utc_z(started_at, "started_at")
        validate_utc_z(finished_at, "finished_at")
        job = self.get_job(job_ref)
        now = utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE jobs SET status = ?, failure_reason = COALESCE(?, failure_reason), "
                "started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at), updated_at = ? "
                "WHERE id = ?",
                (status, failure_reason, started_at, finished_at, now, job["id"]),
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
    ) -> dict[str, Any]:
        require_choice(artifact_type, ARTIFACT_TYPES, "artifact type")
        validate_content_hash(content_hash)
        experiment_id = self.get_experiment(experiment_ref)["id"] if experiment_ref else None
        run_id = self.get_run(run_ref)["id"] if run_ref else None
        job_id = self.get_job(job_ref)["id"] if job_ref else None
        if not experiment_id and not run_id and not job_id:
            raise ValidationError("artifact requires --experiment, --run, or --job")
        now = utc_now()
        artifact_id = new_id("art")
        with self.conn:
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

    def list_artifacts(
        self,
        *,
        experiment_ref: str | None = None,
        run_ref: str | None = None,
        job_ref: str | None = None,
        artifact_type: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
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
        values: dict[tuple[str, str], float] = {}
        for row in export_rows:
            column = row["metric_name"] if metric_names else self._wide_metric_column(row)
            values[(row["run_id"], column)] = row["value"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["experiment_id", "run_id", "run_name", "status", "external_system", "external_id", *metric_columns]
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
                writer.writerow(row)
        artifact = self.add_artifact(
            experiment_ref=experiment["id"],
            run_ref=None,
            job_ref=None,
            artifact_type="metric-table",
            uri=str(output_path),
            content_hash=file_sha256(output_path),
            attrs={"fieldbook.export": "runs-wide"},
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
        metric_counts = Counter(row["metric_name"] for row in rows)
        metric_set = sorted(set(metric_names or metric_counts.keys()))
        coverage_rows = [
            {
                "experiment_id": experiment["id"],
                "metric_name": metric_name,
                "run_count": metric_counts.get(metric_name, 0),
                "total_runs": total_runs,
                "coverage": metric_counts.get(metric_name, 0) / total_runs if total_runs else 0.0,
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
        source_job_id = self.get_job(source_job_ref)["id"] if source_job_ref else None
        source_artifact_id = self.get_artifact(source_artifact_ref)["id"] if source_artifact_ref else None
        now = utc_now()
        existing = self.conn.execute(
            "SELECT id FROM metrics WHERE run_id = ? AND metric_name = ? AND COALESCE(step, '') = COALESCE(?, '') "
            "AND COALESCE(split, '') = COALESCE(?, '') AND COALESCE(source_job_id, '') = COALESCE(?, '') "
            "AND COALESCE(source_artifact_id, '') = COALESCE(?, '') AND deleted_at IS NULL",
            (run_id, metric_name, step, split, source_job_id, source_artifact_id),
        ).fetchone()
        with self.conn:
            if existing:
                metric_id = existing["id"]
                self.conn.execute(
                    "UPDATE metrics SET value = ?, updated_at = ? WHERE id = ?",
                    (value, now, metric_id),
                )
            else:
                metric_id = new_id("met")
                self.conn.execute(
                    "INSERT INTO metrics (id, run_id, metric_name, value, step, split, source_job_id, "
                    "source_artifact_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (metric_id, run_id, metric_name, value, step, split, source_job_id, source_artifact_id, now, now),
                )
        return self.get_metric(metric_id)

    def import_metrics_csv(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                run_ref = row.get("run_id") or row.get("run")
                metric_name = row.get("metric_name") or row.get("name")
                raw_value = row.get("value")
                if not run_ref or not metric_name or raw_value is None:
                    raise ValidationError("metric CSV requires run_id/run, metric_name/name, and value columns")
                rows.append(
                    self.add_metric(
                        run_ref=run_ref,
                        metric_name=metric_name,
                        value=validate_metric_value(raw_value),
                        step=row.get("step") or None,
                        split=row.get("split") or None,
                        source_job_ref=row.get("source_job_id") or None,
                        source_artifact_ref=row.get("source_artifact_id") or None,
                    )
                )
        return rows

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
        body: str,
        author: str | None,
        attrs: dict[str, Any],
    ) -> dict[str, Any]:
        require_choice(entity_type, ENTITY_TYPES, "entity type")
        require_choice(note_type, NOTE_TYPES, "note type")
        require_choice(status, NOTE_STATUSES, "note status")
        entity_id = self._resolve_entity_id(entity_type, entity_ref)
        now = utc_now()
        note_id = new_id("note")
        with self.conn:
            self.conn.execute(
                "INSERT INTO notes (id, entity_type, entity_id, note_type, status, body, author, created_at, "
                "updated_at, attrs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (note_id, entity_type, entity_id, note_type, status, body, author, now, now, attrs_json(attrs)),
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

    def _replace_experiment_tags(self, experiment_id: str, tags: list[str]) -> None:
        self.conn.execute("DELETE FROM experiment_tags WHERE experiment_id = ?", (experiment_id,))
        self.conn.executemany(
            "INSERT INTO experiment_tags (experiment_id, tag) VALUES (?, ?)",
            [(experiment_id, tag) for tag in tags],
        )

    def _link_run_ids(self, experiment_id: str, run_id: str) -> None:
        now = utc_now()
        self.conn.execute(
            "INSERT OR IGNORE INTO experiment_runs (experiment_id, run_id, created_at) VALUES (?, ?, ?)",
            (experiment_id, run_id, now),
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
        }[entity_type]
        name_column = "name" if entity_type in {"experiment", "run", "job"} else None
        return self._resolve_row(table, ref, name_column=name_column)["id"]

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
        data["attrs"] = load_attrs(data.pop("attrs_json", "{}"))
        data["code_dirty"] = bool(data["code_dirty"])
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
