import html
import contextlib
import sqlite3
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fieldbook.errors import NotFoundError, ValidationError
from fieldbook.prompts import build_prompt, prompt_actions


DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765

_TAB_LABELS = {
    "overview": "Overview",
    "runs": "Run Progress",
    "jobs": "Job Recovery",
    "leases": "Advisory Leases",
    "validations": "Validations",
    "freshness": "Freshness",
    "notes": "Notes",
    "artifacts": "Artifacts",
    "external-links": "External Links",
}


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
        groups = _experiment_groups(conn)
    experiments = [experiment for rows in groups.values() for experiment in rows]
    body = [
        "<div class='dashboard-shell'>",
        _experiment_sidebar(groups),
        "<main class='dashboard-main'>",
        "<h1>Fieldbook Dashboard</h1>",
        "<p class='muted'>Read-only experiment registry for agent-operated work.</p>",
    ]
    if not experiments:
        body.append("<p>No experiments recorded yet.</p>")
    for title, rows in groups.items():
        slug = _slug(title)
        if title == "Archived":
            body.append(f"<details class='group archived-group' id='{slug}'>")
            body.append(f"<summary>{_esc(title)} <span class='count'>{len(rows)}</span></summary>")
        else:
            body.append(f"<section class='group' id='{slug}'>")
            body.append(f"<h2>{_esc(title)} <span class='count'>{len(rows)}</span></h2>")
        if not rows:
            body.append("<p class='muted'>(none)</p>")
            body.append("</details>" if title == "Archived" else "</section>")
            continue
        body.append("<div class='card-grid index-grid'>")
        for row in rows:
            href = f"/experiment?id={_esc(row['experiment_id'])}"
            body.append(
                "<article class='card experiment-card'>"
                f"<div class='card-title'><a href='{href}'>{_esc(row['name'])}</a></div>"
                f"<code>{_esc(row['experiment_id'])}</code>"
                f"<div class='pill-row'>{_status_chip(row['status'])}"
                f"{_pill('runs', row['run_count'])}{_pill('jobs', row['job_count'])}"
                f"{_pill('blocking failed', row['blocking_failed_job_count'])}"
                f"{_pill('recovering', row['recovery_in_progress_failed_job_count'])}"
                f"{_pill('review pending', row.get('has_pending_review', 0))}"
                f"{_pill('handoff', row.get('handoff_status', 'unknown'))}"
                f"{_pill('leases', row['active_lease_count'])}</div>"
                "</article>"
            )
        body.append("</div>")
        body.append("</details>" if title == "Archived" else "</section>")
    body.append("</main></div>")
    return _page("Fieldbook Dashboard", "\n".join(body))


def render_experiment_detail(ledger_path: Path, experiment_id: str, *, tab: str = "overview") -> str:
    _status, body = _render_experiment_detail_response(ledger_path, experiment_id, tab=tab)
    return body


def _render_experiment_detail_response(ledger_path: Path, experiment_id: str, *, tab: str = "overview") -> tuple[int, str]:
    with contextlib.closing(_connect_readonly(ledger_path)) as conn:
        experiment = conn.execute(_QUERIES["experiment"], (experiment_id,)).fetchone()
        if experiment is None:
            return 404, _page("Experiment Not Found", f"<h1>Experiment not found</h1><p>{_esc(experiment_id)}</p>", status=404)
        groups = _experiment_groups(conn)
        exp = _row(experiment)
        active_tab = tab if tab in _TAB_LABELS else "overview"
        tab_panel = _tab_panel(conn, active_tab, exp)
    body = [
        "<div class='dashboard-shell'>",
        _experiment_sidebar(groups, category_base="/", current_experiment_id=experiment_id),
        "<main class='dashboard-main'>",
        "<a class='back-link' href='/'>All experiments</a>",
        f"<header class='hero'><div><h1>{_esc(exp['name'])}</h1>"
        f"<p><code>{_esc(exp['experiment_id'])}</code></p></div>{_status_chip(exp['status'])}</header>",
        _metric_cards(exp),
        _tab_bar(exp["experiment_id"], active_tab),
        tab_panel,
        "</main></div>",
    ]
    return 200, _page(f"Fieldbook: {exp['name']}", "\n".join(body))


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
                tab = parse_qs(parsed.query).get("tab", ["overview"])[0]
                status, body = _render_experiment_detail_response(ledger_path, experiment_id, tab=tab)
                _send(self, status, body)
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


