import csv
import json
import subprocess
import sys
from pathlib import Path

from fieldbook.errors import ExitCode
from tests.test_phase2_cli import create_experiment, init_ledger, payload, run_fieldbook


def run_adapter(
    *args: str,
    cwd: Path,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", *args],
        cwd=cwd,
        text=True,
        input=input_text,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def test_adapter_list_and_describe_json(tmp_path):
    listed = json.loads(run_adapter("adapter", "list", "--json", cwd=tmp_path).stdout)
    names = {item["name"] for item in listed}
    assert {"iris-jobs-json", "wandb-runs-json", "metrics-csv", "artifacts-json"}.issubset(names)

    described = json.loads(run_adapter("adapter", "describe", "metrics-csv", "--json", cwd=tmp_path).stdout)
    assert described["name"] == "metrics-csv"
    assert described["emits"] == ["metrics"]
    assert "run_id" in described["required_fields"]
    assert "finite float" in " ".join(described["coercion_rules"])

    unknown = run_adapter("adapter", "describe", "missing-adapter", "--json", cwd=tmp_path, check=False)
    assert unknown.returncode == ExitCode.VALIDATION_ERROR


def test_adapter_run_iris_jobs_json_clean_and_debug(tmp_path):
    source = tmp_path / "iris.json"
    source.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "external_id": "/calvinxu/train",
                        "status": "running",
                        "name": "train",
                        "launcher": "iris",
                        "started_at": "2026-05-18T00:00:00Z",
                        "attrs": {"marin.scale": "300m_6b"},
                    },
                    {"external_id": "/calvinxu/bad", "status": "not-a-fieldbook-status"},
                ]
            }
        )
    )
    output = tmp_path / "manifest.json"
    debug = tmp_path / "debug.json"

    result = json.loads(
        run_adapter(
            "adapter",
            "run",
            "iris-jobs-json",
            "--input",
            str(source),
            "--output",
            str(output),
            "--debug-output",
            str(debug),
            "--json",
            cwd=tmp_path,
        ).stdout
    )

    assert result["outcome"] == "partial"
    assert result["input_rows"] == 2
    assert result["skipped_rows"] == 1
    manifest = json.loads(output.read_text())
    assert manifest["manifest_version"] == 1
    assert manifest["jobs"] == [
        {
            "attrs": {"marin.scale": "300m_6b"},
            "external_id": "/calvinxu/train",
            "external_system": "iris",
            "launcher": "iris",
            "name": "train",
            "started_at": "2026-05-18T00:00:00Z",
            "status": "running",
        }
    ]
    assert manifest["sync_events"][0]["target_system"] == "iris"
    assert manifest["sync_events"][0]["status"] == "synced"
    assert manifest["sync_events"][0]["target_identifier"] == "/calvinxu/train"
    skipped = json.loads(debug.read_text())["skipped_rows"]
    assert skipped[0]["row_index"] == 1
    assert skipped[0]["source_row"]["status"] == "not-a-fieldbook-status"


def test_adapter_run_wandb_runs_json_preserves_attrs(tmp_path):
    source = tmp_path / "wandb.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": "wandb-abc",
                    "name": "run_00097",
                    "description": "baseline",
                    "url": "https://wandb.ai/example/run",
                    "project": "marin",
                    "entity": "fieldbook",
                    "state": "finished",
                    "summary": {"eval/loss": 1.25},
                    "attrs": {"marin.mixture": "proportional"},
                }
            ]
        )
    )
    output = tmp_path / "manifest.json"

    run_adapter("adapter", "run", "wandb-runs-json", "--input", str(source), "--output", str(output), cwd=tmp_path)

    manifest = json.loads(output.read_text())
    assert manifest["runs"][0]["external_system"] == "wandb"
    assert manifest["runs"][0]["external_id"] == "wandb-abc"
    assert manifest["runs"][0]["attrs"] == {
        "marin.mixture": "proportional",
        "wandb.entity": "fieldbook",
        "wandb.project": "marin",
        "wandb.state": "finished",
        "wandb.summary": {"eval/loss": 1.25},
        "wandb.url": "https://wandb.ai/example/run",
    }
    assert manifest["custom_attributes"] == []
    assert manifest["sync_events"][0]["idempotency_key"].startswith("adapter:wandb-runs-json:")


