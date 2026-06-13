# Required context

NO cargar @docs/modules/ completo. Cargar solo el archivo del dominio afectado.

Módulos disponibles:

- Billing:
  @docs/modules/billing.md

- Historial clínico:
  @docs/modules/medical_records.md

- Inventario:
  @docs/modules/inventory.md

- Citas:
  @docs/modules/appointments.md

- Analytics:
  @docs/modules/analytics.md

- Usuarios/organizaciones:
  @docs/modules/organizations.md

No implementar reglas de negocio basándose solo en código.
Los documentos anteriores son contratos del dominio.

# Backend Rules

Contexto:
Django + DRF SaaS multi-tenant.

---

# Organización

Apps son dominios independientes.

Respetar ownership.

No importar lógica entre dominios sin revisar arquitectura.

---

# Services

Toda operación con:

- cambio de estado
- pagos
- inventario
- historial clínico
- analytics

debe pasar por services.

Views deben ser delgadas.

---

# Transactions

Usar transaction.atomic cuando:

- afecta dinero
- afecta stock
- crea varias entidades relacionadas

---

# Concurrencia

Para datos críticos:

usar select_for_update.

Nunca hacer:

obj.value += x
obj.save()

en campos contables concurrentes.

Usar operaciones atómicas.

---

# Serializers

Serializers validan entrada.

No poner reglas complejas de negocio ahí.

---

# API

Mantener formato estándar de errores:

{
  code,
  message/errors
}

---

# Seguridad

Validar siempre:

- organización
- permisos
- ownership

Nunca confiar en frontend.

---

# Estados

No modificar estados directamente.

Ejemplo prohibido:

invoice.status = "paid"

Usar servicios autorizados.

---

# Soft rules

Antes de crear un modelo nuevo:

preguntar:
¿es realmente un concepto nuevo del dominio?