def _experiment_groups(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "Needs attention": [],
        "In progress": [],
        "Review": [],
        "Open": [],
        "Archived": [],
    }
    for row in conn.execute(_QUERIES["experiments"]).fetchall():
        experiment = _row(row)
        groups[_experiment_group(experiment)].append(experiment)
    return groups


def _fetch_rows(conn: sqlite3.Connection, query_name: str, experiment_id: str) -> list[dict[str, Any]]:
    return [_row(row) for row in conn.execute(_QUERIES[query_name], (experiment_id,)).fetchall()]


def _experiment_group(row: dict[str, Any]) -> str:
    lifecycle_state = row.get("lifecycle_state")
    labels = {
        "needs_attention": "Needs attention",
        "in_progress": "In progress",
        "review": "Review",
        "open": "Open",
        "archived": "Archived",
    }
    if lifecycle_state in labels:
        return labels[lifecycle_state]
    if row["deleted_at"] is not None or row["status"] == "archived":
        return "Archived"
    return "Open"


def _page(title: str, body: str, *, status: int = 200) -> str:
    return (
        "<!doctype html><html><head>"
        f"<title>{_esc(title)}</title>"
        "<style>"
        ":root{--bg:#f6f8fb;--surface:#fff;--surface-2:#eef3f8;--text:#172033;--muted:#667085;"
        "--line:#d8e0ea;--ok:#16794c;--warn:#9a6700;--bad:#b42318;--accent:#285ea8}"
        "*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:var(--bg);"
        "color:var(--text);max-width:1500px;margin:20px auto;padding:0 18px;line-height:1.4;font-size:14px}"
        "a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}"
        "h1{font-size:24px;margin:0 0 4px}h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:22px 0 9px}"
        "code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--surface-2);padding:2px 5px;border-radius:5px;white-space:normal;overflow-wrap:anywhere;word-break:break-word}"
        ".muted{color:var(--muted)}.count{font-size:12px;color:var(--muted);font-weight:500}.group{margin-bottom:22px}.group summary{cursor:pointer;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700;margin:24px 0 10px}"
        ".dashboard-shell{display:grid;grid-template-columns:290px minmax(0,1fr);gap:22px;align-items:start}.dashboard-main{min-width:0}.experiment-sidebar{position:sticky;top:18px;max-height:calc(100vh - 36px);overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px;min-width:0}"
        ".experiment-sidebar h2{margin-top:0}.sidebar-group{border-top:1px solid var(--line);padding:8px 0}.sidebar-group:first-of-type{border-top:0}.sidebar-group summary{cursor:pointer;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}.sidebar-link{display:block;margin:6px 0;padding:6px;border-radius:8px;overflow-wrap:anywhere}.sidebar-link:hover{background:var(--surface-2);text-decoration:none}"
        ".sidebar-link.current{background:#e8f1ff;color:var(--text);font-weight:650;outline:1px solid #c8dbf7}"
        ".card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.index-grid{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}"
        ".card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px;box-shadow:0 1px 2px rgba(16,24,40,.04);min-width:0;overflow:hidden}.experiment-card{overflow-wrap:anywhere}"
        ".card-title{font-weight:650;margin-bottom:4px;overflow-wrap:anywhere}.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px;min-width:0}.hero div{min-width:0}"
        ".metric-grid{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:9px;margin:10px 0}.metric{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:9px}"
        ".metric-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.metric-value{font-size:20px;font-weight:700}"
        ".pill-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.pill,.status-chip{display:inline-flex;gap:4px;align-items:center;border-radius:999px;border:1px solid var(--line);padding:2px 8px;font-size:12px;background:var(--surface-2)}"
        ".status-chip.active,.status-chip.succeeded,.status-chip.pass{color:var(--ok);border-color:#b8dfca;background:#edf9f1}"
        ".status-chip.failed,.status-chip.fail{color:var(--bad);border-color:#fac5c0;background:#fff1f0}"
        ".status-chip.running,.status-chip.queued,.status-chip.submitting{color:var(--warn);border-color:#f7d894;background:#fff8e7}"
        ".tab-bar{display:flex;gap:6px;overflow-x:auto;border-bottom:1px solid var(--line);margin:16px 0 14px;padding-bottom:0}.tab-bar a{white-space:nowrap;font-size:13px;padding:9px 12px;border:1px solid transparent;border-bottom:0;border-radius:10px 10px 0 0}.tab-bar a.active{background:var(--surface);border-color:var(--line);color:var(--text);font-weight:700}.tab-panel{min-width:0}"
        ".entity-row{display:grid;grid-template-columns:minmax(0,1.25fr) 120px minmax(0,2fr) minmax(0,1fr);gap:10px;align-items:start;border-top:1px solid var(--line);padding:9px 0;min-width:0;overflow-wrap:anywhere}"
        ".entity-row>div{min-width:0;overflow-wrap:anywhere}.text-clamp{display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden}.path-text{overflow-wrap:anywhere;word-break:break-word}"
        ".entity-row:first-child{border-top:0}.two-col{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}"
        ".attention{background:#fffaf0;border-color:#f2d28b}.prompt-card details{margin-top:8px}.prompt-card pre{white-space:pre-wrap;background:#0f172a;color:#e5e7eb;border-radius:10px;padding:10px;overflow:auto}"
        ".prompt-title-row{display:flex;align-items:start;justify-content:space-between;gap:8px}.copy-button{border:1px solid var(--line);border-radius:8px;background:var(--surface-2);color:var(--accent);font:inherit;font-size:12px;font-weight:650;padding:4px 8px;cursor:pointer;white-space:nowrap}.copy-button:hover{background:#e8f1ff}.copy-button.copied{color:var(--ok);border-color:#b8dfca;background:#edf9f1}"
        ".back-link{font-size:13px}.external-list{display:grid;gap:8px}.external-list a{word-break:break-all}"
        "@media(max-width:900px){.dashboard-shell{grid-template-columns:1fr}.experiment-sidebar{position:static;max-height:none}.metric-grid{grid-template-columns:repeat(2,1fr)}.entity-row{grid-template-columns:1fr}}"
        "</style><script>document.addEventListener('click',async function(event){var button=event.target.closest('button[data-copy-target]');if(!button){return;}var target=document.getElementById(button.getAttribute('data-copy-target'));if(!target){return;}var original=button.textContent;try{await navigator.clipboard.writeText(target.textContent);button.textContent='Copied';button.classList.add('copied');setTimeout(function(){button.textContent=original;button.classList.remove('copied');},1200);}catch(error){button.textContent='Copy failed';setTimeout(function(){button.textContent=original;},1600);}});</script></head><body>"
        f"{body}"
        f"<!-- status:{status} -->"
        "</body></html>"
    )


