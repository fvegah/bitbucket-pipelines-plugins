# Pipelines Hub

Panel local para el día a día con **GitHub**, **Bitbucket** y **Cloudflare** (Workers Builds y Pages), de varias cuentas y organizaciones
a la vez: ejecuciones de pipelines, jobs/steps, logs (en vivo en Bitbucket), re-ejecutar/cancelar,
qué hay desplegado en cada entorno y **pull requests** (por revisar, míos, abiertos, cerrados) con
diff, comentarios, checks, aprobar/pedir cambios/mergear. Trae además un servidor **MCP** para
que Claude consulte lo mismo sin tener los tokens.

```
┌──────────── contenedor (OrbStack) ────────────┐
│  Vue (estático)   FastAPI /api   MCP /mcp      │
│                        │                       │
│        poller ─────────┤── SQLite (/data)      │  tokens cifrados con Fernet
│          │             │                       │
└──────────┼─────────────┼───────────────────────┘
           ▼             ▼
    api.github.com   api.bitbucket.org/2.0
```

## Levantar

```bash
cd pipelines-hub
docker compose up -d --build
```

- **https://pipelines.orb.local** (dominio de OrbStack) o **http://localhost:8095**
- Datos en el volumen `pipelines-hub_hub-data` (base SQLite + `secret.key`). Si se pierde la
  clave, hay que volver a cargar los tokens.

Luego, en **Cuentas → Agregar cuenta**:

| Proveedor | Credencial | Permisos |
|-----------|------------|----------|
| GitHub | Personal access token (`gh auth token` sirve) | classic: `repo`, `read:org` (+`workflow` para re-ejecutar). Fine-grained: Actions y Deployments de lectura (escritura en Actions para re-ejecutar/cancelar) |
| Cloudflare | API token **de usuario** (My Profile → API Tokens → Custom token; la API de Workers Builds no acepta tokens de cuenta) | Account Settings, Workers Scripts, Workers Builds Configuration (*Workers CI*) y Cloudflare Pages en *Read* (*Edit* para re-lanzar, cancelar o reintentar), sobre *All accounts* o las que quieras |
| Bitbucket | Email de Atlassian + API token **con scopes** (o access token de workspace/repo, sin email) | `read:user`, `read:workspace`, `read:repository`, `read:pipeline`, `read:pullrequest` (+`write:pipeline` para re-ejecutar/detener y `write:pullrequest` para aprobar/comentar/mergear), todos `:bitbucket` |

Al conectar la cuenta se abre el selector de organizaciones/workspaces que ve el token. Por cada
una se siguen los **30 repos más activos de los últimos 45 días** (ajustable), más los que se
fijen a mano. Se puede filtrar con globs: `contable-*, !*-legacy`.

## Cómo sincroniza (y por qué no quema el rate limit)

Bitbucket da ~1.000 requests/hora por usuario, así que no se consulta cada repo a ciegas:

1. Cada 60 s se pide **una** lista de repos por org/workspace, ordenada por actividad (con ETag
   en GitHub: los 304 no cuentan contra el límite). Un repo con push nuevo se consulta al tiro.
2. Cada repo tiene su propio ritmo: **15 s** mientras tiene ejecuciones activas, **60 s** si tuvo
   algo en la última hora, **10 min** si no. Un pipeline en pausa hace meses no lo deja "caliente".
3. Los entornos se refrescan cuando termina una ejecución del repo, o cada 30 min.
4. Si el proveedor responde 429, la cuenta queda en pausa hasta que se cumpla el `Retry-After`.

El botón **Sincronizar** fuerza todo en el próximo ciclo. Las cadencias se ajustan con variables
`HUB_*` (ver `.env.example`).

## Kubernetes (solo lectura)

Usa tu kubeconfig local (`~/.kube` montado en el contenedor, solo lectura). Para EKS genera el
token con botocore igual que `aws eks get-token`, con las credenciales de `~/.aws` montadas: no
hace falta la CLI de AWS en la imagen.

- **Resumen**: nodos listos, uso de CPU/memoria del cluster (metrics-server), lo que requiere
  atención (pods en CrashLoop/ImagePull/Pending, deployments incompletos, cronjobs cuyo último
  job falló, nodos con presión), pods con más reinicios, namespaces y eventos Warning.
