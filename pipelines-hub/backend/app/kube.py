"""Visor de Kubernetes de solo lectura.

Usa el kubeconfig del equipo (montado en el contenedor) y, para EKS, genera el token con
botocore igual que `aws eks get-token`, así no hace falta la CLI de AWS en la imagen.
Por diseño este módulo solo hace GET contra la API: aunque la cuenta sea admin del
cluster, el panel no puede cambiar nada. Los Secrets se muestran sin sus valores.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import ssl
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.config import get_settings


class KubeError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def kubeconfig_path() -> Path:
    raw = os.environ.get("KUBECONFIG") or str(get_settings().kubeconfig)
    return Path(raw.split(os.pathsep)[0]).expanduser()


def load_kubeconfig() -> dict[str, Any]:
    path = kubeconfig_path()
    if not path.exists():
        raise KubeError(f"No encuentro el kubeconfig en {path}. Monta ~/.kube en el contenedor.",
                        404)
    return yaml.safe_load(path.read_text()) or {}


def list_contexts() -> list[dict[str, Any]]:
    cfg = load_kubeconfig()
    clusters = {c["name"]: c.get("cluster", {}) for c in cfg.get("clusters", [])}
    out = []
    for ctx in cfg.get("contexts", []):
        c = ctx.get("context", {})
        out.append({
            "name": ctx["name"],
            "cluster": c.get("cluster"),
            "server": clusters.get(c.get("cluster"), {}).get("server"),
            "namespace": c.get("namespace"),
            "current": ctx["name"] == cfg.get("current-context"),
        })
    return out


def _arg(args: list[str], flag: str) -> str | None:
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def eks_token(cluster_name: str, region: str, profile: str | None = None,
              role_arn: str | None = None) -> str:
    """Token de EKS: URL prefirmada de sts:GetCallerIdentity con el header x-k8s-aws-id."""
    import botocore.session
    from botocore.signers import RequestSigner

    session = botocore.session.Session(profile=profile or None)
    creds = session.get_credentials()
    if creds is None:
        raise KubeError("No hay credenciales de AWS en el contenedor (monta ~/.aws).", 401)
    if role_arn:
        sts = session.create_client("sts", region_name=region)
        r = sts.assume_role(RoleArn=role_arn, RoleSessionName="pipelines-hub")["Credentials"]
        from botocore.credentials import Credentials

        creds = Credentials(r["AccessKeyId"], r["SecretAccessKey"], r["SessionToken"])
    client = session.create_client("sts", region_name=region)
    signer = RequestSigner(client.meta.service_model.service_id, region, "sts", "v4", creds,
                           session.get_component("event_emitter"))
    url = signer.generate_presigned_url(
        {
            "method": "GET",
            "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity"
                   "&Version=2011-06-15",
            "body": {},
            "headers": {"x-k8s-aws-id": cluster_name},
            "context": {},
        },
        region_name=region, expires_in=60, operation_name="",
    )
    return "k8s-aws-v1." + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


@dataclass
class _Auth:
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: float = 0.0


class KubeClient:
    """Cliente mínimo de la API de Kubernetes para un contexto del kubeconfig."""

    def __init__(self, context: str):
        cfg = load_kubeconfig()
        ctx = next((c for c in cfg.get("contexts", []) if c["name"] == context), None)
        if not ctx:
            raise KubeError(f"El contexto {context} no está en el kubeconfig", 404)
        c = ctx.get("context", {})
        cluster = next((x["cluster"] for x in cfg.get("clusters", [])
                        if x["name"] == c.get("cluster")), None)
        user = next((x.get("user", {}) for x in cfg.get("users", [])
                     if x["name"] == c.get("user")), {})
        if not cluster:
            raise KubeError(f"El cluster del contexto {context} no está en el kubeconfig", 404)
        self.context = context
        self.server = cluster["server"].rstrip("/")
        self.user = user
        self._auth = _Auth()
        self._tmp: list[str] = []
        self._client = httpx.AsyncClient(base_url=self.server, verify=self._ssl(cluster, user),
                                         timeout=httpx.Timeout(20, connect=10))

    def _tmpfile(self, data: bytes) -> str:
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(data)
        f.close()
        os.chmod(f.name, 0o600)
        self._tmp.append(f.name)
        return f.name

    def _ssl(self, cluster: dict, user: dict):
        if cluster.get("insecure-skip-tls-verify"):
            return False
        ctx = ssl.create_default_context()
        if cluster.get("certificate-authority-data"):
            ctx = ssl.create_default_context(
                cadata=base64.b64decode(cluster["certificate-authority-data"]).decode())
        elif cluster.get("certificate-authority"):
            ctx = ssl.create_default_context(cafile=cluster["certificate-authority"])
        cert = user.get("client-certificate-data")
        key = user.get("client-key-data")
        if cert and key:
            ctx.load_cert_chain(self._tmpfile(base64.b64decode(cert)),
                                self._tmpfile(base64.b64decode(key)))
        elif user.get("client-certificate") and user.get("client-key"):
            ctx.load_cert_chain(user["client-certificate"], user["client-key"])
        return ctx

    async def _headers(self) -> dict[str, str]:
        if self._auth.headers and time.time() < self._auth.expires_at:
            return self._auth.headers
        u = self.user
        if u.get("token"):
            self._auth = _Auth({"Authorization": f"Bearer {u['token']}"}, time.time() + 3600)
        elif u.get("username") and u.get("password"):
            basic = base64.b64encode(f"{u['username']}:{u['password']}".encode()).decode()
            self._auth = _Auth({"Authorization": f"Basic {basic}"}, time.time() + 3600)
        elif u.get("exec"):
            token = await self._exec_token(u["exec"])
            self._auth = _Auth({"Authorization": f"Bearer {token}"}, time.time() + 600)
        else:
            self._auth = _Auth({}, time.time() + 3600)  # certificado de cliente
        return self._auth.headers

    async def _exec_token(self, spec: dict) -> str:
        cmd = spec.get("command", "")
        args = spec.get("args") or []
        env = {e["name"]: e["value"] for e in spec.get("env") or []}
        if Path(cmd).name == "aws" and "get-token" in args:
            cluster = _arg(args, "--cluster-name") or _arg(args, "--cluster-id")
            region = _arg(args, "--region") or env.get("AWS_REGION") \
                or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") \
                or "us-east-1"
            profile = _arg(args, "--profile") or env.get("AWS_PROFILE") \
                or os.environ.get("AWS_PROFILE")
            role = _arg(args, "--role-arn")
            try:
                return await asyncio.to_thread(eks_token, cluster, region, profile, role)
            except KubeError:
                raise
            except Exception as e:
                raise KubeError(f"No se pudo generar el token de EKS: {e}", 401) from e
        if not shutil.which(cmd):
            raise KubeError(f"El kubeconfig usa '{cmd}' para autenticar y no está en el "
                            "contenedor", 501)
        proc = await asyncio.create_subprocess_exec(
            cmd, *args, env={**os.environ, **env},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), 30)
        if proc.returncode:
            raise KubeError(f"{cmd} falló: {err.decode()[:300]}", 401)
        return json.loads(out)["status"]["token"]

    async def get(self, path: str, params: dict | None = None, raw: bool = False):
        headers = await self._headers()
        try:
            r = await self._client.get(path, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise KubeError(f"No se pudo conectar al cluster: {e.__class__.__name__}: {e}") from e
        if r.status_code == 401:
            self._auth = _Auth()
            raise KubeError("El cluster rechazó las credenciales (401)", 401)
        if r.status_code == 404:
            raise KubeError("No encontrado", 404)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message")
            except Exception:
                msg = r.text[:300]
            raise KubeError(f"HTTP {r.status_code}: {msg}", r.status_code)
        return r.text if raw else r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
        for f in self._tmp:
            try:
                os.unlink(f)
            except OSError:
                pass


_clients: dict[str, KubeClient] = {}
_cache: dict[tuple, tuple[float, Any]] = {}


def client_for(context: str) -> KubeClient:
    if context not in _clients:
        _clients[context] = KubeClient(context)
    return _clients[context]


async def close_all() -> None:
    for c in list(_clients.values()):
        await c.aclose()
    _clients.clear()


async def cached_get(context: str, path: str, params: dict | None = None, ttl: float = 10):
    key = (context, path, json.dumps(params or {}, sort_keys=True))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = await client_for(context).get(path, params)
    _cache[key] = (time.time(), data)
    return data


# --- helpers de formato ---------------------------------------------------------------------
def _age(ts: str | None) -> str | None:
    return ts


def parse_cpu(v: str | None) -> float:
    """Núcleos."""
    if not v:
        return 0.0
    v = str(v)
    if v.endswith("n"):
        return int(v[:-1]) / 1e9
    if v.endswith("u"):
        return int(v[:-1]) / 1e6
    if v.endswith("m"):
        return int(v[:-1]) / 1000
    return float(v)


_MEM = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "K": 1000, "M": 1000**2,
        "G": 1000**3, "T": 1000**4, "k": 1000}


def parse_mem(v: str | None) -> int:
    """Bytes."""
    if not v:
        return 0
    v = str(v)
    for suf in sorted(_MEM, key=len, reverse=True):
        if v.endswith(suf):
            return int(float(v[: -len(suf)]) * _MEM[suf])
    try:
        return int(float(v))
    except ValueError:
        return 0


def _meta(o: dict) -> dict:
    m = o.get("metadata", {})
    return {"name": m.get("name"), "namespace": m.get("namespace"),
            "created_at": m.get("creationTimestamp"), "labels": m.get("labels") or {}}


# --- pods ----------------------------------------------------------------------------------
_BAD_WAITING = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
                "CreateContainerConfigError", "CreateContainerError", "InvalidImageName",
                "RunContainerError"}


def pod_summary(p: dict, usage: dict | None = None) -> dict:
    st = p.get("status", {})
    spec = p.get("spec", {})
    cs = st.get("containerStatuses") or []
    ready = sum(1 for c in cs if c.get("ready"))
    restarts = sum(c.get("restartCount", 0) for c in cs)
    reason = st.get("reason")
    last_term = None
    for c in cs:
        w = (c.get("state") or {}).get("waiting")
        t = (c.get("state") or {}).get("terminated")
        if w and w.get("reason"):
            reason = w["reason"]
        elif t and t.get("reason") and st.get("phase") != "Succeeded":
            reason = t["reason"]
        lt = (c.get("lastState") or {}).get("terminated")
        if lt:
            last_term = {"reason": lt.get("reason"), "exit_code": lt.get("exitCode"),
                         "finished_at": lt.get("finishedAt")}
    phase = st.get("phase", "Unknown")
    if p.get("metadata", {}).get("deletionTimestamp"):
        phase, reason = "Terminating", reason or "Terminating"
    owner = next(iter(p["metadata"].get("ownerReferences") or []), {})
    finished_job_pod = owner.get("kind") == "Job" and phase in ("Failed", "Succeeded")
    problem = not finished_job_pod and (
        phase in ("Failed", "Unknown")
        or reason in _BAD_WAITING
        or (phase == "Running" and cs and ready < len(cs))
        or (phase == "Pending" and _older_than(st.get("startTime")
                                                or p["metadata"].get("creationTimestamp"), 300))
    )
    return {
        **_meta(p),
        "phase": phase,
        "reason": reason,
        "ready": f"{ready}/{len(spec.get('containers') or [])}",
        "restarts": restarts,
        "last_termination": last_term,
        "node": spec.get("nodeName"),
        "ip": st.get("podIP"),
        "owner_kind": owner.get("kind"),
        "owner_name": owner.get("name"),
        "containers": [c["name"] for c in spec.get("containers") or []],
        "images": [c.get("image") for c in spec.get("containers") or []],
        "started_at": st.get("startTime"),
        "cpu": usage.get("cpu") if usage else None,
        "memory": usage.get("memory") if usage else None,
        "mem_limit": sum(parse_mem(((c.get("resources") or {}).get("limits") or {}).get("memory"))
                         for c in spec.get("containers") or []) or None,
        "problem": bool(problem),
    }


def _older_than(ts: str | None, seconds: int) -> bool:
    if not ts:
        return False
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(UTC) - dt).total_seconds() > seconds


async def _pod_usage(context: str, namespace: str | None) -> dict[tuple[str, str], dict]:
    path = (f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods" if namespace
            else "/apis/metrics.k8s.io/v1beta1/pods")
    try:
        data = await cached_get(context, path, ttl=20)
    except KubeError:
        return {}
    out = {}
    for m in data.get("items", []):
        cpu = sum(parse_cpu(c["usage"].get("cpu")) for c in m.get("containers", []))
        mem = sum(parse_mem(c["usage"].get("memory")) for c in m.get("containers", []))
        out[(m["metadata"]["namespace"], m["metadata"]["name"])] = {"cpu": cpu, "memory": mem}
    return out


def _ns_path(namespace: str | None, group: str, resource: str) -> str:
    return f"{group}/namespaces/{namespace}/{resource}" if namespace else f"{group}/{resource}"


async def pods(context: str, namespace: str | None = None) -> list[dict]:
    data = await cached_get(context, _ns_path(namespace, "/api/v1", "pods"))
    usage = await _pod_usage(context, namespace)
    items = [pod_summary(p, usage.get((p["metadata"]["namespace"], p["metadata"]["name"])))
             for p in data.get("items", [])]
    return sorted(items, key=lambda x: (not x["problem"], x["namespace"], x["name"]))


# --- workloads -----------------------------------------------------------------------------
def _images(tpl: dict) -> list[str]:
    return [c.get("image") for c in (tpl.get("spec") or {}).get("containers") or []]


def deployment_summary(d: dict) -> dict:
    spec, st = d.get("spec", {}), d.get("status", {})
    desired = spec.get("replicas", 1)
    ready = st.get("readyReplicas", 0)
    return {**_meta(d), "kind": "Deployment", "desired": desired, "ready": ready,
            "updated": st.get("updatedReplicas", 0), "available": st.get("availableReplicas", 0),
            "images": _images(spec.get("template", {})),
            "problem": ready < desired,
            "conditions": [{"type": c.get("type"), "status": c.get("status"),
                            "reason": c.get("reason"), "message": c.get("message")}
                           for c in st.get("conditions") or []]}


def statefulset_summary(d: dict) -> dict:
    spec, st = d.get("spec", {}), d.get("status", {})
    desired, ready = spec.get("replicas", 1), st.get("readyReplicas", 0)
    return {**_meta(d), "kind": "StatefulSet", "desired": desired, "ready": ready,
            "images": _images(spec.get("template", {})), "problem": ready < desired}


def daemonset_summary(d: dict) -> dict:
    spec, st = d.get("spec", {}), d.get("status", {})
    desired, ready = st.get("desiredNumberScheduled", 0), st.get("numberReady", 0)
    return {**_meta(d), "kind": "DaemonSet", "desired": desired, "ready": ready,
            "images": _images(spec.get("template", {})), "problem": ready < desired}


def job_summary(j: dict) -> dict:
    spec, st = j.get("spec", {}), j.get("status", {})
    conds = {c["type"]: c for c in st.get("conditions") or [] if c.get("status") == "True"}
    if "Failed" in conds:
        status = "failed"
    elif "Complete" in conds or "SuccessCriteriaMet" in conds:
        status = "success"
    elif st.get("active"):
        status = "running"
    else:
        status = "queued"
    owner = next(iter(j["metadata"].get("ownerReferences") or []), {})
    return {**_meta(j), "kind": "Job", "status": status,
            "succeeded": st.get("succeeded", 0), "failed": st.get("failed", 0),
            "active": st.get("active", 0), "completions": spec.get("completions", 1),
            "started_at": st.get("startTime"), "finished_at": st.get("completionTime")
            or (conds.get("Failed") or {}).get("lastTransitionTime"),
            "reason": (conds.get("Failed") or {}).get("reason"),
            "cronjob": owner.get("name") if owner.get("kind") == "CronJob" else None,
            "images": _images(spec.get("template") or {}), "problem": status == "failed"}


def cronjob_summary(c: dict, last_job: dict | None) -> dict:
    spec, st = c.get("spec", {}), c.get("status", {})
    tpl = ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}
    return {**_meta(c), "kind": "CronJob", "schedule": spec.get("schedule"),
            "timezone": spec.get("timeZone"), "suspended": bool(spec.get("suspend")),
            "last_schedule": st.get("lastScheduleTime"),
            "last_success": st.get("lastSuccessfulTime"),
            "active": len(st.get("active") or []),
            "images": _images(tpl),
            "last_job": last_job,
            "problem": bool(last_job and last_job["status"] == "failed")}


async def workloads(context: str, kind: str, namespace: str | None = None) -> list[dict]:
    if kind == "deployments":
        data = await cached_get(context, _ns_path(namespace, "/apis/apps/v1", "deployments"))
        items = [deployment_summary(d) for d in data.get("items", [])]
    elif kind == "statefulsets":
        data = await cached_get(context, _ns_path(namespace, "/apis/apps/v1", "statefulsets"))
        items = [statefulset_summary(d) for d in data.get("items", [])]
    elif kind == "daemonsets":
        data = await cached_get(context, _ns_path(namespace, "/apis/apps/v1", "daemonsets"))
        items = [daemonset_summary(d) for d in data.get("items", [])]
    elif kind == "jobs":
        data = await cached_get(context, _ns_path(namespace, "/apis/batch/v1", "jobs"))
        items = sorted((job_summary(j) for j in data.get("items", [])),
                       key=lambda j: j["started_at"] or "", reverse=True)
        return items
    elif kind == "cronjobs":
        data = await cached_get(context, _ns_path(namespace, "/apis/batch/v1", "cronjobs"))
        jobs = await cached_get(context, _ns_path(namespace, "/apis/batch/v1", "jobs"))
        latest: dict[tuple, dict] = {}
        for j in jobs.get("items", []):
            s = job_summary(j)
            if s["cronjob"]:
                k = (s["namespace"], s["cronjob"])
                if (s["started_at"] or "") > ((latest.get(k) or {}).get("started_at") or ""):
                    latest[k] = s
        items = [cronjob_summary(c, latest.get((c["metadata"]["namespace"],
                                                c["metadata"]["name"])))
                 for c in data.get("items", [])]
    else:
        raise KubeError(f"Tipo desconocido: {kind}", 422)
    return sorted(items, key=lambda x: (not x["problem"], x["namespace"], x["name"]))


# --- red y configuración --------------------------------------------------------------------
async def network(context: str, namespace: str | None = None) -> dict:
    svcs = await cached_get(context, _ns_path(namespace, "/api/v1", "services"))
    ings = await cached_get(context, _ns_path(namespace, "/apis/networking.k8s.io/v1",
                                              "ingresses"))
    services = []
    for s in svcs.get("items", []):
        spec = s.get("spec", {})
        lb = ((s.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []
        services.append({**_meta(s), "type": spec.get("type"), "cluster_ip": spec.get("clusterIP"),
                         "external": [x.get("hostname") or x.get("ip") for x in lb],
                         "ports": [f"{p.get('port')}→{p.get('targetPort')}/{p.get('protocol')}"
                                   + (f" (node {p['nodePort']})" if p.get("nodePort") else "")
                                   for p in spec.get("ports") or []],
                         "selector": spec.get("selector") or {}})
    ingresses = []
    for i in ings.get("items", []):
        spec = i.get("spec", {})
        lb = ((i.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []
        rules = []
        for r in spec.get("rules") or []:
            for p in ((r.get("http") or {}).get("paths") or []):
                be = (p.get("backend") or {}).get("service") or {}
                rules.append({"host": r.get("host"), "path": p.get("path"),
                              "service": be.get("name"),
                              "port": (be.get("port") or {}).get("number")
                              or (be.get("port") or {}).get("name")})
        ingresses.append({**_meta(i), "class": spec.get("ingressClassName"),
                          "address": [x.get("hostname") or x.get("ip") for x in lb],
                          "tls": [h for t in spec.get("tls") or [] for h in t.get("hosts") or []],
                          "rules": rules})
    return {"services": services, "ingresses": ingresses}


async def config_objects(context: str, namespace: str | None = None) -> dict:
    cms = await cached_get(context, _ns_path(namespace, "/api/v1", "configmaps"))
    # los Secrets no pasan por la caché: sus valores no se quedan en memoria
    secs = await client_for(context).get(_ns_path(namespace, "/api/v1", "secrets"))
    return {
        "configmaps": [{**_meta(c), "keys": sorted((c.get("data") or {}).keys())}
                       for c in cms.get("items", [])],
        # nunca se devuelven valores de Secrets: solo tipo y nombres de claves
        "secrets": [{**_meta(s), "type": s.get("type"),
                     "keys": sorted((s.get("data") or {}).keys())}
                    for s in secs.get("items", [])],
    }


# --- nodos, namespaces y eventos ------------------------------------------------------------
async def nodes(context: str) -> list[dict]:
    data = await cached_get(context, "/api/v1/nodes")
    try:
        metrics = await cached_get(context, "/apis/metrics.k8s.io/v1beta1/nodes", ttl=20)
        usage = {m["metadata"]["name"]: m["usage"] for m in metrics.get("items", [])}
    except KubeError:
        usage = {}
    all_pods = await cached_get(context, "/api/v1/pods")
    per_node: dict[str, int] = {}
    for p in all_pods.get("items", []):
        n = p.get("spec", {}).get("nodeName")
        if n and p.get("status", {}).get("phase") in ("Running", "Pending"):
            per_node[n] = per_node.get(n, 0) + 1
    out = []
    for n in data.get("items", []):
        name = n["metadata"]["name"]
        st = n.get("status", {})
        conds = {c["type"]: c for c in st.get("conditions") or []}
        labels = n["metadata"].get("labels") or {}
        alloc = st.get("allocatable") or {}
        u = usage.get(name, {})
        pressure = [t for t in ("MemoryPressure", "DiskPressure", "PIDPressure")
                    if (conds.get(t) or {}).get("status") == "True"]
        ready = (conds.get("Ready") or {}).get("status") == "True"
        out.append({
            "name": name,
            "created_at": n["metadata"].get("creationTimestamp"),
            "ready": ready,
            "pressure": pressure,
            "unschedulable": bool(n.get("spec", {}).get("unschedulable")),
            "instance_type": labels.get("node.kubernetes.io/instance-type"),
            "zone": labels.get("topology.kubernetes.io/zone"),
            "capacity_type": labels.get("eks.amazonaws.com/capacityType")
            or labels.get("karpenter.sh/capacity-type"),
            "nodegroup": labels.get("eks.amazonaws.com/nodegroup"),
            "version": (st.get("nodeInfo") or {}).get("kubeletVersion"),
            "cpu_alloc": parse_cpu(alloc.get("cpu")),
            "mem_alloc": parse_mem(alloc.get("memory")),
            "pods_alloc": int(alloc.get("pods", 0) or 0),
            "cpu_used": parse_cpu(u.get("cpu")) if u else None,
            "mem_used": parse_mem(u.get("memory")) if u else None,
            "pods": per_node.get(name, 0),
            "problem": not ready or bool(pressure),
        })
    return sorted(out, key=lambda x: x["name"])


async def events(context: str, namespace: str | None = None, warnings_only: bool = False,
                 involved: str | None = None, limit: int = 300) -> list[dict]:
    params = {}
    selectors = []
    if warnings_only:
        selectors.append("type=Warning")
    if involved:
        selectors.append(f"involvedObject.name={involved}")
    if selectors:
        params["fieldSelector"] = ",".join(selectors)
    data = await cached_get(context, _ns_path(namespace, "/api/v1", "events"), params)
    out = []
    for e in data.get("items", []):
        obj = e.get("involvedObject") or {}
        out.append({
            "namespace": e["metadata"].get("namespace"),
            "type": e.get("type"),
            "reason": e.get("reason"),
            "message": e.get("message"),
            "kind": obj.get("kind"),
            "object": obj.get("name"),
            "count": e.get("count") or 1,
            "last_seen": e.get("lastTimestamp") or e.get("eventTime")
            or e["metadata"].get("creationTimestamp"),
        })
    out.sort(key=lambda x: x["last_seen"] or "", reverse=True)
    return out[:limit]


async def overview(context: str) -> dict:
    ns_data, node_list, pod_list, deps, crons, evs = await asyncio.gather(
        cached_get(context, "/api/v1/namespaces"),
        nodes(context),
        pods(context),
        workloads(context, "deployments"),
        workloads(context, "cronjobs"),
        events(context, warnings_only=True, limit=40),
    )
    namespaces: dict[str, dict] = {
        n["metadata"]["name"]: {"name": n["metadata"]["name"], "pods": 0, "problems": 0,
                                "cpu": 0.0, "memory": 0}
        for n in ns_data.get("items", [])
    }
    for p in pod_list:
        ns = namespaces.setdefault(p["namespace"], {"name": p["namespace"], "pods": 0,
                                                    "problems": 0, "cpu": 0.0, "memory": 0})
        ns["pods"] += 1
        ns["problems"] += int(p["problem"])
        ns["cpu"] += p["cpu"] or 0
        ns["memory"] += p["memory"] or 0
    cpu_alloc = sum(n["cpu_alloc"] for n in node_list)
    mem_alloc = sum(n["mem_alloc"] for n in node_list)
    return {
        "context": context,
        "totals": {
            "nodes": len(node_list),
            "nodes_ready": sum(1 for n in node_list if n["ready"]),
            "pods": len(pod_list),
            "pods_running": sum(1 for p in pod_list if p["phase"] == "Running"),
            "deployments": len(deps),
            "cronjobs": len(crons),
            "cpu_alloc": cpu_alloc,
            "mem_alloc": mem_alloc,
            "cpu_used": sum(n["cpu_used"] or 0 for n in node_list),
            "mem_used": sum(n["mem_used"] or 0 for n in node_list),
            "has_metrics": any(n["cpu_used"] is not None for n in node_list),
        },
        "problems": {
            "pods": [p for p in pod_list if p["problem"]][:50],
            "deployments": [d for d in deps if d["problem"]],
            "cronjobs": [c for c in crons if c["problem"]],
            "nodes": [n for n in node_list if n["problem"]],
            "restarts": sorted((p for p in pod_list if p["restarts"] >= 3),
                               key=lambda p: -p["restarts"])[:15],
        },
        "namespaces": sorted(namespaces.values(), key=lambda n: (-n["problems"], n["name"])),
        "nodes": node_list,
        "warnings": evs,
    }


# --- detalle y logs -------------------------------------------------------------------------
_KINDS = {
    "pods": ("/api/v1", "pods"),
    "services": ("/api/v1", "services"),
    "configmaps": ("/api/v1", "configmaps"),
    "secrets": ("/api/v1", "secrets"),
    "deployments": ("/apis/apps/v1", "deployments"),
    "statefulsets": ("/apis/apps/v1", "statefulsets"),
    "daemonsets": ("/apis/apps/v1", "daemonsets"),
    "replicasets": ("/apis/apps/v1", "replicasets"),
    "jobs": ("/apis/batch/v1", "jobs"),
    "cronjobs": ("/apis/batch/v1", "cronjobs"),
    "ingresses": ("/apis/networking.k8s.io/v1", "ingresses"),
    "nodes": ("/api/v1", "nodes"),
}


def _clean(obj: dict) -> dict:
    obj = json.loads(json.dumps(obj))
    meta = obj.get("metadata", {})
    meta.pop("managedFields", None)
    ann = meta.get("annotations") or {}
    ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    if obj.get("kind") == "Secret":
        for k in ("data", "stringData"):
            if obj.get(k):
                obj[k] = {key: "<oculto>" for key in obj[k]}
    return obj


async def resource(context: str, kind: str, namespace: str | None, name: str) -> dict:
    if kind not in _KINDS:
        raise KubeError(f"Tipo desconocido: {kind}", 422)
    group, res = _KINDS[kind]
    path = f"{group}/{res}/{name}" if kind == "nodes" else \
        f"{group}/namespaces/{namespace}/{res}/{name}"
    obj = await client_for(context).get(path)
    obj = _clean(obj)
    out: dict[str, Any] = {
        "kind": obj.get("kind"),
        "name": name,
        "namespace": namespace,
        "yaml": yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=120),
        "events": await events(context, namespace if kind != "nodes" else None,
                               involved=name, limit=50),
    }
    if kind == "pods":
        usage = await _pod_usage(context, namespace)
        out["summary"] = pod_summary(obj, usage.get((namespace, name)))
        st = obj.get("status", {})
        out["container_states"] = [
            {"name": c["name"], "image": c.get("image"), "ready": c.get("ready"),
             "restarts": c.get("restartCount", 0), "state": c.get("state"),
             "last_state": c.get("lastState")}
            for c in (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or [])
        ]
    selector = ((obj.get("spec") or {}).get("selector") or {})
    labels = selector.get("matchLabels") if kind != "services" else selector
    if kind == "cronjobs":
        jobs = await workloads(context, "jobs", namespace)
        out["jobs"] = [j for j in jobs if j["cronjob"] == name][:20]
    if kind == "jobs":
        labels = {"job-name": name}
    if kind == "nodes":
        all_pods = await pods(context)
        out["pods"] = [p for p in all_pods if p["node"] == name]
    elif labels:
        sel = ",".join(f"{k}={v}" for k, v in labels.items())
        data = await client_for(context).get(f"/api/v1/namespaces/{namespace}/pods",
                                             {"labelSelector": sel})
        usage = await _pod_usage(context, namespace)
        out["pods"] = [pod_summary(p, usage.get((namespace, p["metadata"]["name"])))
                       for p in data.get("items", [])]
    return out


async def pod_log(context: str, namespace: str, name: str, container: str | None = None,
                  previous: bool = False, tail: int = 2000, since_time: str | None = None
                  ) -> str:
    params: dict[str, Any] = {"timestamps": "true"}
    if container:
        params["container"] = container
    if previous:
        params["previous"] = "true"
    if since_time:
        params["sinceTime"] = since_time
    else:
        params["tailLines"] = str(min(max(tail, 1), 20000))
    params["limitBytes"] = str(8 * 1024 * 1024)
    return await client_for(context).get(f"/api/v1/namespaces/{namespace}/pods/{name}/log",
                                         params, raw=True)
