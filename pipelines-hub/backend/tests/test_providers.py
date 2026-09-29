import os
import tempfile

os.environ.setdefault("HUB_DATA_DIR", tempfile.mkdtemp())

import httpx  # noqa: E402
import respx  # noqa: E402

from app.providers.base import parse_dt  # noqa: E402
from app.providers.bitbucket import BitbucketProvider, map_state  # noqa: E402
from app.providers.github import GitHubProvider, map_status  # noqa: E402
from app.sync import matches_filter  # noqa: E402


def test_parse_dt_nanoseconds_and_z():
    dt = parse_dt("2025-06-16T06:54:46.790381774Z")
    assert dt.microsecond == 790381 and dt.utcoffset().total_seconds() == 0
    assert parse_dt("2026-09-28T22:12:33Z").hour == 22
    assert parse_dt(None) is None


def test_github_status_mapping():
    assert map_status("completed", "success") == "success"
    assert map_status("completed", "timed_out") == "failed"
    assert map_status("completed", "cancelled") == "cancelled"
    assert map_status("in_progress", None) == "running"
    assert map_status("waiting", None) == "waiting"
    assert map_status("queued", None) == "queued"


def test_bitbucket_state_mapping():
    assert map_state({"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}})[0] == "success"
    assert map_state({"name": "COMPLETED", "result": {"name": "STOPPED"}})[0] == "cancelled"
    assert map_state({"name": "COMPLETED", "result": {"name": "NOT_RUN"}})[0] == "skipped"
    assert map_state({"name": "IN_PROGRESS", "stage": {"name": "PAUSED"}})[0] == "waiting"
    assert map_state({"name": "IN_PROGRESS", "stage": {"name": "RUNNING"}})[0] == "running"
    assert map_state({"name": "PENDING"})[0] == "queued"


def test_repo_filter():
    assert matches_filter("contable-back", "tachyonichq/contable-back", None)
    assert matches_filter("contable-back", "x/contable-back", "contable-*")
    assert not matches_filter("contable-legacy", "x/contable-legacy", "contable-*, !*-legacy")
    assert not matches_filter("other", "x/other", "contable-*")
    assert not matches_filter("old-legacy", "x/old-legacy", "!*-legacy")


@respx.mock
async def test_bitbucket_log_does_not_split_utf8():
    text = "línea con ñ\n".encode()
    cut = text[: text.index("ñ".encode()) + 1]  # corta el ñ a la mitad
    respx.get(url__regex=r".*/log$").mock(return_value=httpx.Response(206, content=cut))
    p = BitbucketProvider("t", username="a@b.c")
    chunk = await p.get_log("ws/repo", "{p}", "{s}", 0)
    assert chunk.text == "línea con "
    assert chunk.next_offset == len(cut) - 1
    await p.aclose()


@respx.mock
async def test_bitbucket_log_range_not_satisfiable_means_no_news():
    respx.get(url__regex=r".*/log$").mock(return_value=httpx.Response(416))
    p = BitbucketProvider("t", username="a@b.c")
    chunk = await p.get_log("ws/repo", "p", "s", 120)
    assert chunk.text == "" and chunk.next_offset == 120 and chunk.available
    await p.aclose()


@respx.mock
async def test_bitbucket_run_parsing():
    respx.get(url__regex=r".*/pipelines/(\?.*)?$").mock(return_value=httpx.Response(200, json={
        "values": [{
            "uuid": "{abc}", "build_number": 7, "run_number": 2,
            "state": {"name": "COMPLETED", "result": {"name": "FAILED"}},
            "created_on": "2026-09-29T10:00:00.123456789Z",
            "completed_on": "2026-09-29T10:05:00Z", "duration_in_seconds": 300,
            "creator": {"display_name": "Felipe", "links": {"avatar": {"href": "http://a"}}},
            "target": {"type": "pipeline_ref_target", "ref_name": "master",
                       "selector": {"type": "custom", "pattern": "deploy-prod"},
                       "commit": {"hash": "deadbeef", "message": "fix: algo\n\ndetalle"}},
            "trigger": {"name": "MANUAL"},
        }]
    }))
    p = BitbucketProvider("t", username="a@b.c")
    runs, _ = await p.list_runs("ws/repo")
    r = runs[0]
    assert (r.status, r.number, r.attempt, r.branch) == ("failed", 7, 2, "master")
    assert r.workflow == "custom: deploy-prod" and r.title == "fix: algo"
    assert r.event == "manual" and r.url.endswith("/ws/repo/pipelines/results/7")
    await p.aclose()


@respx.mock
async def test_github_runs_etag_not_modified():
    route = respx.get("https://api.github.com/repos/o/r/actions/runs").mock(
        return_value=httpx.Response(304)
    )
    p = GitHubProvider("t")
    runs, etag = await p.list_runs("o/r", etag='W/"x"')
    assert runs is None and etag == 'W/"x"'
    assert route.calls[0].request.headers["If-None-Match"] == 'W/"x"'
    await p.aclose()


def test_github_reviewers_last_state_wins_and_rerequest_is_pending():
    from app.providers.base import Reviewer
    from app.providers.github import merge_reviewers

    def rv(login, state, day):
        return {"user": {"login": login}, "state": state, "submitted_at": f"2026-01-0{day}T10:00Z"}

    reviews = [
        rv("Ana", "CHANGES_REQUESTED", 1),
        rv("Ana", "APPROVED", 2),
        rv("Ana", "COMMENTED", 3),
        rv("Beto", "APPROVED", 1),
        rv("autor", "COMMENTED", 1),
    ]
    requested = [Reviewer("beto", "Beto", None, "pending"),
                 Reviewer("caro", "Caro", None, "pending")]
    got = {r.id: r.state for r in merge_reviewers(requested, reviews, "autor")}
    assert got == {"ana": "approved", "beto": "pending", "caro": "pending"}


def test_split_diff_by_file():
    from app.providers.bitbucket import split_diff

    raw = (
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/old.txt b/new.txt\nsimilarity index 90%\nrename from old.txt\n"
        "rename to new.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
    )
    parts = split_diff(raw)
    assert parts["a.py"] == "@@ -1 +1 @@\n-x\n+y"
    assert parts["new.txt"].startswith("@@ -1,2 +1,2 @@")


def test_bitbucket_pr_reviewer_states():
    from app.providers.bitbucket import _pr

    pr = _pr("ws/r", {
        "id": 3, "title": "t", "state": "OPEN", "created_on": "2026-09-01T00:00:00Z",
        "updated_on": "2026-09-02T00:00:00Z",
        "author": {"display_name": "Yo", "account_id": "me"},
        "source": {"branch": {"name": "feat"}, "commit": {"hash": "abc123def456"}},
        "destination": {"branch": {"name": "master"}},
        "participants": [
            {"role": "REVIEWER", "approved": True, "user": {"account_id": "a"}},
            {"role": "REVIEWER", "approved": False, "state": "changes_requested",
             "user": {"account_id": "b"}},
            {"role": "REVIEWER", "approved": False, "user": {"account_id": "c"}},
            {"role": "PARTICIPANT", "approved": False, "user": {"account_id": "d"}},
        ],
    })
    assert pr.author_id == "me" and pr.state == "open" and pr.head_sha == "abc123def456"
    assert [(r.id, r.state) for r in pr.reviewers] == [
        ("a", "approved"), ("b", "changes_requested"), ("c", "pending")
    ]
    assert pr.url.endswith("/ws/r/pull-requests/3")