- **Pods, Deployments, CronJobs, Jobs, StatefulSets/DaemonSets, Red (Ingress/Services), Config
  (ConfigMaps/Secrets), Nodos y Eventos**, con namespace, búsqueda y "solo con problemas".
- Panel de detalle: resumen, pods relacionados, ejecuciones de un cronjob, eventos, YAML y **logs**
  del pod (por contenedor, en vivo o del contenedor anterior tras un reinicio).
- El código solo hace GET: aunque tu usuario sea admin del cluster, el panel no puede cambiar
  nada. Los **Secrets se muestran sin valores** (solo nombres de claves) y no pasan por la caché.

## Servidores (por SSH, sin agente)

- Se agregan importando un host de `~/.ssh/config` o a mano, con una llave de `~/.ssh` (montado
  solo lectura) o pegada (se guarda cifrada). La huella del servidor se acepta la primera vez y
  la conexión se rechaza si cambia.
- Cada minuto: CPU, carga, memoria, swap y discos, con gráficos de 6 h a 7 días.
- Foto del sistema: SO y kernel, reinicio pendiente, actualizaciones (y de seguridad), **puertos
  abiertos** con su proceso y si quedan expuestos a internet (cruzado con ufw), procesos, discos,
  contenedores, unidades fallidas e intentos de SSH fallidos en 24 h.
- **Servicios** agrupados por plataforma (Edutecnia, quizkid…): systemd, Docker, Redis
  (memoria, clientes, keyspace), PostgreSQL (conexiones y tamaño de bases), Sidekiq (colas,
  ocupados, reintentos, muertos), RabbitMQ (colas sin consumidor), HTTP (código, latencia,
  vencimiento del certificado), puerto TCP y proceso. **Detectar servicios** propone los que
  corren en el servidor.
- **Logs** de cada servicio desde journal, un archivo o `docker logs`: últimas N líneas, filtro
  hecho en el servidor y seguimiento en vivo.
- Solo corren comandos de lectura fijos; lo que viene del formulario (unidad, ruta, contenedor,
  host) se valida y se cita con `shlex`. Las claves de Redis/Postgres van por variable de entorno
  dentro del script (por stdin), nunca como argumento visible en `ps`.

## Cloudflare

Cada cuenta de Cloudflare (las "organizaciones" del dashboard) se agrega como un workspace y
sus Workers y proyectos de Pages aparecen como repos:

- **Workers con Workers Builds** (conectados a GitHub/GitLab): cada build es una ejecución, con
  rama, commit, autor, origen (push/PR/manual) y log en vivo. Se puede re-lanzar el mismo commit
  o cancelar.
- **Pages**: cada deployment, con sus etapas (clone, build, deploy) y log. Se puede reintentar.
- **Workers sin Builds** (deploy con wrangler desde otro CI): se muestran sus deployments (quién
  y cuándo), sin log.
- Entornos: *production* del Worker (con el commit del build que lo generó) y production/preview
  de Pages.
- Como cada build trae el repo de origen, el CI de un **PR de GitHub** incluye los builds de
  Cloudflare del mismo commit, aunque el repo no tenga Actions.

## Vistas y filtros (Ejecuciones, Pull requests y Entornos)

- **+ Filtro** agrega condiciones. Ejecuciones: organización, repositorio, rama, workflow,
  estado, autor, evento, proveedor, cuenta. Pull requests: organización, repositorio, autor, rama
  destino u origen, estado (incluye *Borrador*). Entornos: organización, repositorio, entorno,
  estado, quién desplegó. Cada una puede
  ser **es** o **no es**, con varios valores y patrones con `*` (`deploy*`, `*-legacy`). Las
  opciones salen de los datos reales de los últimos 30 días, con su cantidad.
- Período: todo, 24 h, 7 o 30 días. Las tarjetas de resumen cuentan solo lo que calza.
- **Guardar como vista** deja el filtro como pestaña de esa pantalla (en PR guarda también la
  bandeja: por revisar, míos, abiertos o cerrados). Se guardan en la base del servicio, así que el
  MCP las ve: `list_views(scope)`, `list_runs(view=…)`, `list_prs(saved_view=…)`,
  `list_deployments(view=…)`.