def _section(title: str, body: str, *, section_id: str | None = None) -> str:
    attr = f" id='{_esc(section_id)}'" if section_id else ""
    return f"<section{attr}><h2>{_esc(title)}</h2>\n{body}</section>"


def _experiment_sidebar(
    groups: dict[str, list[dict[str, Any]]],
    *,
    category_base: str = "",
    current_experiment_id: str | None = None,
) -> str:
    sections = ["<aside class='experiment-sidebar'><h2>Experiments</h2>"]
    for title, rows in groups.items():
        contains_current = any(row["experiment_id"] == current_experiment_id for row in rows)
        open_attr = " open" if title != "Archived" or contains_current else ""
        sections.append(f"<details class='sidebar-group'{open_attr}><summary>{_esc(title)} {len(rows)}</summary>")
        sections.append(f"<a class='sidebar-link category-link' href='{_esc(category_base)}#{_esc(_slug(title))}'>View {_esc(title)}</a>")
        if not rows:
            sections.append("<p class='muted'>(none)</p>")
        for row in rows:
            href = f"/experiment?id={_esc(row['experiment_id'])}"
            current_attr = " aria-current='page'" if row["experiment_id"] == current_experiment_id else ""
            classes = "sidebar-link current" if current_attr else "sidebar-link"
            sections.append(
                f"<a class='{classes}' href='{href}'{current_attr}>"
                f"<strong>{_esc(row['name'])}</strong><br><code>{_esc(row['experiment_id'])}</code>"
                "</a>"
            )
        sections.append("</details>")
    sections.append("</aside>")
    return "\n".join(sections)


