"""Servidor MCP (Streamable HTTP en /mcp) sobre las mismas cuentas del panel.

Así Claude puede consultar pipelines de GitHub y Bitbucket sin tener los tokens:
viven cifrados en el servicio.
"""

from __future__ import annotations

import re
from typing import Any

from fastmcp import FastMCP

from app import service

mcp = FastMCP(
    name="pipelines-hub",
    instructions=(
        "Ejecuciones de CI/CD (GitHub Actions y Bitbucket Pipelines) de las cuentas "
        "configuradas en Pipelines Hub. Usa list_runs para ubicar una ejecución, get_run "
        "para ver sus jobs/steps y get_step_log para leer el log de uno. list_deployments "
        "muestra qué hay desplegado en cada entorno. list_prs / get_pr / pr_diff cubren los "
        "pull requests (por revisar, míos, abiertos, cerrados) y comment_pr / approve_pr / "
        "merge_pr actúan sobre ellos: confirma con el usuario antes de aprobar o mergear."
    ),
)


@mcp.tool
async def list_runs(
    status: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    provider: str | None = None,
    query: str | None = None,
    limit: int = 20,
    view: str | None = None,
) -> list[dict[str, Any]]:
    """Lista ejecuciones recientes, las más nuevas primero.

    Args:
        view: nombre de una vista guardada en el panel (ver list_views); se combina con el resto.
        status: active | success | failed | cancelled | queued | running | waiting
            (se pueden combinar con coma, ej. "failed,cancelled").
        repo: parte del nombre del repo (ej. "contable-back").
        branch: rama exacta.
        provider: github | bitbucket.
        query: texto libre sobre título del commit, workflow, rama, autor o SHA.
        limit: máximo de resultados (default 20).
    """
    return await service.list_runs(status=status, repo=repo, branch=branch, provider=provider,
                                   q=query, limit=limit, view=view)


@mcp.tool
async def list_views(scope: str | None = None) -> list[dict[str, Any]]:
    """Vistas guardadas por el usuario en el panel. scope: runs | prs | deployments (todas si
    se omite). Se usan pasando su nombre a list_runs(view=), list_prs(saved_view=) o
    list_deployments(view=)."""
    return await service.list_views(scope)


@mcp.tool
async def get_run(run_id: int) -> dict[str, Any]:
    """Detalle de una ejecución (por su id del panel) con sus jobs/steps y estados."""
    return await service.get_run_detail(run_id)


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@mcp.tool
async def get_step_log(run_id: int, step_id: str, tail_lines: int = 200,
                       grep: str | None = None) -> str:
    """Log de un job (GitHub) o step (Bitbucket) de una ejecución.

    Args:
        run_id: id de la ejecución en el panel.
        step_id: id del job/step, tal como viene en get_run().steps[].id.
        tail_lines: cuántas líneas finales devolver (default 200).
        grep: si viene, devuelve solo las líneas que contienen este texto (sin mayúsculas).
    """
    chunk = await service.get_step_log(run_id, step_id)
    if not chunk["available"]:
        return chunk["message"] or "Log no disponible"
    lines = _ANSI.sub("", chunk["text"]).splitlines()
    if grep:
        g = grep.lower()
        lines = [f"{i + 1}: {line}" for i, line in enumerate(lines) if g in line.lower()]
    return "\n".join(lines[-tail_lines:])


@mcp.tool
async def list_deployments(repo: str | None = None, view: str | None = None
                           ) -> list[dict[str, Any]]:
    """Último despliegue por entorno (production, staging, ...) de cada repo seguido.
    view: nombre de una vista de Entornos guardada en el panel."""
    return await service.list_deployments(repo=repo, view=view)


@mcp.tool
async def rerun(run_id: int, failed_only: bool = False) -> dict[str, Any]:
    """Re-ejecuta una ejecución. failed_only solo aplica a GitHub."""
    return await service.rerun_run(run_id, failed_only)


@mcp.tool
async def cancel(run_id: int) -> dict[str, Any]:
    """Cancela (GitHub) o detiene (Bitbucket) una ejecución en curso."""
    return await service.cancel_run(run_id)


@mcp.tool
async def list_prs(view: str = "open", repo: str | None = None, query: str | None = None,
                   saved_view: str | None = None) -> dict[str, Any]:
    """Pull requests de los repos seguidos.

    Args:
        view: review (me piden revisión) | mine (míos abiertos) | open | closed (7 días).
        repo: parte del nombre del repo.
        query: texto sobre título, autor o rama.
        saved_view: nombre de una vista de PR guardada en el panel (ver list_views).
    """
    data = await service.list_prs(view, repo=repo, q=query, limit=50, saved_view=saved_view)
    for item in data["items"]:
        item.pop("reviewers", None)
    return data


@mcp.tool
async def get_pr(pr_id: int) -> dict[str, Any]:
    """Detalle de un PR: descripción, revisores, checks, commits, comentarios y archivos
    (sin el diff; para el diff usa pr_diff)."""
    data = await service.get_pr_detail(pr_id)
    for f in data.get("files", []):
        f.pop("patch", None)
    return data


@mcp.tool
async def pr_diff(pr_id: int, path: str | None = None, max_chars: int = 40000) -> str:
    """Diff unificado de un PR, completo o de un solo archivo (path exacto)."""
    data = await service.get_pr_detail(pr_id)
    parts = []
    for f in data.get("files", []):
        if path and f["path"] != path:
            continue
        parts.append(f"--- {f['path']} ({f['status']}, +{f['additions']} -{f['deletions']})\n"
                     f"{f.get('patch') or '(sin diff disponible)'}")
    text = "\n\n".join(parts) or "Sin archivos"
    return text[:max_chars] + ("\n… (truncado)" if len(text) > max_chars else "")


@mcp.tool
async def comment_pr(pr_id: int, body: str) -> dict[str, Any]:
    """Deja un comentario general en el PR."""
    return await service.pr_action(pr_id, "comment", body)


@mcp.tool
async def approve_pr(pr_id: int) -> dict[str, Any]:
    """Aprueba el PR con la cuenta configurada."""
    return await service.pr_action(pr_id, "approve")


@mcp.tool
async def merge_pr(pr_id: int, strategy: str = "merge", close_source_branch: bool = False
                   ) -> dict[str, Any]:
    """Mergea el PR. strategy: merge | squash | rebase (en Bitbucket, rebase = fast-forward)."""
    return await service.pr_action(pr_id, "merge", strategy=strategy,
                                   close_source_branch=close_source_branch)
