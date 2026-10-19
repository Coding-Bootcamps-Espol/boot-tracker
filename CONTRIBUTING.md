# Contribución — Boot-Tracker

## Branches
- `feat/<numero-issue>-descripcion` — feature nueva (ej. `feat/9-lead-dashboard`)
- `fix/<numero-issue>-descripcion` — bug fix (ej. `fix/12-token-expiry`)
- `chore/<descripcion>` — tareas técnicas sin issue
- Nunca pushear directo a `main` ni a `staging`

## Flujo: staging → main

```
feat/* ──PR──► staging ──(deploy automático)──► boottracker-staging.codingbootcampslatam.com
staging ──PR──► main   ──(deploy automático)──► boottracker.codingbootcampslatam.com
```

- **Toda rama de trabajo sale de `staging` y su PR apunta a `staging`**
  (`git checkout staging && git pull origin staging && git checkout -b feat/...`).
- Al mergear a `staging`, el CI publica las imágenes y despliega staging. Ahí se
  prueba con datos realistas: es un **espejo anonimizado** de producción, sin datos
  personales reales.
- Los releases a producción son un PR de `staging` a `main`.
- **Correo en staging:** nada sale a internet. Todo lo atrapa Mailpit y se ve en
  `https://boottracker-staging.codingbootcampslatam.com/mailpit/` (pedir la clave a
  Juan). Sirve para probar resets de contraseña y notificaciones.
- **Login en staging:** las cuentas del equipo conservan su correo; la contraseña es
  la de staging (pedirla a Juan). Los bootcampers son `bootcamper<n>@staging.test`.

## Commits
Formato: `tipo(módulo): descripción`
Ejemplos:
- `feat(leads): auto-asignación con locking`
- `fix(auth): refresh token expirado`

Tipos: feat, fix, chore, docs, refactor, test

## PRs
- Base del PR: `staging` (salvo los releases `staging → main`)
- Referenciar el issue: `Closes #número`
- El CI debe pasar (tests Django + build frontend)
- 1 review requerido antes de merge
- PRs pequeños, un issue por PR