def _tab_bar(experiment_id: str, active_tab: str) -> str:
    links = []
    for key, label in _TAB_LABELS.items():
        active = " active" if key == active_tab else ""
        href = f"/experiment?id={_esc(experiment_id)}&tab={_esc(key)}"
        links.append(f"<a class='tab{active}' href='{href}'>{_esc(label)}</a>")
    return '<nav class="tab-bar">' + "".join(links) + "</nav>"


def _tab_panel(conn: sqlite3.Connection, active_tab: str, exp: dict[str, Any]) -> str:
    experiment_id = exp["experiment_id"]
    if active_tab == "runs":
        return _tab_section("Run Progress", _run_cards(_fetch_rows(conn, "runs", experiment_id)))
    if active_tab == "jobs":
        return _tab_section(
            "Job Recovery",
            _job_cards(
                _fetch_rows(conn, "jobs", experiment_id),
                _fetch_rows(conn, "external_links", experiment_id),
            ),
        )
    if active_tab == "leases":
        return _tab_section("Advisory Leases", _lease_cards(_fetch_rows(conn, "leases", experiment_id)))
    if active_tab == "validations":
        return _tab_section("Validations", _validation_cards(_fetch_rows(conn, "validations", experiment_id)))
    if active_tab == "freshness":
        return _tab_section("Freshness", _freshness(exp))
    if active_tab == "notes":
        return _tab_section("Notes", _note_cards(_fetch_rows(conn, "notes", experiment_id)))
    if active_tab == "artifacts":
        return _tab_section("Artifacts", _artifact_cards(_fetch_rows(conn, "artifacts", experiment_id)))
    if active_tab == "external-links":
        return _tab_section("External Links", _links(_fetch_rows(conn, "external_links", experiment_id)))
    return (
        "<div class='tab-panel'>"
        + _section("Attention", _attention_cards(exp), section_id="attention")
        + _section("Agent Instructions", _prompt_cards(conn, experiment_id), section_id="agent-instructions")
        + "</div>"
    )


def _tab_section(title: str, body: str) -> str:
    return "<div class='tab-panel'>" + _section(title, body) + "</div>"


def _metric_cards(exp: dict[str, Any]) -> str:
    metrics = [
        ("Runs", exp["run_count"]),
        ("Jobs", exp["job_count"]),
        ("Blocking Failed", exp["blocking_failed_job_count"]),
        ("Recovering", exp["recovery_in_progress_failed_job_count"]),
        ("Recovered Failures", exp["recovered_failed_job_count"]),
        ("Active Jobs", exp["active_job_count"]),
        ("Failing validations", exp["failing_validation_count"]),
        ("Stale Leases", exp["stale_lease_count"]),
        ("Lifecycle", exp.get("lifecycle_state", "unknown")),
        ("Pending Review", exp.get("has_pending_review", 0)),
        ("Last Reviewed", exp.get("last_reviewed_at") or "never"),
        ("Reviewable Activity", exp.get("last_reviewable_activity_at") or "none"),
    ]
    return "<div class='metric-grid'>" + "".join(
        f"<div class='metric'><div class='metric-label'>{_esc(label)}</div><div class='metric-value'>{_esc(value)}</div></div>"
        for label, value in metrics
    ) + "</div>"


def _attention_cards(exp: dict[str, Any]) -> str:
    cards = []
    if exp["blocking_failed_job_count"]:
        cards.append(
            _attention_card("Blocking failed jobs", f"{exp['blocking_failed_job_count']} failed job(s) need retry/recovery.")
        )
    if exp["recovery_in_progress_failed_job_count"]:
        cards.append(
            _attention_card(
                "Recovery in progress",
                f"{exp['recovery_in_progress_failed_job_count']} failed job(s) have active retry descendants.",
            )
        )
    if exp["failing_validation_count"]:
        cards.append(_attention_card("Failing validations", f"{exp['failing_validation_count']} validation(s) are failing."))
    if exp["stale_submission_count"]:
        cards.append(
            _attention_card("Stale submissions", f"{exp['stale_submission_count']} submission(s) need external-state refresh.")
        )
    if exp["stale_lease_count"]:
        cards.append(_attention_card("Stale leases", f"{exp['stale_lease_count']} advisory lease(s) are stale."))
    if exp["handoff_status"] in {"missing", "stale"}:
        cards.append(_attention_card(f"Handoff {exp['handoff_status']}", "Write a bounded handoff note before context switching."))
    if not cards:
        return "<p class='muted'>(none)</p>"
    return "<div class='card-grid'>" + "".join(cards) + "</div>"


