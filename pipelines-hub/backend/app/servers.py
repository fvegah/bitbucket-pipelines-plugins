"""Monitoreo de servidores por SSH, sin agente.

Cada minuto se toma una muestra (CPU, carga, memoria, disco) y se chequea cada servicio
registrado (systemd, docker, redis, postgres, sidekiq, rabbitmq, http, tcp, proceso).
Los comandos son fijos y los parámetros que vienen del usuario (unidad, ruta, contenedor,
host) se validan y se citan con shlex: el panel nunca ejecuta texto libre en el servidor.

La huella del servidor se acepta la primera vez (TOFU) y después se exige la misma.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncssh
import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.crypto import decrypt
from app.db import Server, ServerSample, Service, ServiceCheck, SessionLocal, utcnow

log = logging.getLogger("pipelines_hub.servers")

KINDS = ("systemd", "docker", "redis", "postgres", "sidekiq", "rabbitmq", "http", "tcp",
         "process", "log")
LOG_TYPES = ("none", "journal", "file", "docker")

_UNIT = re.compile(r"^[\w@.:\-]{1,200}$")
_CONTAINER = re.compile(r"^[\w.\-]{1,200}$")
_PATH = re.compile(r"^/[\w./@+\-]{1,400}$")
_HOST = re.compile(r"^[\w.\-:\[\]]{1,255}$")
_NAME = re.compile(r"^[\w.\-:]{0,100}$")
_PATTERN = re.compile(r"^[\w ./=@:\-]{1,200}$")


class ServerError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _check(value: Any, rx: re.Pattern, what: str) -> str:
    v = str(value or "").strip()
    if not rx.match(v) or ".." in v:
        raise ServerError(f"{what} inválido: {v!r}", 422)
    return v


def validate_service(kind: str, config: dict, log_cfg: dict) -> tuple[dict, dict]:
    """Normaliza y valida la configuración antes de guardarla."""
    if kind not in KINDS:
        raise ServerError(f"Tipo de servicio desconocido: {kind}", 422)
    c: dict[str, Any] = {}
    if kind in ("systemd", "sidekiq") and config.get("unit"):
        c["unit"] = _check(config["unit"], _UNIT, "Unidad systemd")
    if kind == "systemd" and "unit" not in c:
        raise ServerError("Falta la unidad de systemd", 422)
    if kind == "docker":
        c["container"] = _check(config.get("container"), _CONTAINER, "Contenedor")
    if kind in ("redis", "sidekiq"):
        c["host"] = _check(config.get("host") or "127.0.0.1", _HOST, "Host de Redis")
        c["port"] = int(config.get("port") or 6379)
        c["db"] = int(config.get("db") or 0)
        c["tls"] = bool(config.get("tls"))
    if kind == "sidekiq":
        c["namespace"] = _check(config.get("namespace") or "", _NAME, "Namespace")
    if kind == "postgres":
        c["mode"] = config.get("mode") if config.get("mode") in ("local", "remote") else "local"
        if c["mode"] == "remote":
            c["host"] = _check(config.get("host"), _HOST, "Host de Postgres")
            c["port"] = int(config.get("port") or 5432)
            c["user"] = _check(config.get("user") or "postgres", _NAME, "Usuario")
            c["database"] = _check(config.get("database") or "postgres", _NAME, "Base")
    if kind == "http":
        url = str(config.get("url") or "").strip()
        if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
            raise ServerError("URL inválida (http o https)", 422)
        c["url"] = url
        c["from_server"] = bool(config.get("from_server"))
        c["expect"] = int(config.get("expect") or 200)
    if kind == "tcp":
        c["port"] = int(config.get("port") or 0)
        if not 0 < c["port"] < 65536:
            raise ServerError("Puerto inválido", 422)
    if kind == "process":
        c["pattern"] = _check(config.get("pattern"), _PATTERN, "Patrón de proceso")
    if kind == "log":
        pass
    lg: dict[str, Any] = {"type": log_cfg.get("type") or "none"}
    if lg["type"] not in LOG_TYPES:
        raise ServerError("Tipo de log inválido", 422)
    if lg["type"] == "journal":
        lg["unit"] = _check(log_cfg.get("unit") or c.get("unit"), _UNIT, "Unidad del log")
    elif lg["type"] == "file":
        lg["path"] = _check(log_cfg.get("path"), _PATH, "Ruta del log")
    elif lg["type"] == "docker":
        lg["container"] = _check(log_cfg.get("container") or c.get("container"), _CONTAINER,
                                 "Contenedor del log")
    if kind == "log" and lg["type"] == "none":
        raise ServerError("Un servicio de tipo log necesita una fuente de log", 422)
    return c, lg


# --- ~/.ssh montado ------------------------------------------------------------------------
def ssh_dir() -> Path:
    return get_settings().ssh_dir.expanduser()


def ssh_aliases() -> list[dict[str, Any]]:
    """Hosts de ~/.ssh/config para importar (solo HostName/User/Port/IdentityFile)."""
    cfg = ssh_dir() / "config"
    if not cfg.exists():
        return []
    out: list[dict] = []
    current: list[dict] = []
    for raw in cfg.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        key, value = key.lower(), value.strip().strip('"')
        if key == "host":
            current = [{"alias": a} for a in value.split() if "*" not in a and "?" not in a]
            out.extend(current)
            continue
        for h in current:
            if key == "hostname":
                h["host"] = value
            elif key == "user":
                h["user"] = value
            elif key == "port":
                h["port"] = int(value)
            elif key == "identityfile":
                h["key_path"] = Path(value.replace("~/.ssh/", "")).name if "/.ssh/" in value \
                    or value.startswith("~/") else value
            elif key in ("proxycommand", "proxyjump"):
                h["proxy"] = True
    return [h for h in out if h.get("host") and "github" not in h["host"]
            and "bitbucket" not in h["host"]]


def ssh_keys() -> list[str]:
    d = ssh_dir()
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if f.is_file() and not f.name.endswith(".pub") and f.name not in (
                "config", "known_hosts", "known_hosts.old", "authorized_keys"):
            try:
                head = f.read_text(errors="ignore")[:60]
            except OSError:
                continue
            if "PRIVATE KEY" in head:
                out.append(f.name)
    return out


# --- conexiones ----------------------------------------------------------------------------
@dataclass
class _Conn:
    conn: asyncssh.SSHClientConnection
    signature: str


_pool: dict[int, _Conn] = {}
_locks: dict[int, asyncio.Lock] = {}


def _signature(s: Server) -> str:
    return f"{s.host}|{s.port}|{s.username}|{s.key_path}|{s.key_enc}|{s.host_key}"


def _client_key(s: Server):
    passphrase = decrypt(s.passphrase_enc) if s.passphrase_enc else None
    try:
        if s.key_enc:
            return asyncssh.import_private_key(decrypt(s.key_enc), passphrase)
        if s.key_path:
            path = ssh_dir() / Path(s.key_path).name
            return asyncssh.read_private_key(str(path), passphrase)
    except (asyncssh.KeyImportError, OSError) as e:
        raise ServerError(f"No se pudo leer la llave: {e}", 422) from e
    raise ServerError("El servidor no tiene llave configurada", 422)


async def connect_raw(host: str, port: int, username: str, key,
                      expected_host_key: str | None) -> tuple[asyncssh.SSHClientConnection, str]:
    try:
        conn = await asyncio.wait_for(asyncssh.connect(
            host, port=port, username=username, client_keys=[key], known_hosts=None,
            agent_path=None, keepalive_interval=30, login_timeout=15,
        ), 20)
    except (OSError, asyncssh.Error, TimeoutError) as e:
        raise ServerError(f"No se pudo conectar a {host}:{port}: {e.__class__.__name__}: {e}"
                          ) from e
    fp = conn.get_server_host_key().get_fingerprint()
    if expected_host_key and fp != expected_host_key:
        conn.close()
        raise ServerError(
            f"La huella del servidor cambió ({fp}, se esperaba {expected_host_key}). "
            "Si reinstalaste el servidor, bórrala desde la ficha para aceptar la nueva.", 409)
    return conn, fp


async def _conn(s: Server) -> asyncssh.SSHClientConnection:
    lock = _locks.setdefault(s.id, asyncio.Lock())
    async with lock:
        hit = _pool.get(s.id)
        if hit and hit.signature == _signature(s) and not hit.conn.is_closed():
            return hit.conn
        if hit:
            hit.conn.close()
        conn, fp = await connect_raw(s.host, s.port, s.username, _client_key(s), s.host_key)
        if not s.host_key:
            s.host_key = fp  # se persiste en quien llamó
        _pool[s.id] = _Conn(conn, _signature(s))
        return conn


async def run(s: Server, script: str, timeout: float = 40) -> str:
    """Ejecuta un script con `bash -s` (el script va por stdin: no queda en `ps`)."""
    for attempt in (1, 2):
        conn = await _conn(s)
        try:
            r = await asyncio.wait_for(conn.run("bash -s", input=script, check=False), timeout)
            return r.stdout or ""
        except (asyncssh.Error, OSError, BrokenPipeError) as e:
            _pool.pop(s.id, None)
            if attempt == 2:
                raise ServerError(f"Falló la ejecución remota: {e}") from e
        except TimeoutError as e:
            raise ServerError("El servidor tardó demasiado en responder") from e
    return ""


async def drop(server_id: int) -> None:
    hit = _pool.pop(server_id, None)
    if hit:
        hit.conn.close()


async def close_all() -> None:
    for sid in list(_pool):
        await drop(sid)


def _sections(out: str) -> dict[str, str]:
    parts: dict[str, list[str]] = {}
    current = "_"
    for line in out.splitlines():
        if line.startswith("@@") and line.endswith("@@") and len(line) > 4:
            current = line[2:-2]
            parts[current] = []
        else:
            parts.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip("\n") for k, v in parts.items()}


def _sudo(s: Server) -> str:
    return "sudo -n " if s.use_sudo else ""


# --- métricas -----------------------------------------------------------------------------
METRICS_SCRIPT = r"""
echo @@load@@; cat /proc/loadavg
echo @@cpu@@; head -1 /proc/stat; sleep 1; head -1 /proc/stat
echo @@mem@@; grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo
echo @@disk@@; df -P -B1 -x tmpfs -x devtmpfs -x squashfs -x overlay -x efivarfs 2>/dev/null
echo @@uptime@@; cat /proc/uptime
echo @@nproc@@; nproc
"""


def parse_metrics(out: str) -> dict[str, Any]:
    sec = _sections(out)
    m: dict[str, Any] = {}
    try:
        m["load1"] = float(sec.get("load", "0").split()[0])
    except (ValueError, IndexError):
        m["load1"] = None
    cpu_lines = [ln.split()[1:] for ln in sec.get("cpu", "").splitlines() if ln.startswith("cpu")]
    if len(cpu_lines) == 2:
        a, b = ([int(x) for x in ln] for ln in cpu_lines)
        idle = (b[3] + (b[4] if len(b) > 4 else 0)) - (a[3] + (a[4] if len(a) > 4 else 0))
        total = sum(b) - sum(a)
        m["cpu_pct"] = round(100 * (1 - idle / total), 1) if total > 0 else 0.0
    mem = {}
    for ln in sec.get("mem", "").splitlines():
        k, _, v = ln.partition(":")
        mem[k] = int(v.split()[0]) * 1024 if v.split() else 0
    if mem:
        m["mem_total"] = mem.get("MemTotal")
        m["mem_used"] = (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) or None
        m["swap_total"] = mem.get("SwapTotal")
        m["swap_used"] = mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)
    disks = []
    for ln in sec.get("disk", "").splitlines()[1:]:
        f = ln.split()
        if len(f) >= 6 and f[1].isdigit():
            disks.append({"fs": f[0], "total": int(f[1]), "used": int(f[2]), "mount": f[5]})
    m["disks"] = disks
    root = next((d for d in disks if d["mount"] == "/"), disks[0] if disks else None)
    if root:
        m["disk_total"], m["disk_used"] = root["total"], root["used"]
    try:
        m["uptime_s"] = int(float(sec.get("uptime", "0").split()[0]))
    except (ValueError, IndexError):
        pass
    try:
        m["cores"] = int(sec.get("nproc", "").strip())
    except ValueError:
        pass
    return m


# --- foto del sistema (detalle) -------------------------------------------------------------
def snapshot_script(s: Server) -> str:
    sudo = _sudo(s)
    return f"""
