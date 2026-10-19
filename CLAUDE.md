# CLAUDE.md — Boot-Tracker

**Boot-Tracker** es un CRM para Coding Bootcamps ESPOL. Gestiona el ciclo completo:
captación de leads → seguimiento comercial → conversión a bootcamper → pagos → analíticas.

- **Cliente:** PhD. Carmen Vaca (cvaca@espol.edu.ec)
- **Entrega parcial:** 15 jun 2026 — flujo end-to-end (login → leads → interacciones)
- **Entrega final:** 17 ago 2026 — producción + docs + handoff
- **Issues y sprints:** `gh issue list` o GitHub → Milestones

---

## Estado del código

| Área | Estado |
|---|---|
| Backend Django | ✅ Auth, Leads, Payments, Conversions, Notifications. Analytics: stub vacío. |
| Frontend React | ❌ Solo placeholder `<h1>`. Dependencias instaladas, cero pantallas. |
| Mobile Expo | ⚠️ Auth screens implementadas (login, forgot-password). App screens pendientes. |
| DevOps | ⚠️ CI verde. Deploy a producción pendiente. |

---

## Equipo

| Persona | GitHub | Área |
|---|---|---|
| Juan Munizaga | `Jmuniz27` | Orquestación, DevOps, revisiones de backend y mobile |
| JL Chong | `Jlchong3` | Backend — nuevos endpoints |
| Zahid Díaz | `LockHurb` | Integraciones — Google Calendar, Analytics |
| Gabriela Jiménez | `gabsjimz` | Frontend — UI/UX lead, vistas principales |
| Annabella Sánchez | `manzannita` | Frontend — formularios, pagos, admin |
| Isabella Martín | `isabellaim` | Mobile Expo — todas las screens |

**PRs:** CI verde + 1 aprobación. Backend/mobile → Juan revisa. Frontend → Gabriela ↔ Annabella se revisan mutuamente.

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Django 5.1 + DRF + djangorestframework-simplejwt |
| Base de datos | PostgreSQL 16 (Docker) |
| Cola / cache | Redis 7 + Celery (email, OCR) |
| Frontend | React 18 + Vite + Tailwind — shadcn/ui, Zustand, React Hook Form, Zod pendientes de instalar |
| Estado | Zustand (no Redux) — pendiente instalar |
| Fetching | TanStack Query v5 (no useEffect para datos remotos) |
| Formularios | React Hook Form + Zod — pendientes de instalar |
| Mobile | Expo SDK 54 + Expo Router (file-based en `app/`) |
| Auth mobile | expo-secure-store (nunca AsyncStorage para JWT) |
| Storage | MinIO local → S3 prod |
| Emails | SMTP (Gmail) via Celery |
| Docs API | drf-spectacular → `/api/schema/swagger-ui/` |

---

## Comandos esenciales

```bash
# Entorno local completo
docker-compose up

# Migraciones
docker-compose exec backend python manage.py migrate

# Tests backend (con cobertura)
docker-compose exec backend pytest --cov=apps --cov-report=term-missing

# Tests de un módulo
docker-compose exec backend pytest apps/leads/tests/ -v

# Lint backend
docker-compose exec backend ruff check . && ruff format --check .

# Frontend dev
cd frontend && npm run dev

# Mobile
cd mobile && npx expo start
```

### Después de un `git pull` (obligatorio)

Las imágenes y volúmenes de Docker no se actualizan solos cuando un PR agrega
dependencias. Si sólo haces `docker-compose up`, arrancás con dependencias viejas:

```bash
# 1. Backend y celery son DOS imágenes distintas del mismo Dockerfile.
#    Reconstruir sólo backend deja celery caído.
docker-compose build backend celery

# 2. El compose monta `- /app/node_modules` como volumen anónimo, que tapa el
#    node_modules del host. Un `npm install` local NO llega al contenedor, y el
#    volumen se reutiliza aunque reconstruyas la imagen: hay que renovarlo.
docker-compose up -d --build --renew-anon-volumes frontend

# 3. Migraciones
docker-compose exec backend python manage.py migrate

# 4. Datos de prueba (usuarios, leads, programas, pagos)
docker-compose exec backend python manage.py seed_dev
```

**Cómo se ven los síntomas si te lo saltás:**

| Síntoma | Causa |
|---|---|
| `celery exited (1)` con `ModuleNotFoundError` | falta `docker-compose build celery` |
| Vite: `Failed to resolve import "<paquete>"` | falta `--renew-anon-volumes` en frontend |
| `relation ... does not exist` | falta `migrate` |

El de celery es el más peligroso: **no produce ningún error visible en la
interfaz**, pero sin celery no se envían emails ni corre el OCR de comprobantes.

### Profiling opcional

