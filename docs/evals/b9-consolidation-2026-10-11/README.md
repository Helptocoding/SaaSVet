# B9: expediente consolidado y conservación

El [acta](ACTA.md) es el índice vigente de decisiones. La entrega documental está consolidada; la aceptación integral del candidato actual y la activación conservan sus pendientes. Esta carpeta no autoriza ejecuciones adicionales.

## Qué se conserva y cómo

Se conserva la totalidad del inventario local registrado durante la revisión del 11 de octubre. [Inventario de entrada](../inbox-whatsapp-closure-review-2026-10-11/git-inventory.json) y [disposición de cada archivo](versioning-disposition.json).

- Harness, tests, auditoría fuente, decisiones y documentos de cierre: archivos Git directos, sin cambiar sus bytes congelados.
- Recibos, índices y reportes de entrada: también legibles directamente en Git.
- Evidencia bruta de las carpetas históricas inventariadas: ZIP/deflate completos, fragmentados en partes de hasta 20 MiB bajo `evidence-packages/`. No necesitan LFS ni un servicio externo.
- Diagnóstico histórico `68a4a77`: 43 archivos recuperados como blobs exactos, con [procedencia individual](historical-provenance.json), sin incorporar runtime de otra rama.
- Copias locales originales: permanecen intactas. Las reglas exactas de `.gitignore` evitan volver a añadir esos brutos; no cubren nuevas carpetas de pruebas futuras. Los archivos de entrada legibles se añaden expresamente al índice y siguen bajo seguimiento normal.

El [manifiesto](preservation-manifest.json) enumera cada ruta original, tamaño y SHA-256, además de los hashes de cada parte y del ZIP concatenado. `.gitattributes` conserva los bytes de evidencia; una conversión de finales de línea invalidaría sus hashes. El [recibo de recuperación](preservation-verification.json) acredita restauración aislada de todos los miembros y comparación con los originales.

En un checkout nuevo, algunos enlaces de los reportes históricos apuntan a brutos que están dentro de los paquetes. Se recuperan con el modo de hidratación descrito abajo antes de seguir esos enlaces o usar los verificadores históricos. No se debe interpretar su ausencia previa a la restauración como pérdida de evidencia.

Los paquetes son evidencia histórica inmutable. Una corrección interpretativa se registra en un acta posterior; no se edita el paquete ni se reescribe un resultado anterior. No se borran originales por este encargo. Cualquier futura eliminación requiere comprobar de nuevo la recuperación desde un checkout independiente y resolver por separado su autorización y retención. El [análisis acotado de credenciales](privacy-scan.json) no sustituye las aprobaciones P-A/P-B, ni una política de categorías/plazos o una revisión de datos personales.

La decisión de conservación técnica es mantener el expediente completo y recuperable, sin purga automática. No se inventa un plazo legal de retención para datos personales: las categorías, responsables y plazos aplicables siguen sujetos al pendiente de privacidad ya registrado en el acta.

## Verificar y recuperar

Requiere Python 3.9 o posterior y su biblioteca estándar. La restauración no importa la aplicación, no conecta bases/proveedores y no ejecuta escenarios. Los ejemplos usan el wrapper obligatorio del repositorio; puede sustituirse la ruta al intérprete por la instalación disponible.

Desde la raíz de un checkout que contenga esta entrega:

```powershell
rtk proxy venv/Scripts/python.exe -B -X utf8 docs/evals/b9-consolidation-2026-10-11/conserve_evidence.py verify
```

`verify` necesita también las copias locales originales. Para recuperar en una carpeta nueva/vacía, sin ellas:

```powershell
rtk proxy venv/Scripts/python.exe -B -X utf8 docs/evals/b9-consolidation-2026-10-11/conserve_evidence.py restore --destination C:/evidence/b9-recovered
```

Para hidratar las rutas originales en un checkout independiente que ya contiene los reportes legibles, se puede usar `restore --destination <raíz-del-checkout> --allow-identical`. Ese modo permite archivos existentes únicamente si tamaño y hash coinciden. No sobreescribe discrepancias; se detiene conservándolas. El destino y las partes deben estar en una unidad con espacio suficiente para los archivos restaurados y, temporalmente, el mayor ZIP concatenado. La verificación aislada local sólo mantiene un grupo restaurado a la vez.

Toda parte se verifica antes de abrir el ZIP; se rechazan rutas que salgan del destino, miembros faltantes/duplicados y contenido cuyo hash difiera. Una restauración interrumpida puede dejar archivos parciales en el destino: no se considera PASS. Se conservan para diagnóstico o se usa otro destino vacío; no hay limpieza destructiva automática.

Los [controles de integridad](preservation-guards.json) incluyen alteración de partes, hashes erróneos, miembros ausentes/duplicados, escape de rutas y conservación de archivos locales distintos. Se reproducen con `check_preservation_guards.py`; usan unos bytes temporales para comprobar la herramienta, sin importar ni ejecutar el harness de la aplicación.

La primera comprobación de recuperación encontró el límite tradicional de longitud de rutas de Windows al añadir el directorio temporal a rutas históricas profundas. La herramienta utiliza ahora rutas extendidas de Windows después de validar el confinamiento del destino; incluye un control específico y se verifica de nuevo el expediente completo. No exige cambiar la configuración del host ni renombrar evidencia.

`pack` es una operación de conservación del inventario original, no una prueba del sistema. Reutiliza paquetes existentes sólo tras verificar todos sus miembros contra los originales y escribe un checkpoint por grupo. Un paquete incompleto o alterado detiene el proceso. El checkpoint es temporal y no pertenece a la entrega. El incidente de memoria del host interrumpió el empaquetado inicial; no alteró recibos ni ejecutó escenarios, y se retomó con bloques de 128 KiB.

## Versionado y límites de esta entrega

La selección explícita de archivos se prepara en `codex/e4-capacity-scheduling`. [Disposición Git](versioning-disposition.json). Se excluyen los cambios previos ajenos en `DEPLOY_VPS_PLAN.md`, `DEPLOY_VPS_STATUS.md` y `skills-lock.json`. Los tres commits antiguos de WA-02 ya tienen cambios equivalentes incorporados y no se duplican. La evidencia de `68a4a77` se conserva con su procedencia, sin merge ni cambio de rama.

El usuario autorizó el commit de la selección de 536 archivos el 2026-10-11 («si de acuerdo»), conforme a la instrucción original «No hacer commits sin autorización expresa». El registro definitivo se identifica en el historial Git de esta rama; los recibos de verificación conservan su carácter de instantáneas previas al commit y su HEAD de entrada. Esta autorización no incluye push, despliegue ni activación. Una sola rama de entrega reúne archivos directos, manifiestos y paquetes; conservarla localmente todavía no equivale a tener un respaldo remoto.

La conciliación de aceptación se reproduce con `reconcile_acceptance.py`. Sus resultados son comprobaciones de evidencia ya existente: no una full regression actual ni una nueva aceptación. R1-04 permanece `PENDING` con limitación aceptada; R2-04 conserva el recibo físico correcto y la conciliación de su duración. No se diseñó ni ejecutó otra prueba.