- El filtro vive en la URL (`?f=` / `?view=`), así que un link reproduce lo mismo.
- API: `GET /api/runs?filter={"include":{…},"exclude":{…},"since_hours":168}` (igual en
  `/api/prs` y `/api/deployments`), `/api/{runs,prs,deployments}/facets`, `/api/runs/stats`,
  `GET|POST|PUT|DELETE /api/views` (con `scope`).

## Pull requests

- **Por revisar**: PR abiertos donde eres revisor y todavía no respondes (en GitHub, también si
  te volvieron a pedir revisión). **Míos**: tus PR abiertos. **Cerrados**: últimos 7 días.
- Cada PR muestra revisores con su estado, el CI del último commit (cruzado con las ejecuciones
  del panel, sin requests extra), comentarios y si está **lista para mergear** (aprobada, sin
  cambios pedidos y CI verde).
- Detalle: descripción y comentarios en Markdown, diff por archivo con comentarios en línea,
  commits, checks (en GitHub incluye check-runs y statuses de otras herramientas), conflictos.
- Acciones: aprobar (y quitar aprobación en Bitbucket), pedir cambios, comentar, mergear
  (merge / squash / rebase o fast-forward, opcionalmente borrando la rama) y cerrar/declinar.
- Se refrescan cada 2 min en GitHub (con ETag) y cada 5 min en Bitbucket, y al tiro cuando el
  repo muestra actividad nueva o haces una acción desde el panel.
- "Yo" se resuelve con la cuenta: login en GitHub, `account_id` en Bitbucket. En GitHub no se
  cuentan las revisiones pedidas a un *team*.

## Logs

- **Bitbucket**: se leen por rango de bytes mientras el step corre (seguimiento en vivo cada 3 s).
- **GitHub**: la API solo entrega el log de un job cuando termina; mientras tanto el panel muestra
  los pasos del job y un link a la vista en vivo de GitHub.
- Colores ANSI, grupos `##[group]` plegables, errores resaltados (al abrir un job fallido salta al
  primer error), búsqueda con Enter/Shift+Enter, horas por línea y descarga.

## MCP

```bash
claude mcp add --transport http pipelines-hub https://pipelines.orb.local/mcp/
```

Herramientas de infraestructura: `k8s_overview`, `k8s_pods`, `k8s_workloads`, `k8s_describe`,
`k8s_pod_logs`, `k8s_events`, `server_status`, `service_logs`.

Herramientas de CI/CD: `list_runs` (acepta `view`), `list_views`, `get_run`, `get_step_log` (con `tail_lines` y `grep`),
`list_deployments`, `rerun`, `cancel`, `list_prs`, `get_pr`, `pr_diff`, `comment_pr`,
`approve_pr`, `merge_pr`.

## Desarrollo

```bash
# backend (puerto 8799)
cd backend && uv sync && HUB_DATA_DIR=./data uv run uvicorn app.main:app --reload --port 8799
uv run pytest && uv run ruff check app tests

# front (puerto 5188, proxy de /api al backend)
cd frontend && npm install && npm run dev
```

| Ruta | Qué hay |
|------|---------|
| `backend/app/providers/` | `github.py` y `bitbucket.py` con la misma interfaz (`Provider` en `__init__.py`) y tipos normalizados en `base.py` |
| `backend/app/sync.py` | poller y reglas de qué repos se siguen |
| `backend/app/service.py` | operaciones que comparten la API REST y el MCP |
| `backend/app/api.py` · `mcp_server.py` | REST para el front · herramientas MCP |
| `frontend/src/views/` | Ejecuciones, detalle con logs, Pull requests, detalle de PR, Entornos, Cuentas |

Sin autenticación propia: el puerto se publica solo en `127.0.0.1` y el dominio `.orb.local` solo
existe en esta máquina. No exponerlo a una red: además de los tokens de CI, el contenedor ve tu
kubeconfig, tus credenciales de AWS y tus llaves SSH (montadas solo lectura).
