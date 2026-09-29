import os
import tempfile

os.environ.setdefault("HUB_DATA_DIR", tempfile.mkdtemp())

import httpx  # noqa: E402
import respx  # noqa: E402

from app.providers.cloudflare import CloudflareProvider  # noqa: E402

API = "https://api.cloudflare.com/client/v4"
ACC = "a" * 32


def ok(result, info=None):
    body = {"success": True, "errors": [], "result": result}
    if info:
        body["result_info"] = info
    return httpx.Response(200, json=body)


def mock_account(router):
    router.get(f"{API}/accounts").mock(return_value=ok(
        [{"id": ACC, "name": "Altech Mundial"}], {"page": 1, "total_pages": 1}))
    router.get(f"{API}/accounts/{ACC}/workers/scripts").mock(return_value=ok([
        {"id": "contable-front", "tag": "tag1", "modified_on": "2026-09-29T10:00:00Z"},
    ]))
    router.get(f"{API}/accounts/{ACC}/pages/projects").mock(return_value=ok([
        {"name": "landing", "subdomain": "landing.pages.dev", "production_branch": "main",
         "source": {"type": "github", "config": {"owner": "fvegah", "repo_name": "landing"}},
         "latest_deployment": {"created_on": "2026-09-28T10:00:00Z"}},
    ], {"page": 1, "total_pages": 1}))


@respx.mock
async def test_repos_from_workers_and_pages():
    mock_account(respx)
    p = CloudflareProvider("t")
    srcs = await p.discover_sources()
    assert [(s.kind, s.slug, s.name) for s in srcs] == [("account", "altech-mundial",
                                                         "Altech Mundial")]
    repos, _ = await p.list_repos("account", "altech-mundial")
    by = {r.full_name: r for r in repos}
    assert by["altech-mundial/contable-front"].html_url.endswith(
        "/workers/services/view/contable-front/production")
    assert by["altech-mundial/landing"].git_url == "https://github.com/fvegah/landing"
    await p.aclose()


@respx.mock
async def test_worker_builds_map_to_runs_and_learn_git_repo():
    mock_account(respx)
    respx.get(f"{API}/accounts/{ACC}/builds/workers/tag1/builds").mock(return_value=ok([
        {"build_uuid": "b1", "status": "stopped", "build_outcome": "fail",
         "created_on": "2026-09-29T10:00:00Z", "running_on": "2026-09-29T10:00:10Z",
         "stopped_on": "2026-09-29T10:02:10Z",
         "trigger": {"trigger_name": "Deploy default branch", "trigger_uuid": "t1"},
         "build_trigger_metadata": {"branch": "main", "commit_hash": "abc123",
                                    "commit_message": "fix: algo\n\ncuerpo", "author": "felipe",
                                    "provider_type": "github",
                                    "provider_account_name": "tachyonichq",
                                    "repo_name": "contable-front",
                                    "build_trigger_source": "push"}},
        {"build_uuid": "b2", "status": "running", "created_on": "2026-09-29T11:00:00Z",
         "build_trigger_metadata": {"branch": "feat"}},
    ]))
    p = CloudflareProvider("t")
    await p.list_repos("account", "altech-mundial")
    runs, _ = await p.list_runs("altech-mundial/contable-front")
    assert [(r.status, r.branch, r.duration_s) for r in runs] == [
        ("failed", "main", 120), ("running", "feat", None)]
    assert runs[0].title == "fix: algo" and runs[0].event == "push"
    repos, _ = await p.list_repos("account", "altech-mundial")
    front = next(r for r in repos if r.name == "contable-front")
    assert front.git_url == "https://github.com/tachyonichq/contable-front"
    await p.aclose()


@respx.mock
async def test_build_logs_follow_cursor_and_offset():
    mock_account(respx)
    route = respx.get(f"{API}/accounts/{ACC}/builds/builds/b1/logs")
    route.side_effect = [
        ok({"lines": [[1759140000000, "npm ci"]], "cursor": "c2", "truncated": True}),
        ok({"lines": [[1759140001000, "listo"]], "cursor": None, "truncated": False}),
    ]
    p = CloudflareProvider("t")
    await p.list_repos("account", "altech-mundial")
    chunk = await p.get_log("altech-mundial/contable-front", "b1", "b1", 0)
    assert chunk.text.splitlines()[0].endswith("Z npm ci")
    assert chunk.text.splitlines()[1].endswith("Z listo")
    assert route.calls[1].request.url.params["cursor"] == "c2"
    await p.aclose()


def test_pages_status_by_stage():
    s = CloudflareProvider._pages_status
    assert s({"latest_stage": {"name": "deploy", "status": "success"}}) == "success"
    assert s({"latest_stage": {"name": "build", "status": "success"}}) == "running"
    assert s({"latest_stage": {"name": "build", "status": "failure"}}) == "failed"
    assert s({"latest_stage": {"name": "queued", "status": "active"}}) == "queued"
    assert s({"is_skipped": True, "latest_stage": {}}) == "skipped"
