import os
import tempfile

os.environ.setdefault("HUB_DATA_DIR", tempfile.mkdtemp())

import pytest  # noqa: E402

from app import kube  # noqa: E402
from app import servers as S  # noqa: E402
from app.db import Server, Service  # noqa: E402


def test_validate_rejects_shell_injection():
    for bad in ("nginx; rm -rf /", "$(id)", "a b", "x`whoami`"):
        with pytest.raises(S.ServerError):
            S.validate_service("systemd", {"unit": bad}, {})
    with pytest.raises(S.ServerError):
        S.validate_service("log", {}, {"type": "file", "path": "/var/log/../../etc/shadow"})
    with pytest.raises(S.ServerError):
        S.validate_service("log", {}, {"type": "file", "path": "/var/log/x.log; cat /etc/passwd"})
    cfg, lg = S.validate_service("systemd", {"unit": "puma_app"}, {"type": "journal"})
    assert cfg == {"unit": "puma_app"} and lg == {"type": "journal", "unit": "puma_app"}


def test_parse_metrics():
    out = """@@load@@
0.68 0.40 0.38 1/300 123
@@cpu@@
cpu  100 0 100 800 0 0 0 0 0 0
cpu  150 0 150 900 0 0 0 0 0 0
@@mem@@
MemTotal:        4000 kB
MemAvailable:    1000 kB
SwapTotal:       2000 kB
SwapFree:        1500 kB
@@disk@@
Filesystem 1-blocks Used Available Capacity Mounted on
/dev/vda1 1000 600 400 60% /
@@uptime@@
3600.5 7000.1
@@nproc@@
2
"""
    m = S.parse_metrics(out)
    assert m["cpu_pct"] == 50.0 and m["load1"] == 0.68 and m["cores"] == 2
    assert m["mem_total"] == 4000 * 1024 and m["mem_used"] == 3000 * 1024
    assert m["swap_used"] == 500 * 1024
    assert (m["disk_total"], m["disk_used"], m["uptime_s"]) == (1000, 600, 3600)


def test_ports_exposure_and_ufw():
    out = """@@ports@@
tcp   LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1,fd=6))
tcp   LISTEN 0 511 0.0.0.0:9080 0.0.0.0:* users:(("promtail",pid=2,fd=6))
tcp   LISTEN 0 200 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=3,fd=6))
tcp   LISTEN 0 200 100.64.0.10:58086 0.0.0.0:* users:(("tailscaled",pid=4,fd=6))
@@ufw@@
Status: active
22/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
"""
    snap = S.parse_snapshot(out)
    by = {p["port"]: p for p in snap["ports"]}
    assert by["443"]["internet"] and by["443"]["process"] == "nginx"
    assert not by["9080"]["internet"]  # escucha en todas, pero ufw lo filtra
    assert by["5432"]["exposure"] == "local" and by["58086"]["exposure"] == "tailscale"


def test_docker_proxy_bypasses_ufw():
    out = """@@ports@@
tcp   LISTEN 0 4096 0.0.0.0:3100 0.0.0.0:* users:(("docker-proxy",pid=9,fd=4))
@@ufw@@
Status: active
22/tcp                     ALLOW IN    Anywhere
"""
    assert S.parse_snapshot(out)["ports"][0]["internet"]


def _svc(kind, cfg=None):
    import json

    return Service(id=1, name="x", kind=kind, config_json=json.dumps(cfg or {}), log_json="{}")


def test_sidekiq_interpretation():
    out = """@@ping@@
PONG
@@queues@@
default 3
mailers 0
@@sets@@
retry 7
dead 2
schedule 1
@@stats@@
processed 1000
failed 9
@@procs@@
host:123:abc 4
"""
    status, summary, d = S.interpret(_svc("sidekiq"), {}, out)
    assert status == "ok" and d["enqueued"] == 3 and d["busy"] == 4 and d["retry"] == 7
    assert "7 reintentos" in summary


def test_redis_password_goes_by_env_not_argv():
    srv = Server(id=1, name="s", host="h", username="u", use_sudo=False)
    script = S.check_script(srv, _svc("redis"), {"host": "127.0.0.1", "port": 6379, "db": 0},
                            "s3cr3t")
    first, rest = script.split("\n", 1)
    assert first == "export REDISCLI_AUTH=s3cr3t" and "s3cr3t" not in rest


def test_systemd_down():
    out = "@@unit@@\nActiveState=failed\nSubState=failed\nResult=exit-code\nLoadState=loaded\n"
    status, summary, _ = S.interpret(_svc("systemd", {"unit": "x"}), {"unit": "x"}, out)
    assert status == "down" and "failed" in summary


def test_k8s_pod_problem_rules():
    meta = {"name": "p", "namespace": "n", "creationTimestamp": "2026-01-01T00:00:00Z"}
    base = {"metadata": meta, "spec": {"containers": [{"name": "c"}]}}
    crash = {**base, "status": {"phase": "Running", "containerStatuses": [
        {"ready": False, "restartCount": 5,
         "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}
    assert kube.pod_summary(crash)["problem"] and kube.pod_summary(crash)["reason"] == \
        "CrashLoopBackOff"
    job_failed = {**base, "metadata": {**base["metadata"], "ownerReferences": [{"kind": "Job"}]},
                  "status": {"phase": "Failed", "containerStatuses": []}}
    assert not kube.pod_summary(job_failed)["problem"]  # lo reporta el cronjob, no el pod
    assert kube.parse_cpu("250m") == 0.25 and kube.parse_mem("512Mi") == 512 * 1024**2


def test_secrets_are_redacted():
    obj = kube._clean({"kind": "Secret", "metadata": {"name": "s"},
                       "data": {"DATABASE_URL": "cG9zdGdyZXM6Ly8="}})
    assert obj["data"] == {"DATABASE_URL": "<oculto>"}
