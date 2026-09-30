# PROFILE-BETA-1 — inventario READ y frontera de promoción

Autoridad: plan canónico §7:710, 715, 721, 731 y §12/§14; contrato B9D. El plan exige una lista aprobada explícita pero no nombra cada READ del primer candidato. La selección siguiente es el **alcance acotado de este candidato de prueba**, no una afirmación de aprobación operacional ni un cambio del gate runtime. Fuente del inventario: `apps.agent.capabilities.EFFECTS` en el baseline B9D.

| Capability | Efecto | Candidato | Gate runtime existente | Identidad/consentimiento | B0 cerrado | Frontera tenant y riesgo |
| --- | --- | --- | --- | --- | --- | --- |
| `get_clinic_info` | READ_PUBLIC | Sí | AgentSettings, policy, catálogo/ToolExecutor, API | Sin identidad personal ni B7B | Puede funcionar | Organización del canal y datos de clínica del mismo tenant |
| `get_service_catalog` | READ_PUBLIC | Sí | Igual; API de servicios con RBAC AGENT | Sin identidad personal ni B7B | Puede funcionar | Organización del canal; respuesta validada antes de grounded reply |
| `get_offered_specialties` | READ_PUBLIC | No | Igual | Sin identidad personal ni B7B | Puede funcionar | Fuera de los guiones E2E seleccionados, no aprobado por este candidato |
| `check_product_availability` | READ_PUBLIC | No | Igual | Sin identidad personal ni B7B | Puede funcionar | Fuera del corpus acotado; no confundir disponibilidad con promesa de stock |
| `find_available_slots` | READ_PUBLIC | No | Igual | Sin identidad personal ni B7B | Puede funcionar | Fuera del corpus acotado; disponibilidad no reserva cita |
| `check_appointment_slot` | READ_PUBLIC | Sí | Igual | Sin identidad personal ni B7B | Puede funcionar | Slot por clínica/vet; no ejecuta WRITE ni concede reserva |
| `list_my_pets` | READ_PERSONAL | Sí | Verificación `confirmed_in_chat` vigente + owner; API/RBAC y contrato | No B7B; identidad actual obligatoria | Puede funcionar si pasa identidad | Owner/org y proyección de handles de la conversación; teléfono compartido sigue riesgo residual |
| `get_vaccine_status` | READ_PERSONAL | Sí | Handle de mascota de la conversación + `_personal_pet_reference` + API/RBAC | No B7B; hereda identidad/owner del handle | Puede funcionar si pasa identidad | Pet/org/owner acotados; no acepta ID arbitrario del modelo como autoridad |
| `get_appointments` | READ_PERSONAL | Sí | `confirmed_in_chat` vigente; owner/mascota y API/RBAC | No B7B; identidad actual obligatoria | Puede funcionar si pasa identidad | Org/owner/pet acotados; el resultado no autoriza mutación |
| `get_recent_product_queries` | READ_PERSONAL | No | `available_tools` y `run_tool` exigen `confirmed_in_chat`; proyección local de `ToolExecution` | No B7B; identidad vigente obligatoria | Puede funcionar si pasa identidad | Historial local scoped a conversación; fuera del corpus E2E seleccionado, y persiste el riesgo general de teléfono compartido/reciclado |

Para todas las filas, el manifiesto B9D describe lo que un release **podría aprobar**; no intercepta cada READ. Su gate obligatorio de ejecución se aplica a las cinco WRITE. `AgentSettings.enabled=True` y el policy engine mantienen la disponibilidad heredada de READ/CONTROL bajo B0; no convierten una READ en aprobación beta. La identidad `ContactIdentity` y su revisión, el binding B6, el contacto de la conversación, la procedencia de handles y RBAC del agente deben permanecer vigentes en READ_PERSONAL. Un resultado de test con identidad sembrada no resuelve el riesgo real de número compartido o reciclado; el plan exige aceptación humana expresa de ese riesgo antes de activación.

La política de READ no exige confirmación causal B7B de una operación WRITE ni el grant B9D para atender una consulta bajo la disponibilidad previa. La aprobación operacional del candidato sigue pendiente por clínica, capability y tasa; ningún READ del inventario se promovió en producción mediante B9E. Las READ no seleccionadas no se retiran del código y no se cuentan como cobertura E2E de este perfil.
