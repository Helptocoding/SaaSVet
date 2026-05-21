# Día 6 — Endurecimiento de IDs (pk vs public_id)

Plan arquitectónico para apagar `ALLOW_LEGACY_ID_LOOKUP` sin romper la app, cerrar P0 #18 + P1 #38-40, y eliminar IDOR/enumeration latente en superficies con PK entero.

## Documentos

| # | Archivo | Rol | Lectura obligatoria |
|---|---|---|---|
| 0 | **[PLAN-DIA-6.md](PLAN-DIA-6.md)** | **Plan final consolidado — fuente de verdad** | ✅ Todos |
| 1 | [01-draft-backend-architect.md](01-draft-backend-architect.md) | Draft inicial — ownership, boundaries, lookup strategy | Backend devs |
| 2 | [02-security-annex.md](02-security-annex.md) | Anexo seguridad — IDOR, enumeration, tenant leaks, RBAC | Backend + security review |
| 3 | [03-db-annex.md](03-db-annex.md) | Anexo persistencia — índices, migraciones, UUID version | DB + migración |
| 4 | [04-code-quality-annex.md](04-code-quality-annex.md) | Anexo anti-deuda — helper creep, dual-lookup, naming drift | Code review |
| 5 | [05-qa-annex.md](05-qa-annex.md) | Anexo QA — tests, regression, edge cases, rollback | QA + cutover |

## Pipeline de auditoría aplicado

Los 5 anexos se produjeron secuencialmente, cada uno revisando el anterior:

```
backend-architect (draft) → security-auditor → database-architect → code-reviewer → senior-qa
```

El plan final (`PLAN-DIA-6.md`) absorbe los hallazgos de los 5.

## Inicio

Leer `PLAN-DIA-6.md` antes de tocar código. Los anexos son traza de razonamiento — útiles si alguna decisión genera dudas.

## Out of scope

Ver `PLAN-DIA-6.md` §18.
