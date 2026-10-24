# Triaje posterior de Gitleaks — B9 r12

La puerta de seguridad continúa **FAIL**. El candidato y el reporte original no cambiaron.

El reporte contiene **3156 detecciones generic-api-key**, distribuidas en 221 rutas y 16 commits con hallazgos. Esto no equivale a 3156 credenciales distintas.

- **2606** detecciones tienen contexto verificado de propiedades de archivos fuente .py con valores de forma SHA256 en documentos JSON/JSONL históricos.
- **550** detecciones quedan **NOT_CLASSIFIED_CREDENTIAL_VALIDITY**; el contexto redactado no permite declarar que sean credenciales reales ni falsos positivos.
- No se confirmó ninguna credencial activa mediante este análisis; tampoco se demuestra su ausencia.

Se inspeccionaron nombres de campos de Match redactados, RuleID, File y Commit. Para verificar los metadatos se leyeron objetos Git históricos de docs, sin imprimir valores. Se conservaron todos los hallazgos originales.

No se repitieron el escáner ni las pruebas; no se cambiaron fuentes, sellos ni allowlists.

Contextos de campo reportados (nombres únicamente):

| Contexto | Detecciones |
| --- | ---: |
| password.py | 604 |
| key | 424 |
| api.py | 395 |
| authorization.py | 199 |
| authorization_message.py | 198 |
| key.py | 152 |
| token.py | 152 |
| key_and_more.py | 151 |
| api_contract.py | 151 |
| authoritative_flow.py | 151 |
| authentication.py | 151 |
| auth_no_store.py | 151 |
| auth.py | 151 |
| token | 119 |
| KEY | 5 |
| SECRET_KEY | 1 |
| SECRET | 1 |

Los nombres de contexto pueden ser sufijos del campo original porque la regla inicia el Match en su palabra clave. La verificación JSON recupera el nombre completo cuando es posible. La clasificación y los grupos por ruta/commit constan en security-finding-triage.json.

Los 25 casos frontend filtrados, los 355 PASS frontend y los resultados backend previos no se ejecutaron durante este triaje.
