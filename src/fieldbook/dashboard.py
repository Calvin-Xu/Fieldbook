import html
import contextlib
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fieldbook.errors import NotFoundError, ValidationError


DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765


_QUERIES = {
    "experiments": "SELECT * FROM v_dashboard_experiments_v1 ORDER BY updated_at DESC, experiment_id",
    "experiment": "SELECT * FROM v_dashboard_experiments_v1 WHERE experiment_id = ?",
    "runs": "SELECT * FROM v_dashboard_runs_v1 WHERE experiment_id = ? ORDER BY run_id LIMIT 100",
    "jobs": "SELECT * FROM v_dashboard_jobs_v1 WHERE experiment_id = ? ORDER BY updated_at DESC, job_id LIMIT 100",
    "leases": "SELECT * FROM v_dashboard_leases_v1 WHERE experiment_id = ? ORDER BY released_at IS NOT NULL, heartbeat_at DESC LIMIT 100",
    "validations": "SELECT * FROM v_dashboard_validations_v1 WHERE experiment_id = ? ORDER BY updated_at DESC LIMIT 100",
    "notes": "SELECT * FROM v_dashboard_notes_v1 WHERE experiment_id = ? ORDER BY updated_at DESC LIMIT 50",
    "artifacts": "SELECT * FROM v_dashboard_artifacts_v1 WHERE experiment_id = ? ORDER BY updated_at DESC LIMIT 100",
    "external_links": "SELECT * FROM v_dashboard_external_links_v1 WHERE experiment_id = ? ORDER BY entity_type, entity_id LIMIT 100",
}


def dashboard_queries() -> dict[str, str]:
    return dict(_QUERIES)


def dashboard_routes() -> list[dict[str, str]]:
    return [
        {"method": "GET", "path": "/"},
        {"method": "GET", "path": "/experiment"},
        {"method": "GET", "path": "/healthz"},
    ]


def server_config(*, host: str | None, port: int | None, allow_non_localhost: bool) -> dict[str, Any]:
    resolved_host = host or DEFAULT_DASHBOARD_HOST
    resolved_port = DEFAULT_DASHBOARD_PORT if port is None else port
    if resolved_host not in {"127.0.0.1", "localhost", "::1"} and not allow_non_localhost:
        raise ValidationError("dashboard serve requires --allow-non-localhost for non-local hosts")
    if not 0 <= resolved_port <= 65535:
        raise ValidationError("dashboard port must be between 0 and 65535")
    return {"host": resolved_host, "port": resolved_port}


def render_experiment_index(ledger_path: Path) -> str:
    with contextlib.closing(_connect_readonly(ledger_path)) as conn:
        experiments = [_row(row) for row in conn.execute(_QUERIES["experiments"]).fetchall()]
    groups = {
        "Active": [],
        "Needing Attention": [],
        "Stale": [],
        "Archived": [],
    }
    for experiment in experiments:
        groups[_experiment_group(experiment)].append(experiment)
    body = ["<h1>Fieldbook Dashboard</h1>"]
    if not experiments:
        body.append("<p>No experiments recorded yet.</p>")
        body.append(_command("fieldbook experiment create --name <name> --json"))
    for title, rows in groups.items():
        body.append(f"<h2>{_esc(title)}</h2>")
        if not rows:
            body.append("<p class='muted'>(none)</p>")
            continue
        body.append("<ul>")
        for row in rows:
            href = f"/experiment?id={_esc(row['experiment_id'])}"
            counts = f"runs={row['run_count']} jobs={row['job_count']} leases={row['active_lease_count']}"
            body.append(
                "<li>"
                f"<a href='{href}'>{_esc(row['name'])}</a> "
                f"<code>{_esc(row['experiment_id'])}</code> "
                f"<span>{_esc(counts)}</span>"
                "</li>"
            )
        body.append("</ul>")
    return _page("Fieldbook Dashboard", "\n".join(body))