def test_adapter_run_metrics_csv_and_artifacts_json(tmp_path):
    metrics = tmp_path / "metrics.csv"
    with metrics.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_id", "run_external_id", "metric_name", "value", "step", "split"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "run_abc",
                "metric_name": "eval/uncheatable_eval/bpb",
                "value": "0.91",
                "step": "00100",
                "split": "validation",
            }
        )
        writer.writerow({"run_id": "run_abc", "metric_name": "bad", "value": "nan"})
        writer.writerow({"run_external_id": "wandb-abc", "metric_name": "missing-ledger-id", "value": "1.0"})
    metrics_output = tmp_path / "metrics_manifest.json"
    metrics_debug = tmp_path / "metrics_debug.json"

    run_adapter(
        "adapter",
        "run",
        "metrics-csv",
        "--input",
        str(metrics),
        "--output",
        str(metrics_output),
        "--debug-output",
        str(metrics_debug),
        cwd=tmp_path,
    )

    metrics_manifest = json.loads(metrics_output.read_text())
    assert metrics_manifest["metrics"] == [
        {
            "metric_name": "eval/uncheatable_eval/bpb",
            "run_id": "run_abc",
            "split": "validation",
            "step": "00100",
            "value": 0.91,
        }
    ]
    assert len(json.loads(metrics_debug.read_text())["skipped_rows"]) == 2

    artifacts = tmp_path / "artifacts.json"
    artifacts.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "run_id": "run_abc",
                        "type": "eval-result",
                        "uri": "gs://example/evals/results.json",
                        "attrs": {"marin.eval": "english-lite"},
                    }
                ]
            }
        )
    )
    artifact_output = tmp_path / "artifact_manifest.json"

    run_adapter(
        "adapter",
        "run",
        "artifacts-json",
        "--input",
        str(artifacts),
        "--output",
        str(artifact_output),
        cwd=tmp_path,
    )

    artifact_manifest = json.loads(artifact_output.read_text())
    assert artifact_manifest["artifacts"][0]["uri"] == "gs://example/evals/results.json"
    assert artifact_manifest["artifacts"][0]["attrs"] == {"marin.eval": "english-lite"}


def test_adapter_strict_and_hard_parse_failure(tmp_path):
    source = tmp_path / "iris.json"
    source.write_text(json.dumps([{"external_id": "/calvinxu/bad", "status": "not-valid"}]))
    output = tmp_path / "manifest.json"
    debug = tmp_path / "debug.json"

    strict = run_adapter(
        "adapter",
        "run",
        "iris-jobs-json",
        "--input",
        str(source),
        "--output",
        str(output),
        "--debug-output",
        str(debug),
        "--strict",
        cwd=tmp_path,
        check=False,
    )

    assert strict.returncode == ExitCode.VALIDATION_ERROR
    assert not output.exists()
    assert json.loads(debug.read_text())["skipped_rows"][0]["source_row"]["status"] == "not-valid"

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json")
    hard_debug = tmp_path / "hard_debug.json"
    hard = run_adapter(
        "adapter",
        "run",
        "wandb-runs-json",
        "--input",
        str(bad_json),
        "--output",
        str(output),
        "--debug-output",
        str(hard_debug),
        cwd=tmp_path,
        check=False,
    )
    assert hard.returncode == ExitCode.VALIDATION_ERROR
    assert json.loads(hard_debug.read_text())["outcome"] == "failed"


def test_adapter_stdin_stdout_and_conflict(tmp_path):
    source = json.dumps([{"id": "wandb-abc", "name": "run_00097"}])
    result = run_adapter(
        "adapter",
        "run",
        "wandb-runs-json",
        "--input",
        "-",
        "--output",
        "-",
        cwd=tmp_path,
        input_text=source,
    )
    manifest = json.loads(result.stdout)
    assert manifest["runs"][0]["external_id"] == "wandb-abc"

    conflict = run_adapter(
        "adapter",
        "run",
        "wandb-runs-json",
        "--input",
        "-",
        "--output",
        "-",
        "--debug-output",
        "-",
        cwd=tmp_path,
        input_text=source,
        check=False,
    )
    assert conflict.returncode == ExitCode.VALIDATION_ERROR


def test_adapter_output_reconciles_end_to_end(tmp_path):
    ledger = init_ledger(tmp_path)
    experiment_id = create_experiment(ledger)

    runs = tmp_path / "wandb.json"
    runs.write_text(json.dumps([{"id": "wandb-abc", "name": "run_00097"}]))
    runs_manifest = tmp_path / "runs_manifest.json"
    run_adapter("adapter", "run", "wandb-runs-json", "--input", str(runs), "--output", str(runs_manifest), cwd=tmp_path)
    applied_runs = payload(
        run_fieldbook(
            ledger,
            "reconcile",
            "file",
            "--experiment",
            experiment_id,
            "--path",
            str(runs_manifest),
            "--source",
            "adapter-wandb",
            "--apply",
        )
    )
    assert applied_runs["counts"]["insert"]["runs"] == 1
    run_id = payload(run_fieldbook(ledger, "run", "list", "--experiment", experiment_id))[0]["id"]

    metrics = tmp_path / "metrics.csv"
    metrics.write_text(f"run_id,metric_name,value\n{run_id},eval/loss,1.25\n")
    metrics_manifest = tmp_path / "metrics_manifest.json"
    run_adapter(
        "adapter",
        "run",
        "metrics-csv",
        "--input",
        str(metrics),
        "--output",
        str(metrics_manifest),
        cwd=tmp_path,
    )
    applied_metrics = payload(
        run_fieldbook(
            ledger,
            "reconcile",
            "file",
            "--path",
            str(metrics_manifest),
            "--source",
            "adapter-metrics",
            "--apply",
        )
    )

    assert applied_metrics["counts"]["insert"]["metrics"] == 1
    metric = payload(run_fieldbook(ledger, "metric", "list", "--run", run_id))[0]
    assert metric["metric_name"] == "eval/loss"
    assert metric["value"] == 1.25
