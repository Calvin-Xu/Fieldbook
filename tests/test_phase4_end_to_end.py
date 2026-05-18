import json
import subprocess
import sys
from pathlib import Path


def run_fieldbook(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "fieldbook", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def payload(result: subprocess.CompletedProcess[str]):
    return json.loads(result.stdout)


def test_agent_end_to_end_flow_from_subdirectory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    init = payload(run_fieldbook(repo, "init", "--json"))
    ledger_path = Path(init["ledger"])
    assert ledger_path == repo / ".experiments" / "ledger.sqlite"

    experiment = payload(
        run_fieldbook(
            repo,
            "experiment",
            "create",
            "--name",
            "agent dogfood",
            "--description",
            "End-to-end agent workflow",
            "--tag",
            "marin",
            "--attr",
            "marin.issue=5416",
            "--json",
        )
    )
    run = payload(
        run_fieldbook(
            repo,
            "run",
            "add",
            "--experiment",
            experiment["id"],
            "--name",
            "dogfood_run",
            "--attr",
            "marin.scale=300m_6b",
            "--json",
        )
    )
    job = payload(
        run_fieldbook(
            repo,
            "job",
            "add",
            "--run",
            run["id"],
            "--name",
            "train",
            "--status",
            "running",
            "--launcher",
            "iris",
            "--external-system",
            "iris",
            "--external-id",
            "/calvinxu/dogfood-train",
            "--json",
        )
    )
    run_fieldbook(
        repo,
        "artifact",
        "add",
        "--run",
        run["id"],
        "--type",
        "checkpoint",
        "--uri",
        "gs://example/checkpoint",
        "--json",
    )
    run_fieldbook(
        repo,
        "metric",
        "add",
        "--run",
        run["id"],
        "--name",
        "eval/uncheatable_eval/bpb",
        "--value",
        "0.91",
        "--source-job",
        job["id"],
        "--json",
    )
    run_fieldbook(
        repo,
        "note",
        "add",
        "--entity-type",
        "experiment",
        "--entity-id",
        experiment["id"],
        "--type",
        "next-action",
        "--body",
        "Collect follow-up evals.",
        "--json",
    )

    manifest = Path(__file__).parent / "fixtures" / "marin" / "eval_completion_manifest.json"
    reconcile = payload(
        run_fieldbook(
            repo,
            "reconcile",
            "file",
            "--experiment",
            experiment["id"],
            "--path",
            str(manifest),
            "--source",
            "fixture",
            "--apply",
            "--json",
        )
    )
    assert reconcile["counts"]["insert"]["metrics"] == 1

    long_path = repo / ".experiments" / "metrics_long.csv"
    wide_path = repo / ".experiments" / "runs_wide.csv"
    run_fieldbook(repo, "export", "metrics-long", "--experiment", experiment["id"], "--output", str(long_path), "--json")
    run_fieldbook(
        repo,
        "export",
        "runs-wide",
        "--experiment",
        experiment["id"],
        "--output",
        str(wide_path),
        "--metric",
        "eval/uncheatable_eval/bpb",
        "--json",
    )
    assert long_path.exists()
    assert wide_path.exists()

    subdir = repo / "analysis" / "notebooks"
    subdir.mkdir(parents=True)
    status = payload(run_fieldbook(subdir, "experiment", "status", experiment["id"], "--json"))
    assert status["run_count"] == 2
    assert status["job_counts"] == {"running": 1, "succeeded": 1}
    assert status["next_actions"][0]["body"] == "Collect follow-up evals."