def _attention_card(title: str, body: str) -> str:
    return f"<article class='card attention'><div class='card-title'>{_esc(title)}</div><p>{_esc(body)}</p></article>"


def _prompt_cards(conn: sqlite3.Connection, experiment_id: str) -> str:
    actions = prompt_actions(conn, experiment_id)["actions"]
    if not actions:
        return "<p class='muted'>(none)</p>"
    cards = []
    skill_path = Path(__file__).resolve().parents[2] / ".codex" / "skills" / "fieldbook" / "SKILL.md"
    for action in actions:
        try:
            prompt = build_prompt(conn, action["action_id"], experiment_id, skill_path=skill_path)
            copy_target = f"prompt-copy-{_dom_id(action['action_id'])}"
            copy_button = (
                f"<button type='button' class='copy-button' data-copy-target='{_esc(copy_target)}'>"
                "Copy instruction</button>"
            )
            preview = (
                "<details><summary>Preview agent instruction</summary>"
                f"<pre id='{_esc(copy_target)}'>{_esc(prompt['body'])}</pre></details>"
            )
        except ValidationError as exc:
            copy_button = ""
            preview = f"<p class='muted'>Prompt blocked by safety check: {_esc(exc)}</p>"
        except Exception as exc:
            copy_button = ""
            preview = f"<p class='muted'>Prompt unavailable: {_esc(exc)}</p>"
        cards.append(
            "<article class='card prompt-card'>"
            "<div class='prompt-title-row'>"
            f"<div class='card-title'>{_esc(action['title'])}</div>"
            f"{copy_button}"
            "</div>"
            f"<p>{_esc(action['issue_summary'])}</p>"
            f"<p class='muted'>{_esc(action['constraints'][0])}</p>"
            f"{preview}"
            "</article>"
        )
    return "<div class='two-col'>" + "".join(cards) + "</div>"


def _run_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    cards = []
    for row in rows:
        phase = row.get("phase") or row.get("status") or "recorded"
        progress_parts = [
            f"phase={phase}",
            f"metrics={row.get('metric_count', 0)}",
            f"jobs={row.get('job_edge_count', 0)}",
        ]
        cards.append(
            "<div class='entity-row'>"
            f"<div><strong>{_esc(row.get('name') or row.get('run_id'))}</strong><br><code>{_esc(row.get('run_id'))}</code></div>"
            f"<div>{_status_chip(phase)}</div>"
            f"<div>kind={_esc(row.get('kind') or '')}<br>{_esc('; '.join(progress_parts))}</div>"
            f"<div class='muted'>checkpoint={_esc(row.get('has_checkpoint', 0))}<br>eval={_esc(row.get('has_eval_result', 0))}</div>"
            "</div>"
        )
    return "<div class='card'>" + "".join(cards) + "</div>"