echo @@os@@; grep -E '^(PRETTY_NAME|VERSION_ID|ID)=' /etc/os-release; uname -r; hostname
echo @@reboot@@; test -f /var/run/reboot-required && echo yes || echo no
echo @@updates@@; (apt list --upgradable 2>/dev/null | tail -n +2 | wc -l) 2>/dev/null
echo @@security@@; (apt list --upgradable 2>/dev/null | grep -ci -- '-security') 2>/dev/null
echo @@ports@@; {sudo}ss -ltnupH 2>/dev/null || ss -ltnuH
echo @@procs@@; ps -eo pid,user,pcpu,rss,etimes,comm --sort=-rss --no-headers | head -15
echo @@docker@@; command -v docker >/dev/null && \
  {sudo}docker ps -a --format '{{{{json .}}}}' 2>/dev/null
echo @@failed@@; systemctl --failed --no-legend --plain 2>/dev/null
echo @@units@@; systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null
echo @@ufw@@; {sudo}ufw status 2>/dev/null | head -40
echo @@sshfail@@
if [ "$(id -u)" = 0 ] || id -nG | grep -qwE 'adm|systemd-journal' || [ -n "{sudo}" ]; then
  {sudo}journalctl -u ssh -u sshd --since -24h --no-pager -q 2>/dev/null \
    | grep -cE 'Failed|Invalid user' || true
