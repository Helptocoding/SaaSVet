# Procedimiento aprobado — solicitudes de acceso/demo

**Ámbito:** solo datos del formulario público Formspree y sus copias/reenvíos relacionados. No aplica a cuentas activas de clínicas, expedientes, WhatsApp, metadata, backups operativos de otros tratamientos ni preferencia/retención GA4.

## Regla aprobada y fecha de referencia

Para una solicitud sin relación activa, seleccionar para eliminación cuando hayan transcurrido **180 días naturales o más** desde el último contacto efectivo sobre esa misma solicitud. El responsable aprobó esta regla en esta conversación. La fecha del envío inicia el cómputo si no hubo contacto efectivo posterior. El vencimiento es inclusivo: día 179 no; día 180 sí. Guardar fechas como calendario (`YYYY-MM-DD`) con evidencia de origen y zona horaria si la fuente es timestamp; el operador normaliza una sola fecha y no inventa fechas.

**Contacto efectivo:** interacción humana entrante o saliente sustantiva referida a la solicitud —p. ej., respuesta del prospecto o respuesta atendida sobre su acceso/demo— registrada con fecha, canal y referencia mínima. Mensajes automáticos, confirmaciones, recordatorios, campañas o newsletters no son contacto efectivo y nunca reinician el cómputo. No conservar contenido completo como prueba si basta fecha/canal/identificador interno.

**Relación activa:** excepción de revisión, no etiqueta por haber enviado el formulario o recibir un automático. Debe tener evidencia de inicio, propósito vigente, responsable y fecha de revisión/cierre. Al finalizarla, separar registros necesarios para el servicio/obligaciones justificadas del conjunto de prospecto. Los campos de la solicitud vuelven a regla de prospectos; no se les asigna retención indefinida por asociación con cliente.

**Revocación/solicitud de derechos:** bloquear nuevos usos de seguimiento y escalar al responsable para determinar alcance, excepciones legales y ejecución en sistemas/copies. No usar el trámite como excusa para ampliar retención ni borrar automáticamente otros registros con otra finalidad. Registrar solo decisión, fecha y resultado sin PII adicional en este repositorio.

## Ciclo manual que ejecutará el usuario

1. En una revisión periódica fijada por el responsable, obtener una lista de solicitudes desde Formspree y comparar con el buzón de recepción. Las exportaciones incluyen datos personales: guardarlas en carpeta privada controlada, cifrada y temporal; no incorporarlas a Git, este expediente, tickets abiertos ni chat.
2. Asignar referencia de solicitud (ID del proveedor o clave interna mínima, no correo/nombre) y registrar fecha de envío. Revisar correos/reenvíos para localizar solo contactos efectivos. Mantener por contacto fecha/canal/referencia, no el cuerpo.
3. Marcar cada registro como `ELEGIBLE`, `NO_ELEGIBLE` (fecha dentro de 180 días), `RELACION_ACTIVA_REVISAR`, `FECHA_DESCONOCIDA_REVISAR` o `DERECHOS/REVOCACION_REVISAR`. Fechas dudosas y duplicados no se completan por aproximación.
4. Antes de borrar, confirmar que no hay relación activa documentada ni obligación distinta que exija conservar un subconjunto. Separar lo que sí se conserva, limitarlo al propósito independiente y quitarlo del dossier de prospecto.
5. Para elegibles, localizar y eliminar manualmente en Formspree; buzón original; enviados/reenvíos; papelera; hojas de cálculo, descargas, adjuntos y exportaciones; integraciones conectadas que el titular confirme; y duplicados de equipo. Revisar también copias del buzón o cliente de correo bajo control del usuario.
6. Consultar el dashboard y documentación/soporte del proveedor para su retención de logs, respaldos y ciclos de expiración. Una eliminación de dashboard no demuestra borrado físico de copias de proveedor. Registrar lo que el proveedor confirme, fecha/versiones, alcance y excepciones; no prometer borrado físico no acreditado.
7. Hacer control posterior por referencia y estado; si algo falla, detener el cierre, registrar sistema/acción pendiente y escalar al titular. La evidencia mínima es conteo por sistema, resultado, fecha y operador; nunca valores de formulario.
8. Eliminar exportaciones temporales de trabajo y vaciar papeleras/reciclajes que estén bajo control del responsable. No modificar cuentas del proveedor a nombre del usuario ni ejecutar borrados durante esta entrega.

## Dataset sintético probado

| Referencia ficticia | Fecha base / situación | Resultado esperado |
|---|---|---|
| `SYN-179` | envío día 0; reloj día 179 | Aún no elegible. |
| `SYN-180` | envío día 0; reloj día 180 | Elegible si no existe excepción. |
| `SYN-181` | envío día 0; reloj día 181 | Elegible si no existe excepción. |
| `SYN-AUTO` | envío día 0; campaña/automático día 179 | La fecha base sigue día 0; elegible en día 180. |
| `SYN-EFECTIVO` | envío día 0; contacto humano efectivo día 90 | Referencia pasa al día 90; elegible en día 270, no en día 269. |
| `SYN-ACTIVA` | relación activa con prueba y revisión pendiente | No borrar automáticamente; revisión de propósito/fin. Al cerrar, reevaluar original del prospecto. |
| `SYN-SIN-FECHA` | envío/contacto sin fecha acreditable | Revisión manual; no usar fecha actual ni fecha de despliegue como sustituto. |
| `SYN-REVOCADA` | revocación ficticia | Bloquear seguimiento y resolver eliminación/excepción según alcance; evidencia manual. |

Verificación ejecutada con `datetime.date`/`timedelta` en Python; assertions para días 179/180/181, contacto efectivo posterior, automático, relación activa, fecha desconocida y revocación. **Fixture de regla solamente**; no es una base de prospectos, automatización, CRM ni evidencia de eliminaciones reales.

## Evidencia mínima que quedará con el usuario

- Referencia no identificadora, rango/fecha de corte, conteo revisado/elegible/eliminado/con excepción.
- Sistemas revisados: Formspree, buzón, enviados, papelera, reenvíos, exportaciones, archivos de trabajo e integraciones confirmadas.
- Registro de contacto efectivo y prueba de cierre de relación cuando corresponda.
- Fecha/operador/resultado por sistema, ticket de excepción y respuesta del proveedor respecto a copias/backups si la obtiene.
- Ningún valor de PII, exportación, ID de cuenta, contrato privado o credencial en Git/chat.
