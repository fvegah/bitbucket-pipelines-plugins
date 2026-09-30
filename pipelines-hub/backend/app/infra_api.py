"""API de infraestructura: visor de Kubernetes y monitoreo de servidores."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import kube
from app import servers as srv
from app.crypto import encrypt
from app.db import KubeCluster, Server, ServerSample, Service, ServiceCheck, SessionLocal, utcnow
from app.service import iso

router = APIRouter(prefix="/api")


def _kerr(e: Exception) -> HTTPException:
    if isinstance(e, kube.KubeError):
        return HTTPException(e.status_code if 400 <= e.status_code < 600 else 502, e.message)
    if isinstance(e, srv.ServerError):
        return HTTPException(e.status_code, e.message)
    return HTTPException(500, str(e))


# ============================ Kubernetes ============================
class ClusterIn(BaseModel):
    context: str
    name: str | None = None


async def _context(cluster_id: int) -> str:
    async with SessionLocal() as s:
        c = await s.get(KubeCluster, cluster_id)
        if not c:
            raise HTTPException(404, "Cluster no encontrado")
        return c.context


@router.get("/k8s/contexts")
async def k8s_contexts():
    try:
        ctxs = kube.list_contexts()
    except kube.KubeError as e:
        return {"available": False, "message": e.message, "contexts": []}
    async with SessionLocal() as s:
        added = set((await s.execute(select(KubeCluster.context))).scalars())
    return {"available": True, "path": str(kube.kubeconfig_path()),
            "contexts": [{**c, "added": c["name"] in added} for c in ctxs]}


@router.get("/k8s/clusters")
async def k8s_clusters():
    async with SessionLocal() as s:
        rows = (await s.execute(select(KubeCluster).order_by(KubeCluster.id))).scalars()
        return [{"id": c.id, "name": c.name, "context": c.context} for c in rows]


@router.post("/k8s/clusters", status_code=201)
async def k8s_add_cluster(body: ClusterIn):
    ctxs = {c["name"] for c in kube.list_contexts()}
    if body.context not in ctxs:
        raise HTTPException(404, "Ese contexto no está en el kubeconfig")
    try:
        await kube.client_for(body.context).get("/version")
    except kube.KubeError as e:
        raise _kerr(e) from e
    name = body.name or body.context.split("/")[-1]
    async with SessionLocal() as s:
        c = KubeCluster(name=name, context=body.context)
        s.add(c)
        try:
            await s.commit()
        except IntegrityError as e:
            raise HTTPException(409, "Ese contexto ya está agregado") from e
        return {"id": c.id, "name": c.name, "context": c.context}


@router.delete("/k8s/clusters/{cluster_id}", status_code=204)
async def k8s_remove_cluster(cluster_id: int):
    async with SessionLocal() as s:
        c = await s.get(KubeCluster, cluster_id)
        if c:
            await s.delete(c)
            await s.commit()


async def _k(fn, cluster_id: int, *args, **kw):
    ctx = await _context(cluster_id)
    try:
        return await fn(ctx, *args, **kw)
    except kube.KubeError as e:
        raise _kerr(e) from e


@router.get("/k8s/{cluster_id}/overview")
async def k8s_overview(cluster_id: int):
    return await _k(kube.overview, cluster_id)


@router.get("/k8s/{cluster_id}/pods")
async def k8s_pods(cluster_id: int, namespace: str | None = None):
    return await _k(kube.pods, cluster_id, namespace or None)


@router.get("/k8s/{cluster_id}/workloads/{kind}")
async def k8s_workloads(cluster_id: int, kind: str, namespace: str | None = None):
    return await _k(kube.workloads, cluster_id, kind, namespace or None)


@router.get("/k8s/{cluster_id}/network")
async def k8s_network(cluster_id: int, namespace: str | None = None):
    return await _k(kube.network, cluster_id, namespace or None)


@router.get("/k8s/{cluster_id}/config")
async def k8s_config(cluster_id: int, namespace: str | None = None):
    return await _k(kube.config_objects, cluster_id, namespace or None)


@router.get("/k8s/{cluster_id}/nodes")
async def k8s_nodes(cluster_id: int):
    return await _k(kube.nodes, cluster_id)


@router.get("/k8s/{cluster_id}/events")
async def k8s_events(cluster_id: int, namespace: str | None = None, warnings: bool = False):
    return await _k(kube.events, cluster_id, namespace or None, warnings)


@router.get("/k8s/{cluster_id}/resource/{kind}/{namespace}/{name}")
async def k8s_resource(cluster_id: int, kind: str, namespace: str, name: str):
    return await _k(kube.resource, cluster_id, kind, None if namespace == "_" else namespace,
                    name)


@router.get("/k8s/{cluster_id}/log/{namespace}/{pod}")
async def k8s_log(cluster_id: int, namespace: str, pod: str, container: str | None = None,
                  previous: bool = False, tail: int = 2000, since: str | None = None):
    text = await _k(kube.pod_log, cluster_id, namespace, pod, container, previous, tail, since)
    # el cursor es la marca de tiempo de la última línea (el log trae --timestamps)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    last = lines[-1].split(" ", 1)[0] if lines else since
    if since and lines and lines[0].startswith(since):
        lines = lines[1:]  # sinceTime es inclusivo: no repetir la última línea
    body = "\n".join(lines)
    return {"text": body + ("\n" if body else ""), "cursor": last, "append": bool(since),
            "available": True}


# ============================ Servidores ============================
class ServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=300)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=100)
    key_path: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    use_sudo: bool = True
    environment: str | None = None


class ServerPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    key_path: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    use_sudo: bool | None = None
    environment: str | None = None
    reset_host_key: bool = False


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["systemd", "docker", "redis", "postgres", "sidekiq", "rabbitmq", "http", "tcp",
                  "process", "log"]
    platform: str | None = None
    config: dict = Field(default_factory=dict)
    log: dict = Field(default_factory=dict)
    password: str | None = None


class ServicePatch(BaseModel):
    name: str | None = None
    platform: str | None = None
    config: dict | None = None
    log: dict | None = None
    password: str | None = None


def _sample_dict(x: ServerSample | None) -> dict | None:
    if not x:
        return None
    return {"ts": iso(x.ts), "cpu_pct": x.cpu_pct, "load1": x.load1, "cores": x.cores,
            "mem_total": x.mem_total, "mem_used": x.mem_used, "swap_total": x.swap_total,
            "swap_used": x.swap_used, "disk_total": x.disk_total, "disk_used": x.disk_used,
            "uptime_s": x.uptime_s, "disks": json.loads(x.disks_json or "[]")}


def _service_dict(v: Service) -> dict:
    return {"id": v.id, "server_id": v.server_id, "name": v.name, "kind": v.kind,
            "platform": v.platform, "config": json.loads(v.config_json or "{}"),
            "log": json.loads(v.log_json or "{}"), "has_password": bool(v.secret_enc),
            "status": v.status, "summary": v.summary,
            "detail": json.loads(v.detail_json or "{}"), "checked_at": iso(v.checked_at),
            "changed_at": iso(v.changed_at)}


async def _server_dict(s, x: Server, with_services: bool = True) -> dict:
    last = (await s.execute(select(ServerSample).where(ServerSample.server_id == x.id)
                            .order_by(ServerSample.ts.desc()).limit(1))).scalar()
    snap = json.loads(x.snapshot_json) if x.snapshot_json else None
    out = {"id": x.id, "name": x.name, "host": x.host, "port": x.port, "username": x.username,
           "key_path": x.key_path, "has_private_key": bool(x.key_enc),
           "use_sudo": x.use_sudo, "environment": x.environment, "host_key": x.host_key,
           "status": x.status, "last_error": x.last_error, "last_seen_at": iso(x.last_seen_at),
           "snapshot_at": iso(x.snapshot_at), "sample": _sample_dict(last),
           "flags": {
               "reboot_required": (snap or {}).get("reboot_required"),
               "updates": (snap or {}).get("updates"),
               "ssh_failed_24h": (snap or {}).get("ssh_failed_24h"),
               "os": (snap or {}).get("os"),
               "internet_ports": [p["port"] for p in (snap or {}).get("ports", [])
                                  if p.get("internet")],
           }}
    if with_services:
        out["services"] = [_service_dict(v) for v in sorted(x.services, key=lambda v: v.name)]
    return out


async def _load_server(s, server_id: int) -> Server:
    x = await s.get(Server, server_id, options=[selectinload(Server.services)])
    if not x:
        raise HTTPException(404, "Servidor no encontrado")
    return x


@router.get("/servers/ssh-config")
async def ssh_config():
    return {"aliases": srv.ssh_aliases(), "keys": srv.ssh_keys(), "dir": str(srv.ssh_dir())}


@router.post("/servers/test")
async def test_server(body: ServerIn):
    probe = _new_server(body)
    try:
        conn, fp = await srv.connect_raw(probe.host, probe.port, probe.username,
                                         srv._client_key(probe), None)
        r = await conn.run("hostname; whoami; sudo -n true 2>/dev/null && echo sudo-ok || "
                           "echo sudo-no", check=False)
        conn.close()
    except srv.ServerError as e:
        raise _kerr(e) from e
    lines = (r.stdout or "").split()
    return {"hostname": lines[0] if lines else None, "user": lines[1] if len(lines) > 1 else None,
            "sudo": "sudo-ok" in (r.stdout or ""), "host_key": fp}


def _new_server(body: ServerIn) -> Server:
    if not body.key_path and not body.private_key:
        raise HTTPException(422, "Elige una llave de ~/.ssh o pega una llave privada")
    return Server(
        name=body.name.strip(), host=body.host.strip(), port=body.port,
        username=body.username.strip(),
        key_path=None if body.private_key else body.key_path,
        key_enc=encrypt(body.private_key.strip() + "\n") if body.private_key else None,
        passphrase_enc=encrypt(body.passphrase) if body.passphrase else None,
        use_sudo=body.use_sudo, environment=(body.environment or "").strip() or None,
    )


@router.get("/servers")
async def list_servers():
    async with SessionLocal() as s:
        rows = (await s.execute(select(Server).options(selectinload(Server.services))
                                .order_by(Server.name))).scalars().all()
        return [await _server_dict(s, x) for x in rows]


@router.post("/servers", status_code=201)
async def create_server(body: ServerIn):
    x = _new_server(body)
    try:
        conn, fp = await srv.connect_raw(x.host, x.port, x.username, srv._client_key(x), None)
        conn.close()
    except srv.ServerError as e:
        raise _kerr(e) from e
    x.host_key = fp
    async with SessionLocal() as s:
        s.add(x)
        try:
            await s.commit()
        except IntegrityError as e:
            raise HTTPException(409, "Ya hay un servidor con ese nombre") from e
        sid = x.id
    srv.poller.wake()
    await refresh_snapshot(sid)
    async with SessionLocal() as s:
        return await _server_dict(s, await _load_server(s, sid))


@router.patch("/servers/{server_id}")
async def update_server(server_id: int, body: ServerPatch):
    async with SessionLocal() as s:
        x = await _load_server(s, server_id)
        data = body.model_dump(exclude_unset=True)
        for f in ("name", "host", "port", "username", "use_sudo", "environment"):
            if f in data and data[f] is not None:
                setattr(x, f, data[f].strip() if isinstance(data[f], str) else data[f])
        if data.get("private_key"):
            x.key_enc, x.key_path = encrypt(data["private_key"].strip() + "\n"), None
        elif data.get("key_path"):
            x.key_path, x.key_enc = data["key_path"], None
        if data.get("passphrase"):
            x.passphrase_enc = encrypt(data["passphrase"])
        if body.reset_host_key or "host" in data or "port" in data:
            x.host_key = None
        await s.commit()
        await srv.drop(server_id)
    srv.poller.wake()
    async with SessionLocal() as s:
        return await _server_dict(s, await _load_server(s, server_id))


@router.delete("/servers/{server_id}", status_code=204)
async def delete_server(server_id: int):
    async with SessionLocal() as s:
        x = await s.get(Server, server_id)
        if x:
            await s.delete(x)
            await s.commit()
    await srv.drop(server_id)


@router.get("/servers/{server_id}")
async def get_server(server_id: int):
    async with SessionLocal() as s:
        x = await _load_server(s, server_id)
        out = await _server_dict(s, x)
        out["snapshot"] = json.loads(x.snapshot_json) if x.snapshot_json else None
        return out


async def refresh_snapshot(server_id: int) -> dict:
    async with SessionLocal() as s:
        x = await _load_server(s, server_id)
        try:
            out = await srv.run(x, srv.snapshot_script(x), timeout=90)
        except srv.ServerError as e:
            x.status, x.last_error = "error", e.message
            await s.commit()
            raise _kerr(e) from e
        vantage = (await s.execute(select(Server).where(
            Server.id != x.id, Server.status == "ok").order_by(Server.id).limit(1))).scalar()
        snap = await srv.verify_exposure(srv.parse_snapshot(out), vantage)
        x.snapshot_json, x.snapshot_at = json.dumps(snap), utcnow()
        await s.commit()
        return snap


@router.post("/servers/{server_id}/snapshot")
async def snapshot(server_id: int):
    return await refresh_snapshot(server_id)


@router.post("/servers/{server_id}/poll")
async def poll_now(server_id: int):
    await srv.poller.poll_server(server_id)
    return await get_server(server_id)


@router.get("/servers/{server_id}/samples")
async def samples(server_id: int, hours: int = 24):
    since = utcnow() - timedelta(hours=min(max(hours, 1), 24 * 7))
    async with SessionLocal() as s:
        rows = (await s.execute(select(ServerSample).where(
            ServerSample.server_id == server_id, ServerSample.ts >= since)
            .order_by(ServerSample.ts))).scalars().all()
    step = max(1, len(rows) // 400)  # como mucho ~400 puntos por gráfico
    return [{k: v for k, v in _sample_dict(r).items() if k != "disks"} for r in rows[::step]]


@router.get("/servers/{server_id}/suggestions")
async def server_suggestions(server_id: int):
    async with SessionLocal() as s:
        x = await _load_server(s, server_id)
        snap = json.loads(x.snapshot_json) if x.snapshot_json else None
    if not snap:
        snap = await refresh_snapshot(server_id)
        async with SessionLocal() as s:
            x = await _load_server(s, server_id)
    return srv.suggestions(snap, x.services)


@router.post("/servers/{server_id}/services", status_code=201)
async def add_service(server_id: int, body: ServiceIn):
    try:
        cfg, lg = srv.validate_service(body.kind, body.config, body.log)
    except srv.ServerError as e:
        raise _kerr(e) from e
    async with SessionLocal() as s:
        x = await _load_server(s, server_id)
        v = Service(server_id=x.id, name=body.name.strip(), kind=body.kind,
                    platform=(body.platform or "").strip() or None,
                    config_json=json.dumps(cfg), log_json=json.dumps(lg),
                    secret_enc=encrypt(body.password) if body.password else None)
        s.add(v)
        await s.commit()
        try:
            status, summary, detail, latency = await srv.check_service(x, v)
            srv.poller._record(s, v, status, summary, detail, latency, utcnow())
            await s.commit()
        except srv.ServerError as e:
            v.status, v.summary = "unknown", e.message
            await s.commit()
        return _service_dict(v)


@router.patch("/services/{service_id}")
async def update_service(service_id: int, body: ServicePatch):
    async with SessionLocal() as s:
        v = await s.get(Service, service_id)
        if not v:
            raise HTTPException(404, "Servicio no encontrado")
        cfg = body.config if body.config is not None else json.loads(v.config_json or "{}")
        lg = body.log if body.log is not None else json.loads(v.log_json or "{}")
        try:
            cfg, lg = srv.validate_service(v.kind, cfg, lg)
        except srv.ServerError as e:
            raise _kerr(e) from e
        v.config_json, v.log_json = json.dumps(cfg), json.dumps(lg)
        if body.name:
            v.name = body.name.strip()
        if body.platform is not None:
            v.platform = body.platform.strip() or None
        if body.password:
            v.secret_enc = encrypt(body.password)
        await s.commit()
        return _service_dict(v)


@router.delete("/services/{service_id}", status_code=204)
async def delete_service(service_id: int):
    async with SessionLocal() as s:
        v = await s.get(Service, service_id)
        if v:
            await s.delete(v)
            await s.commit()


@router.post("/services/{service_id}/check")
async def check_now(service_id: int):
    async with SessionLocal() as s:
        v = await s.get(Service, service_id)
        if not v:
            raise HTTPException(404, "Servicio no encontrado")
        x = await _load_server(s, v.server_id)
        v = next(y for y in x.services if y.id == service_id)
        try:
            status, summary, detail, latency = await srv.check_service(x, v)
        except srv.ServerError as e:
            raise _kerr(e) from e
        srv.poller._record(s, v, status, summary, detail, latency, utcnow())
        await s.commit()
        return _service_dict(v)


@router.get("/services/{service_id}/history")
async def service_history(service_id: int, hours: int = 24):
    since = utcnow() - timedelta(hours=min(max(hours, 1), 48))
    async with SessionLocal() as s:
        rows = (await s.execute(select(ServiceCheck.ts, ServiceCheck.status,
                                       ServiceCheck.latency_ms)
                                .where(ServiceCheck.service_id == service_id,
                                       ServiceCheck.ts >= since)
                                .order_by(ServiceCheck.ts))).all()
    return [{"ts": iso(t), "status": st, "latency_ms": lat} for t, st, lat in rows]


@router.get("/services/{service_id}/log")
async def service_log(service_id: int, lines: int = 500, cursor: str | None = None,
                      grep: str | None = None):
    async with SessionLocal() as s:
        v = await s.get(Service, service_id)
        if not v:
            raise HTTPException(404, "Servicio no encontrado")
        x = await _load_server(s, v.server_id)
        v = next(y for y in x.services if y.id == service_id)
        try:
            out = await srv.read_log(x, v, lines, cursor, grep)
        except srv.ServerError as e:
            raise _kerr(e) from e
        if x.host_key and s.is_modified(x):
            await s.commit()
        return out


@router.get("/infra/overview")
async def infra_overview():
    async with SessionLocal() as s:
        servers = (await s.execute(select(Server.status, func.count()).group_by(Server.status)
                                   )).all()
        services = (await s.execute(select(Service.status, func.count())
                                    .group_by(Service.status))).all()
    return {"servers": dict(servers), "services": dict(services)}