else
  echo na
fi
echo @@sudo@@; sudo -n true 2>/dev/null && echo yes || echo no
echo @@tailscale@@; command -v tailscale >/dev/null && tailscale ip -4 2>/dev/null | head -1
echo @@who@@; who 2>/dev/null | head -10
echo @@publicip@@; ip -4 -o addr show scope global 2>/dev/null | awk '{{print $4}}' | cut -d/ -f1
"""


def _exposure(addr: str) -> str:
    host = addr.rsplit(":", 1)[0].strip("[]")
    if host.endswith("%lo") or host.startswith("127.") or host in ("::1", "localhost") \
            or host.startswith("127.0.0.53"):
        return "local"
    if host.startswith("100.") or host.startswith("fd7a:115c"):
        return "tailscale"
    if host in ("0.0.0.0", "*", "::", "[::]", ""):
        return "all"
    if host.startswith(("10.", "192.168.", "172.")):
        return "private"
    return "public"


def parse_snapshot(out: str) -> dict[str, Any]:
    sec = _sections(out)
    os_lines = sec.get("os", "").splitlines()
    osr = dict(ln.split("=", 1) for ln in os_lines if "=" in ln)
    rest = [ln for ln in os_lines if "=" not in ln]
    ufw_txt = sec.get("ufw", "")
    ufw_active = "Status: active" in ufw_txt
    ufw_allowed: set[str] = set()
    for ln in ufw_txt.splitlines():
        if "ALLOW" in ln:
            port = ln.split()[0].split("/")[0]
            ufw_allowed.add(port)
    ports = []
    seen = set()
    for ln in sec.get("ports", "").splitlines():
        f = ln.split()
        if len(f) < 5:
            continue
        proto, local = f[0], f[4]
        port = local.rsplit(":", 1)[-1]
        proc = ""
        m = re.search(r'users:\(\("([^"]+)"', ln)
        if m:
            proc = m.group(1)
        exp = _exposure(local)
        key = (proto, port, exp, proc)
        if key in seen:
            continue
        seen.add(key)
        # Docker publica con reglas de iptables que van ANTES que ufw: docker-proxy queda
        # expuesto aunque ufw no lo permita.
        internet = exp in ("all", "public") and (
            not ufw_active or port in ufw_allowed or proc == "docker-proxy")
        ports.append({"proto": proto, "address": local, "port": port, "process": proc,
                      "exposure": exp, "internet": internet})
    ports.sort(key=lambda p: (not p["internet"], p["exposure"], int(p["port"])
                              if p["port"].isdigit() else 0))
    procs = []
    for ln in sec.get("procs", "").splitlines():
        f = ln.split(None, 5)
        if len(f) == 6:
            procs.append({"pid": int(f[0]), "user": f[1], "cpu": float(f[2]),
                          "rss": int(f[3]) * 1024, "elapsed_s": int(f[4]), "command": f[5]})
    containers = []
    for ln in sec.get("docker", "").splitlines():
        try:
            d = json.loads(ln)
            containers.append({"name": d.get("Names"), "image": d.get("Image"),
                               "status": d.get("Status"), "state": d.get("State"),
                               "ports": d.get("Ports")})
        except json.JSONDecodeError:
            pass
    failed = [ln.split()[0] for ln in sec.get("failed", "").splitlines() if ln.strip()]
    units = [ln.split()[0] for ln in sec.get("units", "").splitlines() if ln.strip()]

    def _int(v):
        try:
            return int(v.strip().splitlines()[-1])
        except (ValueError, IndexError, AttributeError):
            return None

    return {
        "os": osr.get("PRETTY_NAME", "").strip('"'),
        "os_id": osr.get("ID", "").strip('"'),
        "os_version": osr.get("VERSION_ID", "").strip('"'),
        "kernel": rest[0] if rest else None,
        "hostname": rest[1] if len(rest) > 1 else None,
        "reboot_required": sec.get("reboot", "").strip() == "yes",
        "updates": _int(sec.get("updates", "")),
        "security_updates": _int(sec.get("security", "")),
        "ports": ports,
        "processes": procs,
        "containers": containers,
        "failed_units": failed,
        "running_units": units,
        "ufw": {"active": ufw_active, "rules": ufw_txt} if ufw_txt else None,
        "ssh_failed_24h": _int(sec.get("sshfail", "")),
        "sudo": sec.get("sudo", "").strip() == "yes",
        "tailscale_ip": sec.get("tailscale", "").strip() or None,
        "sessions": [ln for ln in sec.get("who", "").splitlines() if ln.strip()],
        "public_ips": [ip for ip in sec.get("publicip", "").split()
                       if _exposure(f"{ip}:0") == "public"],
    }


async def verify_exposure(snap: dict, vantage: Server | None) -> dict:
    """Prueba los puertos que el servidor cree expuestos conectando a su IP pública desde OTRO
    servidor monitoreado: un firewall del proveedor no se ve desde adentro, y el equipo donde
    corre el panel no sirve de punto de vista (su red puede cortar salidas)."""
    ips = snap.get("public_ips") or []
    targets = [p for p in snap["ports"] if p["internet"] and p["proto"].startswith("tcp")]
    if not ips or not targets or vantage is None:
        return snap
    ip = shlex.quote(ips[0])
    script = "".join(
        f"nc -z -w 4 {ip} {int(p['port'])} >/dev/null 2>&1 && echo {int(p['port'])} open "
        f"|| echo {int(p['port'])} closed\n" for p in targets)
    try:
        out = await run(vantage, script, timeout=60)
    except ServerError:
        return snap
    res = dict(ln.split() for ln in out.splitlines() if len(ln.split()) == 2)
    for p in targets:
        r = res.get(p["port"])
        if r is None:
            continue
        p["verified"] = "open" if r == "open" else "filtered"
        if r != "open":
            p["internet"] = False
    snap["exposure_checked_from"] = f"{vantage.name} → {ips[0]}"
    return snap


_SYSTEM_UNITS = re.compile(
    r"^(ssh|sshd|cron|dbus|systemd-|getty|serial-getty|polkit|rsyslog|snapd|udisks|"
    r"multipathd|packagekit|networkd-dispatcher|unattended-upgrades|user@|accounts-daemon|"
    r"irqbalance|chrony|ntp|fwupd|thermald|ModemManager|wpa_supplicant|atd|lvm2|"
    r"droplet-agent|do-agent|qemu-guest|open-vm|cloud-|containerd|upower|"
    r"tailscaled|fail2ban|ufw|apport|smartd|boltd|rtkit|avahi|cups|colord|gdm|"
    r"blk-availability|finalrd|lxd|iscsid|plymouth|console|setvtrgb|kmod|keyboard|"
    r"promtail|node_exporter|grafana-agent|amazon-ssm|snap\.)")


def suggestions(snap: dict, existing: list[Service]) -> list[dict]:
    """Servicios detectados en la foto del sistema que todavía no están registrados."""
    have_units = {json.loads(s.config_json or "{}").get("unit") for s in existing}
    have_containers = {json.loads(s.config_json or "{}").get("container") for s in existing}
    have_kinds = {s.kind for s in existing}
    out = []
    for unit in snap.get("running_units", []):
        name = unit.removesuffix(".service")
        if _SYSTEM_UNITS.match(name) or unit in have_units or name in have_units:
            continue
        lower = name.lower()
        if lower.startswith("redis") and "redis" not in have_kinds:
            out.append({"name": "Redis", "kind": "redis",
                        "config": {"host": "127.0.0.1", "port": 6379, "db": 0},
                        "log": {"type": "journal", "unit": name}})
        elif lower.startswith("postgresql") and "postgres" not in have_kinds:
            if lower == "postgresql":
                continue  # el wrapper; el real es postgresql@<ver>-main
            out.append({"name": "PostgreSQL", "kind": "postgres", "config": {"mode": "local"},
                        "log": {"type": "journal", "unit": name}})
        elif lower.startswith("rabbitmq") and "rabbitmq" not in have_kinds:
            out.append({"name": "RabbitMQ", "kind": "rabbitmq", "config": {},
                        "log": {"type": "journal", "unit": name}})
        else:
            out.append({"name": name, "kind": "systemd", "config": {"unit": name},
                        "log": {"type": "journal", "unit": name}})
    for c in snap.get("containers", []):
        if c["name"] and c["name"] not in have_containers:
            out.append({"name": c["name"], "kind": "docker", "config": {"container": c["name"]},
                        "log": {"type": "docker", "container": c["name"]}})
    return out


# --- chequeo de servicios -------------------------------------------------------------------
def _redis_cli(cfg: dict, password: str | None) -> tuple[str, str]:
    """Prefijo de export (clave por env, no por argumento) + comando redis-cli."""
    exports = f"export REDISCLI_AUTH={shlex.quote(password)}\n" if password else ""
    tls = " --tls" if cfg.get("tls") else ""
    cmd = (f"redis-cli --no-auth-warning -h {shlex.quote(cfg['host'])} -p {int(cfg['port'])}"
           f" -n {int(cfg.get('db') or 0)}{tls}")
    return exports, cmd


def check_script(s: Server, svc: Service, cfg: dict, password: str | None) -> str | None:
    sudo = _sudo(s)
    k = svc.kind
    if k == "systemd" or (k == "sidekiq" and cfg.get("unit")):
        unit = shlex.quote(cfg["unit"])
        base = (f"echo @@unit@@; systemctl show {unit} --no-pager -p ActiveState -p SubState "
                "-p MainPID -p ActiveEnterTimestamp -p NRestarts -p MemoryCurrent -p Result "
                "-p LoadState\n")
        if k == "systemd":
            return base
    else:
        base = ""
    if k == "docker":
        return (f"echo @@docker@@; {sudo}docker inspect --format '{{{{json .State}}}}' "
                f"{shlex.quote(cfg['container'])} 2>&1\n")
    if k == "redis":
        exports, cli = _redis_cli(cfg, password)
        return exports + f"echo @@info@@; {cli} INFO 2>&1\necho @@ping@@; {cli} PING 2>&1\n"
    if k == "sidekiq":
        exports, cli = _redis_cli(cfg, password)
        ns = shlex.quote(cfg.get("namespace") or "")
        return exports + base + f"""NS={ns}