def render_experiment_detail(ledger_path: Path, experiment_id: str) -> str:
    with contextlib.closing(_connect_readonly(ledger_path)) as conn:
        experiment = conn.execute(_QUERIES["experiment"], (experiment_id,)).fetchone()
        if experiment is None:
            return _page("Experiment Not Found", f"<h1>Experiment not found</h1><p>{_esc(experiment_id)}</p>", status=404)
        sections = {
            "runs": [_row(row) for row in conn.execute(_QUERIES["runs"], (experiment_id,)).fetchall()],
            "jobs": [_row(row) for row in conn.execute(_QUERIES["jobs"], (experiment_id,)).fetchall()],
            "leases": [_row(row) for row in conn.execute(_QUERIES["leases"], (experiment_id,)).fetchall()],
            "validations": [_row(row) for row in conn.execute(_QUERIES["validations"], (experiment_id,)).fetchall()],
            "notes": [_row(row) for row in conn.execute(_QUERIES["notes"], (experiment_id,)).fetchall()],
            "artifacts": [_row(row) for row in conn.execute(_QUERIES["artifacts"], (experiment_id,)).fetchall()],
            "external_links": [_row(row) for row in conn.execute(_QUERIES["external_links"], (experiment_id,)).fetchall()],
        }
    exp = _row(experiment)
    body = [
        f"<h1>{_esc(exp['name'])}</h1>",
        f"<p><code>{_esc(exp['experiment_id'])}</code> status={_esc(exp['status'])}</p>",
        _command(f"fieldbook experiment workloop {exp['experiment_id']} --json"),
        _command(f"fieldbook refresh run --experiment {exp['experiment_id']} --source <source> --json"),
        _section("Run Progress", _table(sections["runs"])),
        _section("Job Recovery", _table(sections["jobs"])),
        _section("Advisory Leases", _table(sections["leases"])),
        _section("Validations", _table(sections["validations"])),
        _section("Freshness", _freshness(exp)),
        _section("Notes", _table(sections["notes"])),
        _section("Artifacts", _table(sections["artifacts"])),
        _section("External Links", _links(sections["external_links"])),
    ]
    return _page(f"Fieldbook: {exp['name']}", "\n".join(body))


def make_dashboard_server(ledger_path: Path, *, host: str, port: int) -> ThreadingHTTPServer:
    if not ledger_path.exists():
        raise NotFoundError("no Fieldbook ledger found; run `fieldbook init` first")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                _send(self, 200, "ok", content_type="text/plain; charset=utf-8")
                return
            if parsed.path == "/":
                _send(self, 200, render_experiment_index(ledger_path))
                return
            if parsed.path == "/experiment":
                experiment_id = parse_qs(parsed.query).get("id", [""])[0]
                status = 200 if experiment_id and _experiment_exists(ledger_path, experiment_id) else 404
                _send(self, status, render_experiment_detail(ledger_path, experiment_id))
                return
            _send(self, 404, _page("Not Found", "<h1>Not Found</h1>"))

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook
            _send(self, 405, "read-only dashboard", content_type="text/plain; charset=utf-8")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def log_message(self, _format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve_dashboard(ledger_path: Path, *, host: str, port: int, announce: bool = True) -> None:
    server = make_dashboard_server(ledger_path, host=host, port=port)
    if announce:
        print(f"fieldbook dashboard: http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _connect_readonly(ledger_path: Path) -> sqlite3.Connection:
    if not ledger_path.exists():
        raise NotFoundError("no Fieldbook ledger found; run `fieldbook init` first")
    uri = f"{ledger_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _experiment_exists(ledger_path: Path, experiment_id: str) -> bool:
    with contextlib.closing(_connect_readonly(ledger_path)) as conn:
        return conn.execute(_QUERIES["experiment"], (experiment_id,)).fetchone() is not None


def _experiment_group(row: dict[str, Any]) -> str:
    if row["deleted_at"] is not None or row["status"] == "archived":
        return "Archived"
    if row["failed_job_count"] or row["failing_validation_count"]:
        return "Needing Attention"
    if row["stale_lease_count"] or row["last_checkpoint_at"] is None:
        return "Stale"
    return "Active"


def _page(title: str, body: str, *, status: int = 200) -> str:
    return (
        "<!doctype html><html><head>"
        f"<title>{_esc(title)}</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:1100px;margin:32px auto;padding:0 18px;line-height:1.45}"
        "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}"
        "code{background:#f4f4f4;padding:2px 4px;border-radius:4px}.command{display:block;margin:8px 0;padding:8px;background:#f7f7f7}"
        ".muted{color:#666}</style></head><body>"
        f"{body}"
        f"<!-- status:{status} -->"
        "</body></html>"
    )


def _section(title: str, body: str) -> str:
    return f"<h2>{_esc(title)}</h2>\n{body}"


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    columns = list(rows[0].keys())[:10]
    header = "".join(f"<th>{_esc(column)}</th>" for column in columns)
    body = []
    for row in rows[:25]:
        body.append("<tr>" + "".join(f"<td>{_esc(row.get(column))}</td>" for column in columns) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _links(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    items = []
    for row in rows:
        url = str(row["url"])
        items.append(f"<li>{_esc(row['entity_type'])} <a href='{_esc(url)}'>{_esc(url)}</a></li>")
    return "<ul>" + "".join(items) + "</ul>"


def _freshness(row: dict[str, Any]) -> str:
    checkpoint = row["last_checkpoint_at"] or "missing"
    return f"<p>Last checkpoint: <code>{_esc(checkpoint)}</code></p>"


def _command(command: str) -> str:
    return f"<code class='command'>{_esc(command)}</code>"


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _send(handler: BaseHTTPRequestHandler, status: int, body: str, *, content_type: str = "text/html; charset=utf-8") -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
