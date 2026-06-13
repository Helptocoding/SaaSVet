# ADR p36: Capa de tema compartido para documentos PDF (Fase 1 del rediseño)

**Fecha**: 2026-06-11
**Estado**: Implementado (Fase 1). Fase 2 (branding por organización) aprobada en dirección, pendiente de ADR propio al implementarse.

## Contexto

El SaaS genera tres documentos PDF: resumen de consulta (`medical_records`), receta
(`prescriptions`) y cobro (`billing`). Antes de este ADR:

1. **Tres generadores ad-hoc** — cada view definía sus propios `ParagraphStyle` y estilos
   de tabla (duplicación triple, cero identidad visual: Helvetica genérica, grids grises
   estilo Excel, sin membrete).
2. **Bug real en receta**: `prescription_pdf` usaba canvas crudo de ReportLab con cursor
   `y` manual **sin manejo de salto de página** — una receta con muchos ítems dibujaba
   fuera del área visible y el contenido se perdía al imprimir.
3. **Fechas en UTC**: los `strftime` se aplicaban sobre datetimes UTC sin convertir a la
   timezone de la organización (6-7h de desfase para México).
4. **Nombres de descarga rotos en la práctica**: el backend armaba
   `consulta_<id>_<mascota>.pdf`, pero faltaba `CORS_EXPOSE_HEADERS` — axios no puede
   leer `Content-Disposition` cross-origin, `extractFilename()` caía al fallback
   genérico y el browser numeraba duplicados ("consulta (1).pdf").

Los documentos son la cara visible del SaaS frente al cliente final de la clínica; su
calidad percibida es parte del producto.

## Decisión

### 1. Capa compartida `apps/core/pdf/` (paquete)

```
apps/core/pdf/
├── __init__.py      — API pública (re-exporta también pdf_utils para import único)
├── theme.py         — DocumentTheme (paleta+tipografía) + build_styles() + get_theme_for_organization()
├── components.py    — title_block, section, info_card, data_table, totals_table,
│                      numbered_item, signature_block
└── document.py      — render_branded_pdf(): membrete por página, "Página N de M"
                       (canvas de dos pasadas), watermark, geometría (CONTENT_WIDTH)
```

**Boundary**: `core/pdf` es dueño del **CÓMO se ve** (presentación); cada dominio sigue
siendo dueño del **QUÉ datos** lleva su documento (el view arma los flowables). Sin
imports cross-dominio nuevos. `apps/core/pdf_utils.py` se conserva (saneo + naming);
el paquete lo re-exporta.

**Regla dura**: nada en `core/pdf` ejecuta queries. Los tests de N+1 de los endpoints
PDF (`assertNumQueries` estricto en billing) dependen de eso.

### 2. Receta: canvas crudo → platypus

`prescription_pdf` reescrito sobre flowables. Pagina correctamente (mata el bug de
overflow), `KeepTogether` por medicamento, bloque de firma del veterinario. Test de
regresión: 40 ítems → 2+ páginas y el último medicamento presente en el texto extraído.

### 3. Chrome por página + watermark de estado

- Header: nombre de la clínica (verde bosque `#1a4434`, fit-to-width con elipsis) +
  tipo de documento; regla de marca. Footer: fecha de generación (tz org) +
  "Página N de M". Se repite en cada página (`onPage` callbacks + NumberedCanvas).
- **Watermark en cobros**: `draft` → "BORRADOR", `cancelled` → "CANCELADO" (diagonal,
  alpha bajo). Un draft impreso no debe poder pasar por comprobante final.
- Tema por defecto = identidad del design system (`frontend/design-system.md`):
  brand `#1a4434`, cards cream `#f5f1e8`, hairlines `#d9d2be`. El color de marca solo
  se usa en acentos (títulos, reglas, header), nunca en body text.

### 4. Fechas en timezone de la organización

Todo datetime mostrado en PDFs pasa por `utc_to_local(org, value)`
(`apps/core/datetime_utils`). La fecha de generación del footer usa `org_now_local`.

### 5. Nombres de descarga identificables (contrato con frontend)

- Helper único `pdf_filename(prefix, pk, name_segment, local_date)` en
  `core/pdf_utils.py` → `tipo_id_mascota_YYYY-MM-DD.pdf`
  (ej. `receta_142_Rocky_2026-06-10.pdf`; segmento vacío → `documento`;
  factura sin mascota → `sin-mascota`).
- **`CORS_EXPOSE_HEADERS = ['content-disposition']`** en settings — sin esto el
  frontend jamás ve el nombre. Test de contrato:
  `apps/core/tests/test_pdf_utils.py::PdfDownloadCorsContractTests`.

### 6. Branding-ready (gancho para Fase 2)

`get_theme_for_organization(org)` es el **único punto** que cambiará cuando exista
branding por tenant: hoy retorna `DEFAULT_THEME`; en Fase 2 leerá el branding de la
organización con fallback al default. Los views no se tocan.

## Alternativas descartadas

- **WeasyPrint (HTML/CSS → PDF)**: exige Pango/Cairo nativos (fricción en dev Windows,
  peso en imagen Docker) y tiraba los 3 generadores + tests existentes. ReportLab ya
  estaba en producción y platypus alcanza la calidad requerida.
- **Render en frontend (react-pdf / print CSS)**: pierde autoridad server-side
  (multitenancy, RBAC, datos frescos) y duplica lógica de dominio en el cliente.
- **Status quo (estilos por view)**: triple duplicación; el branding por organización
  (Fase 2) habría requerido tocar N views en lugar de 1 función.

## Fase 2 (dirección aprobada — ADR propio al implementar)

Modelo `OrganizationBranding` (OneToOne, patrón `OrganizationSettings`): logo
**BinaryField en DB** (no hay infra MEDIA y el filesystem de Railway es efímero;
cap ~200KB con re-encode Pillow; **SVG prohibido** — vector XSS/SSRF), `brand_color`,
dirección/teléfono/email/RFC/leyenda. Endpoints `GET/PATCH /api/organizations/me/branding/`.
Además: `User.license_number` (cédula profesional en receta), expediente interno
`GET /api/medical-records/<uuid>/pdf/full/`, campos opcionales `next_visit_date` y
`client_instructions` en `MedicalRecord`.

## Consecuencias

- (+) Identidad visual consistente en los 3 documentos; un solo lugar para evolucionarla.
- (+) Bug de overflow de receta eliminado; fechas correctas para México.
- (+) Descargas con nombre identificable (`tipo_id_mascota_fecha.pdf`).
- (−) Nueva superficie compartida en `core` — cambios al tema afectan a los 3 documentos
  (mitigado: smoke tests del paquete + markers por documento).
- (~) `pypdf` sigue siendo dependencia solo-tests (extracción de texto).

## Tests

- `apps/core/tests/test_pdf_theme.py` — smoke del paquete (SimpleTestCase, sin DB):
  chrome multipágina, numeración, watermark, org name largo, tint, edge cases.
- `apps/core/tests/test_pdf_utils.py` — `pdf_filename` + contrato CORS expose.
- `apps/prescriptions/tests/test_pdf.py` — regresión overflow (40 ítems → 2+ páginas),
  markers, cross-tenant 404, filename con fecha.
- `apps/medical_records/tests/test_pdf.py` y `apps/billing/tests/test_invoice_pdf.py` —
  suites previas intactas + watermarks por estado + filename con fecha.