echo @@ping@@; {cli} PING 2>&1
R="{cli}"
echo @@queues@@
for q in $($R SMEMBERS "${{NS}}queues"); do echo "$q $($R LLEN "${{NS}}queue:$q")"; done
echo @@sets@@
for z in retry dead schedule; do echo "$z $($R ZCARD "${{NS}}$z")"; done
echo @@stats@@
echo "processed $($R GET "${{NS}}stat:processed")"; echo "failed $($R GET "${{NS}}stat:failed")"
echo @@procs@@
for p in $($R SMEMBERS "${{NS}}processes"); do echo "$p $($R HGET "${{NS}}$p" busy)"; done
"""
    if k == "postgres":
        sql = ("select current_setting('server_version'), (select count(*) from "
               "pg_stat_activity), current_setting('max_connections'), (select coalesce("
               "json_agg(json_build_object('db', datname, 'size', pg_database_size(datname)) "
               "order by pg_database_size(datname) desc), '[]') from pg_database where not "
               "datistemplate)")
        if cfg.get("mode") == "remote" and not password:
            # sin clave: solo disponibilidad (pg_isready no autentica)
            return (f"echo @@ready@@; pg_isready -h {shlex.quote(cfg['host'])} "
                    f"-p {int(cfg['port'])} -d {shlex.quote(cfg['database'])} "
                    f"-U {shlex.quote(cfg['user'])} 2>&1\n")
        if cfg.get("mode") == "remote":
            exports = f"export PGPASSWORD={shlex.quote(password)}\n"
            return exports + (
                f"echo @@pg@@; psql -XAtq -F '|' -h {shlex.quote(cfg['host'])} "
                f"-p {int(cfg['port'])} -U {shlex.quote(cfg['user'])} "
                f"-d {shlex.quote(cfg['database'])} -c {shlex.quote(sql)} 2>&1\n")
        return (f"echo @@pg@@; {sudo}-u postgres psql -XAtq -F '|' -c {shlex.quote(sql)} "
                "2>&1\necho @@ready@@; pg_isready 2>&1\n") if sudo else (
                "echo @@ready@@; pg_isready 2>&1\n")
    if k == "rabbitmq":
        return (f"echo @@queues@@; {sudo}rabbitmqctl -q list_queues name messages consumers "
                "2>&1 | head -200\n")
    if k == "http" and cfg.get("from_server"):
        return (f"echo @@http@@; curl -s -o /dev/null -m 15 -w '%{{http_code}} %{{time_total}}' "
                f"{shlex.quote(cfg['url'])}\n")
    if k == "tcp":
        return f"echo @@tcp@@; ss -ltnH '( sport = :{int(cfg['port'])} )' | wc -l\n"
    if k == "process":
        return f"echo @@proc@@; pgrep -fc -- {shlex.quote(cfg['pattern'])}\n"
    if k == "log":
        lg = json.loads(svc.log_json or "{}")
        if lg.get("type") == "file":
            p = shlex.quote(lg["path"])
            return f"echo @@file@@; {sudo}stat -c '%s %Y' {p} 2>&1\n"
        return None
    return None


def _kv(txt: str) -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in txt.splitlines() if "=" in ln)


def _systemd_result(sec: dict) -> tuple[str, str, dict]:
    u = _kv(sec.get("unit", ""))
    if u.get("LoadState") == "not-found":
        return "down", "La unidad no existe", u
    active = u.get("ActiveState")
    mem = u.get("MemoryCurrent")
    detail = {"active": active, "sub": u.get("SubState"), "pid": u.get("MainPID"),
              "since": u.get("ActiveEnterTimestamp"), "restarts": u.get("NRestarts"),
              "memory": int(mem) if mem and mem.isdigit() else None, "result": u.get("Result")}
    if active == "active":
        return "ok", f"{u.get('SubState')} desde {u.get('ActiveEnterTimestamp') or '?'}", detail
    if active in ("activating", "reloading"):
        return "warn", active, detail
    return "down", f"{active or 'desconocido'} ({u.get('Result')})", detail


def interpret(svc: Service, cfg: dict, out: str) -> tuple[str, str, dict]:
    sec = _sections(out)
    k = svc.kind
    if k == "systemd":
        return _systemd_result(sec)
    if k == "docker":
        raw = sec.get("docker", "")
        try:
            st = json.loads(raw.splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return "down", raw[:200] or "Sin respuesta de docker", {}
        health = (st.get("Health") or {}).get("Status")
        detail = {"status": st.get("Status"), "running": st.get("Running"),
                  "restarts": st.get("RestartCount"), "started_at": st.get("StartedAt"),
                  "health": health, "oom": st.get("OOMKilled"), "exit_code": st.get("ExitCode")}
        if st.get("Running") and health in (None, "healthy"):
            return "ok", f"running{' · ' + health if health else ''}", detail
        if st.get("Running"):
            return "warn", f"running · {health}", detail
        return "down", f"{st.get('Status')} (exit {st.get('ExitCode')})", detail
    if k == "redis":
        if "PONG" not in sec.get("ping", ""):
            return "down", (sec.get("ping") or sec.get("info") or "sin respuesta")[:200], {}
        info = dict(ln.split(":", 1) for ln in sec.get("info", "").splitlines()
                    if ":" in ln and not ln.startswith("#"))
        keys = {k2: v for k2, v in info.items() if re.match(r"^db\d+$", k2)}
        detail = {"version": info.get("redis_version"), "role": info.get("role"),
                  "memory": info.get("used_memory_human"),
                  "max_memory": info.get("maxmemory_human"),
                  "clients": info.get("connected_clients"), "ops": info.get(
                      "instantaneous_ops_per_sec"), "uptime_days": info.get("uptime_in_days"),
                  "evicted": info.get("evicted_keys"), "keyspace": keys}
        return "ok", f"{detail['memory']} · {detail['clients']} clientes", detail
    if k == "sidekiq":
        status, summary, detail = ("ok", "", {})
        if cfg.get("unit"):
            status, summary, detail = _systemd_result(sec)
        if "PONG" not in sec.get("ping", ""):
            return "down", "Redis de Sidekiq no responde", detail
        queues = {}
        for ln in sec.get("queues", "").splitlines():
            f = ln.split()
            if len(f) == 2 and f[1].isdigit():
                queues[f[0]] = int(f[1])
        sets = {f[0]: int(f[1]) for f in (ln.split() for ln in sec.get("sets", "").splitlines())
                if len(f) == 2 and f[1].isdigit()}
        stats = {f[0]: int(f[1]) for f in (ln.split() for ln in sec.get("stats", "").splitlines())
                 if len(f) == 2 and f[1].isdigit()}
        procs = [ln.split() for ln in sec.get("procs", "").splitlines() if ln.strip()]
        busy = sum(int(p[1]) for p in procs if len(p) == 2 and p[1].isdigit())
        enqueued = sum(queues.values())
        detail = {**detail, "queues": queues, "enqueued": enqueued, "processes": len(procs),
                  "busy": busy, **sets, **stats}
        if status == "ok" and not procs:
            status = "warn"
        summary = (f"{enqueued} en cola · {busy} ocupados · {len(procs)} procesos"
                   f" · {sets.get('retry', 0)} reintentos · {sets.get('dead', 0)} muertos")
        return status, summary, detail
    if k == "postgres":
        pg = sec.get("pg", "")
        ready = sec.get("ready", "")
        if pg and "|" in pg.splitlines()[0]:
            ver, conns, maxc, dbs = pg.splitlines()[0].split("|", 3)
            try:
                dbs_list = json.loads(dbs)
            except json.JSONDecodeError:
                dbs_list = []
            detail = {"version": ver, "connections": int(conns), "max_connections": int(maxc),
                      "databases": dbs_list}
            status = "warn" if int(conns) > 0.8 * int(maxc) else "ok"
            return status, f"{conns}/{maxc} conexiones · {len(dbs_list)} bases", detail
        if "accepting connections" in ready:
            return "ok", "acepta conexiones", {}
        return "down", (pg or ready or "sin respuesta")[:200], {}
    if k == "rabbitmq":
        txt = sec.get("queues", "")
        if "Error" in txt or "error" in txt[:200]:
            return "down", txt[:200], {}
        queues = []
        for ln in txt.splitlines():
            f = ln.split("\t") if "\t" in ln else ln.split()
            if len(f) >= 3 and f[1].isdigit():
                queues.append({"name": f[0], "messages": int(f[1]), "consumers": int(f[2])})
        stuck = [q for q in queues if q["messages"] > 0 and q["consumers"] == 0]
        pending = sum(q["messages"] for q in queues)
        status = "warn" if stuck else "ok"
        return status, f"{len(queues)} colas · {pending} mensajes · {len(stuck)} sin consumidor", \
            {"queues": sorted(queues, key=lambda q: -q["messages"])[:50], "stuck": stuck}
    if k == "http":
        parts = sec.get("http", "").split()
        if len(parts) == 2 and parts[0].isdigit():
            code, secs = int(parts[0]), float(parts[1])
            ok = code == int(cfg.get("expect") or 200)
            return ("ok" if ok else "down"), f"HTTP {code} · {int(secs * 1000)} ms", \
                {"code": code, "latency_ms": int(secs * 1000)}
        return "down", "sin respuesta", {}
    if k == "tcp":
        n = sec.get("tcp", "0").strip()
        return ("ok", f"escuchando en :{cfg['port']}", {}) if n.isdigit() and int(n) > 0 else \
            ("down", f"nada escucha en :{cfg['port']}", {})
    if k == "process":
        n = sec.get("proc", "0").strip()
        return ("ok", f"{n} procesos", {"count": int(n)}) if n.isdigit() and int(n) > 0 else \
            ("down", "no hay procesos", {"count": 0})
    if k == "log":
        f = sec.get("file", "").split()
        if len(f) == 2 and f[0].isdigit():
            age = int(time.time()) - int(f[1])
            return "ok", f"{int(f[0]) // 1024} KB · escrito hace {age // 60} min", \
                {"size": int(f[0]), "age_s": age}
        return "down", (sec.get("file") or "no existe")[:200], {}
    return "unknown", "", {}


async def http_check_from_hub(cfg: dict) -> tuple[str, str, dict]:
    url = cfg["url"]
    t = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "pipelines-hub"})
    except httpx.HTTPError as e:
        return "down", f"{e.__class__.__name__}", {}
    ms = int((time.monotonic() - t) * 1000)
    detail: dict[str, Any] = {"code": r.status_code, "latency_ms": ms}
    u = urlparse(url)
    if u.scheme == "https":
        try:
            days = await asyncio.to_thread(_cert_days, u.hostname, u.port or 443)
            detail["cert_days"] = days
        except Exception:
            pass
    ok = r.status_code == int(cfg.get("expect") or 200)
    status = "ok" if ok else "down"
    if ok and detail.get("cert_days") is not None and detail["cert_days"] < 14:
        status = "warn"
    extra = f" · cert {detail['cert_days']} d" if detail.get("cert_days") is not None else ""
    return status, f"HTTP {r.status_code} · {ms} ms{extra}", detail


def _cert_days(host: str, port: int) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=8) as sock, \
            ctx.wrap_socket(sock, server_hostname=host) as ss:
        cert = ss.getpeercert()
    exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    return (exp - datetime.now(UTC)).days


async def check_service(s: Server, svc: Service) -> tuple[str, str, dict, int | None]:
    cfg = json.loads(svc.config_json or "{}")
    password = decrypt(svc.secret_enc) if svc.secret_enc else None
    t = time.monotonic()
    if svc.kind == "http" and not cfg.get("from_server"):
        status, summary, detail = await http_check_from_hub(cfg)
        return status, summary, detail, detail.get("latency_ms")
    script = check_script(s, svc, cfg, password)
    if script is None:
        return "unknown", "Sin chequeo para este tipo", {}, None
    out = await run(s, script, timeout=30)
    status, summary, detail = interpret(svc, cfg, out)
    return status, summary, detail, int((time.monotonic() - t) * 1000)


# --- logs -----------------------------------------------------------------------------------
def log_script(s: Server, lg: dict, lines: int, cursor: str | None, grep: str | None) -> str:
    sudo = _sudo(s)
    lines = min(max(int(lines or 500), 10), 5000)
    g = shlex.quote(grep) if grep else None
    t = lg.get("type")
    if t == "journal":
        unit = shlex.quote(lg["unit"])
        where = f"--after-cursor {shlex.quote(cursor)}" if cursor else f"-n {lines}"
        grep_arg = f" --grep {g}" if g else ""
        return (f"{sudo}journalctl -u {unit} --no-pager -o short-iso --show-cursor {where}"
                f"{grep_arg} 2>&1 | tail -n 20000\n")
    if t == "file":
        p = shlex.quote(lg["path"])
        if cursor and cursor.isdigit():
            return f"""SIZE=$({sudo}stat -c %s {p} 2>/dev/null || echo 0)