El panel de django-silk está apagado por defecto; se levanta con
`SILK_ENABLED=True docker-compose up backend` y queda en `/silk/`
(exige sesión de staff).

---

## Estructura

```
boot-tracker/
├── backend/
│   ├── config/          ← settings base/dev/prod
│   └── apps/
│       ├── authentication/
│       ├── leads/
│       ├── payments/
│       ├── programs/
│       ├── notifications/
│       └── analytics/   ← stub vacío, pendiente
├── frontend/
│   └── src/
│       ├── api/         ← (objetivo) clientes por módulo (auth.api.ts, leads.api.ts…)
│       ├── components/  ← (objetivo) wrappers shadcn/ui + propios
│       ├── pages/       ← (objetivo)
│       ├── hooks/       ← (objetivo)
│       └── store/       ← (objetivo) Zustand stores
└── mobile/
    └── app/
        ├── (auth)/      ← login.tsx, forgot-password.tsx ✅
        └── (app)/       ← screens principales pendientes
```

---

## Convenciones

### Git
- **Antes de crear cualquier rama de feature:** hacer `git checkout staging && git pull origin staging` para partir del HEAD actualizado. Los PRs de trabajo apuntan a `staging`; `main` sólo recibe releases desde `staging` (ver CONTRIBUTING.md).
- Rama: `feat/<numero-issue>-descripcion` (ej. `feat/9-lead-dashboard`)
- Commit: `feat(leads): add self-assignment endpoint` — sin mencionar herramientas de IA. IMPORTANTE, no incluir "Co-Authored-By".
- PR: título + número de issue + cómo probar

### Django / Python
- Linter: **ruff** — no usar flake8 ni black por separado
- Lógica de negocio en `services.py` — nunca en views ni serializers
- Tests: pytest + factory_boy
- Logging: `logger = logging.getLogger(__name__)` — nunca `print()`

### React
- Fetching: `useQuery` / `useMutation` de TanStack Query
- Estado global: Zustand — instalar con `npm install zustand` antes de usar
- Formularios: React Hook Form + Zod — instalar con `npm install react-hook-form zod` antes de usar
- Componentes shadcn/ui: instalar con `npx shadcn@latest init` antes de usar — no modificar el original, crear wrappers en `components/`
- Archivos: PascalCase para componentes, `use-nombre.ts` para hooks, `nombre.service.ts` para servicios

### Mobile
- Navegación: Expo Router (file-based)
- JWT: expo-secure-store — nunca AsyncStorage
- Notificaciones: Expo Notifications

### Internacionalización (i18n) — OBLIGATORIO en web y mobile
La app es **bilingüe español/inglés** (default: **español**; toggle manual, elección persistida). **Todo texto visible al usuario DEBE pasar por `t('clave')`** y tener entrada en **es.json y en.json**. Nada de strings hardcodeados en la UI.

- **Web:** `i18next` + `react-i18next`. Locales en `frontend/src/i18n/locales/{es,en}.json`; init en `frontend/src/i18n/index.js`; `useTranslation()` en componentes; `<LanguageSwitcher />` para cambiar idioma.
- **Mobile:** `i18next` + `react-i18next`, persistido en `expo-secure-store`. Locales en `mobile/src/i18n/locales/{es,en}.json`; init en `mobile/src/i18n/index.ts`; `<LanguageSwitcher />` en `mobile/src/components/`.
- **Claves** por dominio (`common`, `auth`/`login`/`forgot`, `nav`, `leads`, `payments`, `agenda`, `analytics`, `users`…). El **español debe ser idéntico al texto original** para no cambiar la UI ni romper tests.
- **Regla para cualquier feature/fix/cambio nuevo:** si agrega o toca texto visible, ese texto va por `t()` con su versión **española E inglesa** en ambos locales. Un PR con strings hardcodeados nuevos no cumple la convención.

### Linear auto-sync (`/linear-sync`)
- **Uso:** después de mergear un PR a `main`, corre `/linear-sync CB-<N>`
  (ej. `/linear-sync CB-40`). Verifica el issue antes de cerrarlo.
- **Cómo funciona:** lanza el agente `linear-sync` (modelo `claude-opus-4-8`,
  tarea de criterio). Lee el issue en Linear (criterios, sub-tareas, labels),
  resuelve el PR y el estado de CI con `python .claude/scripts/pr_context.py CB-<N>`,
  inspecciona el código y los tests del diff, y decide.
- **Matching:** el id sale del nombre de rama `<user>/cb-<N>-<slug>` → `CB-<N>`.
  Si el argumento no es `CB-<N>`, no toca Linear. **Sólo modifica ese issue.**