def _job_cards(rows: list[dict[str, Any]], links: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    link_by_entity = {row["entity_id"]: row["url"] for row in links if row.get("entity_type") == "job"}
    cards = []
    for row in rows:
        recovery = _first_present(row, "recovery_state", "retry_of", "failure_reason", default="")
        link = link_by_entity.get(row.get("job_id"))
        link_html = f"<a href='{_esc(link)}'>external</a>" if link else ""
        cards.append(
            "<div class='entity-row'>"
            f"<div><strong>{_esc(row.get('name') or row.get('job_id'))}</strong><br><code>{_esc(row.get('job_id'))}</code></div>"
            f"<div>{_status_chip(row.get('status') or '')}</div>"
            f"<div>{_esc(recovery)}</div>"
            f"<div>{link_html}</div>"
            "</div>"
        )
    return "<div class='card'>" + "".join(cards) + "</div>"


def _lease_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    cards = []
    for row in rows:
        state = "released" if row.get("released_at") else "active"
        if not row.get("released_at") and _is_stale_heartbeat(row.get("heartbeat_at")):
            state = "stale"
        cards.append(
            "<div class='entity-row'>"
            f"<div><strong>{_esc(row.get('entity_type'))}</strong><br><code>{_esc(row.get('lease_id'))}</code></div>"
            f"<div>{_status_chip(state)}</div>"
            f"<div>target=<code>{_esc(row.get('entity_id'))}</code><br>owner={_esc(row.get('owner_agent'))}</div>"
            f"<div class='muted'>heartbeat={_esc(row.get('heartbeat_at') or '')}</div>"
            "</div>"
        )
    return "<div class='card'>" + "".join(cards) + "</div>"


def _is_stale_heartbeat(value: Any, *, threshold_hours: float = 1.0) -> bool:
    if value is None:
        return False
    try:
        heartbeat = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return heartbeat < datetime.now(UTC) - timedelta(hours=threshold_hours)


def _validation_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    cards = []
    for row in rows:
        cards.append(
            "<div class='entity-row'>"
            f"<div><strong>{_esc(row.get('check_name'))}</strong><br><code>{_esc(row.get('validation_id'))}</code></div>"
            f"<div>{_status_chip(row.get('status') or '')}</div>"
            f"<div>measured={_esc(row.get('measured_value') or '')}<br>expected={_esc(row.get('expected_value') or '')}</div>"
            f"<div class='muted'>{_esc(row.get('updated_at') or '')}</div>"
            "</div>"
        )
    return "<div class='card'>" + "".join(cards) + "</div>"


def _note_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    cards = []
    for row in rows:
        preview = str(row.get("body_preview") or "").replace("\n", " ")[:220]
        cards.append(
            "<article class='card'>"
            f"<div class='card-title'>{_esc(row.get('title') or row.get('note_id'))}</div>"
            f"<div class='pill-row'>{_pill('type', row.get('note_type'))}{_pill('status', row.get('status'))}</div>"
            f"<p class='text-clamp'>{_esc(preview)}</p><code>{_esc(row.get('note_id'))}</code>"
            "</article>"
        )
    return "<div class='card-grid'>" + "".join(cards) + "</div>"


def _artifact_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    cards = []
    for row in rows:
        cards.append(
            "<div class='entity-row'>"
            f"<div><strong>{_esc(row.get('artifact_type'))}</strong><br><code>{_esc(row.get('artifact_id'))}</code></div>"
            f"<div>{_pill('system', row.get('external_system') or 'local')}</div>"
            f"<div>{_artifact_uri(row.get('uri'))}</div>"
            f"<div class='muted'>{_esc(row.get('updated_at') or '')}</div>"
            "</div>"
        )
    return "<div class='card'>" + "".join(cards) + "</div>"


def _table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    columns = list(rows[0].keys())[:10]
    header = "".join(f"<th>{_esc(column)}</th>" for column in columns)
    body = []
    for row in rows[:25]:
        body.append("<tr>" + "".join(f"<td>{_esc(row.get(column))}</td>" for column in columns) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _status_chip(status: Any) -> str:
    text = str(status or "unknown")
    css = text.lower().replace("_", "-")
    return f"<span class='status-chip { _esc(css) }'>{_esc(text)}</span>"


def _pill(label: str, value: Any) -> str:
    return f"<span class='pill'><span class='muted'>{_esc(label)}</span> {_esc(value)}</span>"


def _first_present(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _artifact_uri(value: Any) -> str:
    uri = str(value or "")
    if uri.startswith("http"):
        return f"<a class='path-text' href='{_esc(uri)}'>{_esc(uri)}</a>"
    return f"<span class='path-text'>{_esc(uri)}</span>"


def _links(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='muted'>(none)</p>"
    items = []
    for row in rows:
        url = str(row["url"])
        items.append(
            "<div class='card'>"
            f"<strong>{_esc(row['external_system'] or row['entity_type'])}</strong> "
            f"<code>{_esc(row['entity_id'])}</code><br>"
            f"<a href='{_esc(url)}'>{_esc(url)}</a>"
            "</div>"
        )
    return "<div class='external-list'>" + "".join(items) + "</div>"


def _freshness(row: dict[str, Any]) -> str:
    handoff = row["last_handoff_at"] or "missing"
    status = row.get("handoff_status") or "unknown"
    return f"<p>Last handoff: <code>{_esc(handoff)}</code></p><p>Handoff status: <code>{_esc(status)}</code></p>"


def _command(command: str) -> str:
    return f"<code class='command'>{_esc(command)}</code>"


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def _dom_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-")


def _send(handler: BaseHTTPRequestHandler, status: int, body: str, *, content_type: str = "text/html; charset=utf-8") -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