OFF={int(cursor)}
if [ "$SIZE" -lt "$OFF" ]; then OFF=0; fi
echo "@@size@@"; echo $SIZE
echo "@@text@@"; {sudo}tail -c +$((OFF+1)) {p} | head -c 2000000
"""
        filt = f" | grep -i -- {g}" if g else ""
        return (f"echo @@size@@; {sudo}stat -c %s {p} 2>&1\necho @@text@@; "
                f"{sudo}tail -n {lines if not g else 50000} {p} 2>&1{filt} | tail -n {lines}\n")
    if t == "docker":
        c = shlex.quote(lg["container"])
        since = f"--since {shlex.quote(cursor)}" if cursor else f"--tail {lines}"
        filt = f" | grep -i -- {g}" if g else ""
        return (f"echo @@now@@; date -u +%Y-%m-%dT%H:%M:%S.%NZ\necho @@text@@; "
                f"{sudo}docker logs --timestamps {since} {c} 2>&1{filt} | tail -n 20000\n")
    raise ServerError("El servicio no tiene log configurado", 422)


async def read_log(s: Server, svc: Service, lines: int = 500, cursor: str | None = None,
                   grep: str | None = None) -> dict[str, Any]:
    lg = json.loads(svc.log_json or "{}")
    if lg.get("type") in (None, "none"):
        raise ServerError("El servicio no tiene log configurado", 422)
    out = await run(s, log_script(s, lg, lines, cursor, grep), timeout=40)
    t = lg["type"]
    if t == "journal":
        new_cursor = cursor
        text_lines = []
        for ln in out.splitlines():
            if ln.startswith("-- cursor: "):
                new_cursor = ln[len("-- cursor: "):].strip()
            elif ln.startswith("-- No entries --"):
                continue
            else:
                text_lines.append(ln)
        text = "\n".join(text_lines)
        if "sudo:" in text[:200] and "password" in text[:300]:
            return {"text": "", "cursor": cursor, "append": bool(cursor), "available": False,
                    "message": "Para leer el journal hace falta sudo sin clave o que el usuario "
                               "esté en el grupo systemd-journal/adm."}
        return {"text": text + ("\n" if text else ""), "cursor": new_cursor,
                "append": bool(cursor), "available": True}
    sec = _sections(out)
    if t == "file":
        size = sec.get("size", "").strip()
        if not size.isdigit():
            return {"text": "", "cursor": cursor, "append": False, "available": False,
                    "message": (size or "No se pudo leer el archivo")[:300]}
        text = sec.get("text", "")
        return {"text": text + ("\n" if text and not text.endswith("\n") else ""),
                "cursor": size, "append": bool(cursor), "available": True}
    now = sec.get("now", "").strip() or cursor
    text = sec.get("text", "")
    return {"text": text + ("\n" if text else ""), "cursor": now, "append": bool(cursor),
            "available": True}


# --- poller --------------------------------------------------------------------------------
class InfraPoller:
    def __init__(self):
        self.settings = get_settings()
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._sem = asyncio.Semaphore(4)
        self._last_prune = 0.0

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="infra-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await close_all()

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("infra tick falló")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(),
                                       timeout=self.settings.server_sample_interval)
            except TimeoutError:
                pass

    async def tick(self) -> None:
        async with SessionLocal() as s:
            ids = (await s.execute(select(Server.id))).scalars().all()
        await asyncio.gather(*(self._guard(self.poll_server, i) for i in ids))
        if time.time() - self._last_prune > 3600:
            await self.prune()
            self._last_prune = time.time()

    async def _guard(self, fn, *args):
        async with self._sem:
            try:
                await fn(*args)
            except Exception:
                log.exception("poll de servidor falló")

    async def poll_server(self, server_id: int) -> None:
        async with SessionLocal() as s:
            srv = await s.get(Server, server_id, options=[selectinload(Server.services)])
            if not srv:
                return
            now = utcnow()
            try:
                out = await run(srv, METRICS_SCRIPT, timeout=30)
                m = parse_metrics(out)
                s.add(ServerSample(
                    server_id=srv.id, ts=now, cpu_pct=m.get("cpu_pct"), load1=m.get("load1"),
                    cores=m.get("cores"), mem_total=m.get("mem_total"),
                    mem_used=m.get("mem_used"), swap_total=m.get("swap_total"),
                    swap_used=m.get("swap_used"), disk_total=m.get("disk_total"),
                    disk_used=m.get("disk_used"), uptime_s=m.get("uptime_s"),
                    disks_json=json.dumps(m.get("disks") or []),
                ))
                srv.status, srv.last_error, srv.last_seen_at = "ok", None, now
            except ServerError as e:
                srv.status, srv.last_error = "error", e.message
                for svc in srv.services:
                    if svc.kind != "http" or json.loads(svc.config_json or "{}").get(
                            "from_server"):
                        self._record(s, svc, "unknown", "Servidor inalcanzable", {}, None, now)
                await s.commit()
                return
            results = await asyncio.gather(*(self._check(srv, svc) for svc in srv.services),
                                           return_exceptions=True)
            for svc, res in zip(srv.services, results, strict=True):
                if isinstance(res, Exception):
                    msg = getattr(res, "message", str(res))
                    self._record(s, svc, "unknown", msg[:300], {}, None, now)
                else:
                    self._record(s, svc, *res, now)
            await s.commit()

    async def _check(self, srv: Server, svc: Service):
        return await check_service(srv, svc)

    @staticmethod
    def _record(s, svc: Service, status: str, summary: str, detail: dict,
                latency: int | None, now: datetime) -> None:
        if svc.status != status:
            svc.changed_at = now
        svc.status, svc.summary, svc.checked_at = status, summary, now
        svc.detail_json = json.dumps(detail)
        s.add(ServiceCheck(service_id=svc.id, ts=now, status=status, latency_ms=latency))

    async def prune(self) -> None:
        cutoff = utcnow() - timedelta(days=self.settings.server_history_days)
        async with SessionLocal() as s:
            await s.execute(delete(ServerSample).where(ServerSample.ts < cutoff))
            await s.execute(delete(ServiceCheck).where(
                ServiceCheck.ts < utcnow() - timedelta(days=2)))
            await s.commit()


poller = InfraPoller()