- **La barra:** Done = todos los criterios de aceptación implementados + tests
  presentes y **no-skippeados** + **build verde**. Si falta algo → **In Review**
  con la lista de faltantes (por requisito). **Build rojo → no se toca el estado**
  ("Build is failing — fix CI before this can be closed").
- **Trigger:** sólo por slash command (no hay hook automático — política de costo).
- **Credenciales:** la sync usa el **Linear MCP** ya autenticado; no se necesita
  token. Opcional `LINEAR_API_TOKEN` para el fallback REST del script
  (`.env.example`). Nunca hardcodear tokens.

---

## Convención de PRs (1 issue = 1 PR)

Cada issue de GitHub debe tener exactamente un PR asociado.

### Reglas
- El body del PR DEBE incluir `Closes #N` (N = número de issue en GitHub)
- **Excepción — PRs sin issue (tooling/chore):** incluir `No-Issue: <razón>` en el body en lugar de `Closes #N`. El gate lo reconoce y no bloquea.
- Nombre de rama: `<type>/<CB-XX>-short-description` (ej. `feat/CB-44-leads-dashboard`)
- El título del PR debe referenciar el título del issue

### Asignación de revisores
| Escenario | PR Author | Reviewer | Quién mergea |
|---|---|---|---|
| Codeas tu propio issue | Assignee del issue | Cualquier compañero (preferir experto del dominio) | Reviewer tras aprobar |
| Codeas el issue de otro | Quien codea | Assignee del issue (revisa su propia spec) | Assignee tras aprobar |

### Ejemplo real: CB-56 (S4-3 Monitoreo pagos)
Issue asignado a: JL Chong — Codeado por: Juan Munizaga
→ Juan abre PR con `Closes #21` → Asigna a Zahid como reviewer → Zahid revisa y mergea

### Labels en PRs
- `feature` — nueva funcionalidad
- `fix` — bug fix
- `devops` — infra/CI
- `docs` — solo documentación
- `test` — solo tests

### Gate automatico pre-PR

Al correr `gh pr create`, Claude ejecuta un gate de dos capas antes de crear el PR:

1. **Capa inteligente (hook prompt):** trae el issue de GitHub (`Closes #N`) y la tarjeta de Linear (CB-key), compara el diff contra los criterios de aceptacion y el checklist. Si algún criterio verificable no se cumple, lista los huecos y pregunta "seguro que queres crear el PR igual?" antes de proceder.
2. **Piso determinista (`pre-pr.sh`):** bloquea con confirmacion si falta el minimo estructural: no estar en `main`, body con referencia al issue (o `No-Issue:`), body con instrucciones de prueba. Si no pasa, indica qué corregir en el body.

**Ciclo de vida completo de un PR:**
```
gh pr create  →  gate pre-PR  →  PR creado  →  recordatorio pr-reviewer  →  Claude aprueba  →  merge  →  /linear-sync CB-N
```

---

## Lo que NO hacer

- `print()` → usar `logging.getLogger(__name__)`
- Lógica en views/serializers → va en `services.py`
- `useEffect` para fetching → TanStack Query
- `AsyncStorage` para tokens → expo-secure-store
- Modificar archivos shadcn/ui directamente → crear wrappers
- Hardcodear credenciales → siempre `.env`
- Mencionar herramientas de IA en commits

---

## Reglas de Negocio Críticas

Estas reglas no se pueden romper. Si una PR las viola, Claude la rechaza automáticamente.

| Regla | Dónde vive | Consecuencia de violarla |
|---|---|---|
| Validación de cédula ecuatoriana | `backend/apps/authentication/validators.py` → `validate_cedula()` | Datos inválidos en DB, problema legal |
| Umbral 10% déficit en pagos | `backend/apps/payments/services.py` | No se dispara la alerta al coordinador |
| RBAC obligatorio en cada endpoint | Todo `APIView`/`ViewSet` debe declarar `permission_classes` | Cualquier usuario accede a datos ajenos |
| OCR de comprobantes es async | `backend/apps/payments/tasks.py` via Celery — nunca inline en views | Timeout en requests, mala UX |
| No push directo a `main` ni a `staging` | Todas las modificaciones van por PR | Se saltea CI + revisión de Claude |

### Flujo Git obligatorio

```
feature branch → PR targeting staging → CI verde + review → merge → deploy a staging
staging → PR targeting main → CI verde + review → merge → deploy a producción
```

- Claude puede **rechazar** un PR y debe comentar razones específicas con `file:line`
- Claude aprueba con `gh pr review --approve` solo si CI pasa y no hay BLOCK issues
- No se requiere aprobación humana si Claude aprueba y CI es verde

### Secrets y configuración

Nunca hardcodear. Siempre usar variables de entorno del `.env` (local) o los secrets de GitHub Actions (CI/prod).
Variables requeridas: ver `.env.example` en la raíz del repo.
