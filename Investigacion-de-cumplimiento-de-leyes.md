# Guía de cumplimiento de seguridad y privacidad para Veteris/VetCare (SaaS veterinario, México)

## TL;DR
- **HIPAA NO te aplica.** HIPAA protege información de salud de **personas humanas**, no de animales; los expedientes clínicos veterinarios no son "PHI". Tus prioridades reales son la **ley mexicana de datos (LFPDPPP)** y las **responsabilidades residuales de PCI DSS vía Stripe**.
- **PCI DSS se reduce drásticamente con Stripe.** Si usas Stripe Checkout/Elements (campos hospedados) y nunca tocas datos de tarjeta, calificas al cuestionario más ligero (**SAQ A, 31 requisitos**). Stripe es PCI DSS Nivel 1 y te entrega su Attestation of Compliance (AOC).
- **ISO 27001 y SOC 2 son OPCIONALES pero recomendables** como marco para ordenar tu seguridad y para vender a clientes B2B; ninguno es obligatorio por ley en México, pero ambos te ayudan a demostrar las "medidas de seguridad" que la LFPDPPP sí exige (art. 18).

## Key Findings

1. **HIPAA: NO aplica (datos veterinarios no son PHI).** Bajo HIPAA, un "individuo" es "a human who is born alive" (45 CFR §160.103). Los animales son considerados propiedad, no personas. Los expedientes veterinarios quedan fuera del alcance de HIPAA.
2. **LFPDPPP es tu obligación legal #1.** Manejas datos personales de los dueños (nombre, contacto, datos de pago). Eso te convierte en "responsable" del tratamiento bajo la ley mexicana, con obligaciones concretas: aviso de privacidad, derechos ARCO, medidas de seguridad, notificación de brechas.
3. **Cambio regulatorio clave 2025:** El INAI desapareció (mandatado por el Decreto de simplificación orgánica publicado en el DOF el 20-dic-2024). Desde el 21 de marzo de 2025, la autoridad de datos personales es la **Secretaría Anticorrupción y Buen Gobierno**.
4. **PCI DSS vía Stripe = alcance mínimo, pero NO cero.** Sigues teniendo responsabilidades residuales: no almacenar PAN/CVV, usar integración hospedada, TLS, monitoreo de scripts, completar SAQ anual.
5. **ISO 27001 / SOC 2:** marcos voluntarios. ISO 27001 = certificación de un sistema de gestión (ISMS). SOC 2 = reporte de atestación de un CPA sobre tus controles. Ambos mapean a las medidas de seguridad que exige la LFPDPPP.

## Details

### 1. HIPAA — NO TE APLICA

**Qué es.** HIPAA (Health Insurance Portability and Accountability Act, 1996) es una ley **federal de EE.UU.** El HHS (Department of Health and Human Services) emitió la Privacy Rule y la Security Rule para proteger la "Protected Health Information" (PHI): información de salud individualmente identificable creada o manejada por "covered entities" (proveedores de salud, planes de salud, clearinghouses) y sus "business associates".

**Analogía.** HIPAA es como el reglamento interno de un club privado de EE.UU.: solo aplica a quienes son miembros (hospitales, aseguradoras de salud humana de EE.UU. y sus proveedores) y solo protege a pacientes **humanos**.

**¿Aplica a datos veterinarios/animales?** **No.** Bajo HIPAA, "individual" se define como la persona sujeta de la PHI, y "person" es "a human who is born alive" (45 CFR §160.103). Los animales no son individuos bajo HIPAA. Además, los veterinarios no realizan las transacciones electrónicas estándar que convierten a alguien en "covered entity". La única excepción tangencial sería si la información de un animal (p. ej. un animal de servicio) se guardara en el mismo "designated record set" que la PHI de un humano cubierto — escenario irrelevante para un SaaS veterinario.

**Conclusión para Felipe.** HIPAA es **irrelevante** para Veteris/VetCare. No proceses tu arquitectura contra HIPAA. (Nota: si algún día quisieras vender a un hospital/clínica humana en EE.UU., reevaluar; pero no por tratar datos de mascotas.) Lo que sí aplica a los datos de los **dueños humanos** es la ley mexicana de datos personales, no HIPAA.

### 2. LFPDPPP — TU PRINCIPAL OBLIGACIÓN LEGAL (México)

**Qué es.** La Ley Federal de Protección de Datos Personales en Posesión de los Particulares regula cómo las empresas privadas en México tratan datos personales. Una **nueva LFPDPPP** se publicó en el DOF el 20 de marzo de 2025 (firmada por la presidenta Claudia Sheinbaum Pardo) y entró en vigor el 21 de marzo de 2025, abrogando la ley de 2010.

**Cambio de autoridad (crítico).** Por la reforma constitucional de "simplificación orgánica" (Decreto en DOF del 20-dic-2024), el **INAI desapareció**. Sus funciones de protección de datos pasaron a la **Secretaría Anticorrupción y Buen Gobierno (SABG)**, que depende del Ejecutivo. Las funciones de transparencia y acceso a la información pasaron a un organismo desconcentrado llamado **"Transparencia para el Pueblo"**. Las resoluciones de la SABG se impugnan vía juicio de amparo ante tribunales especializados.

**¿Aplica a Felipe? SÍ, totalmente.** Veteris/VetCare trata datos personales de los dueños de mascotas (nombre, contacto, información personal, referencias de pago). Eres un "responsable" del tratamiento.

**Obligaciones concretas (con artículos de la nueva ley 2025, verificados contra el texto oficial de diputados.gob.mx):**
- **Principios rectores (art. 5):** licitud, finalidad, lealtad, consentimiento, calidad, proporcionalidad, información y responsabilidad.
- **Aviso de privacidad (arts. 14-16):** debe contener identidad/domicilio del responsable; los datos que se tratarán identificando los sensibles; finalidades (distinguiendo las que requieren consentimiento de las que no); medios para limitar uso/divulgación; mecanismos para ejercer ARCO; y procedimiento para comunicar cambios. Debe ponerse a disposición en el momento de la recolección.
- **Consentimiento:** regla general tácito; **expreso para datos financieros/patrimoniales (art. 7)**; **expreso y por escrito para datos sensibles (art. 8)**.
- **Derechos ARCO (arts. 21-26):** Acceso (22), Rectificación (23), Cancelación (24), Oposición (26). Debes responder en un plazo máximo de **20 días hábiles (art. 31)**, y si procede, hacerlo efectivo en los 15 días siguientes.
- **Medidas de seguridad (art. 18):** "Todo responsable deberá establecer y mantener medidas de seguridad administrativas, técnicas y físicas que permitan proteger los datos personales contra daño, pérdida, alteración, destrucción o el uso, acceso o tratamiento no autorizado." Deben considerar el riesgo, la sensibilidad y el desarrollo tecnológico.
- **Notificación de vulneraciones (art. 19):** debes informar **de forma inmediata** al titular las brechas que afecten significativamente sus derechos patrimoniales o morales.
- **Sanciones (art. 59):** estructura de dos tramos — **multa de 100 a 160,000 UMAs** (infracciones menores) y **de 200 a 320,000 UMAs** (infracciones graves); las sanciones **pueden incrementarse hasta por dos veces** cuando involucren datos sensibles. **Delitos (arts. 62-64):** prisión de **3 meses a 3 años** por provocar una vulneración con ánimo de lucro (art. 62), de **6 meses a 5 años** por tratamiento mediante engaño con lucro indebido (art. 63), **duplicable con datos sensibles** (art. 64).

**Qué debe revisar el agente de IA en código/arquitectura para LFPDPPP:**
- Existencia de un aviso de privacidad accesible desde el momento de recolección (landing y app).
- Gestión de consentimiento: checkboxes no premarcados, registro/log de consentimiento, mecanismo de revocación simple y gratuito.
- Implementación funcional de derechos ARCO: endpoints o procesos para exportar (acceso), rectificar, cancelar (borrar) y oponerse.
- Cifrado en reposo y en tránsito (TLS) de los datos de dueños.
- Control de acceso basado en roles (RBAC), principio de mínimo privilegio, MFA.
- Logs de acceso a datos personales y plan de respuesta a incidentes (para cumplir art. 19).
- Contrato de encargado ("data processing agreement") con subprocesadores (hosting, Stripe, email).

### 3. PCI DSS — ALCANCE MÍNIMO VÍA STRIPE (pero con responsabilidades residuales)

**Qué es.** El PCI DSS (Payment Card Industry Data Security Standard) es un estándar del PCI Security Standards Council (fundado por Visa, Mastercard, Amex, Discover, JCB) que protege los datos de tarjeta. No es ley; lo imponen contractualmente las marcas y los bancos adquirentes. Versión actual: **v4.0.1**, mandatoria desde el 31 de marzo de 2025.

**Analogía.** PCI DSS es como las reglas de manejo de efectivo de una franquicia: si tú nunca tocas el efectivo (porque un camión blindado —Stripe— lo recoge y procesa), tus obligaciones se reducen a no dejar la puerta abierta y firmar un papel diciendo que el camión blindado hace el trabajo pesado.

**Niveles de comerciante** (por volumen anual de transacciones): Nivel 1 (>6M), Nivel 2 (1-6M), Nivel 3 (20k-1M), Nivel 4 (<20k). Felipe será Nivel 4 (el más bajo). Los niveles 2-4 pueden validar con un **SAQ (Self-Assessment Questionnaire)** en lugar de auditoría QSA.

**Stripe absorbe la mayor parte.** Stripe es **PCI DSS Nivel 1 Service Provider**, certificado anualmente por un QSA (Coalfire). Con Stripe Checkout o Elements, los datos de tarjeta se capturan en campos hospedados que envían la información directamente a los servidores validados de Stripe **sin tocar tu servidor**. Stripe te provee su **Attestation of Compliance (AOC)** y un "wizard" en el Dashboard que pre-llena tu SAQ.

**El SAQ que te corresponde — depende de la integración (cifras de URM Consulting, QSA):**
- **SAQ A (31 requisitos, el más ligero):** si usas Stripe Checkout (página hospedada/redirect) o Elements vía iframe, y **ningún elemento de la página de pago se origina en tu servidor**. Este es tu objetivo.
- **SAQ A-EP (151 requisitos):** si tu página de pago ejecuta scripts servidos desde tu propio dominio que pueden afectar el pago (p.ej. Stripe.js v2 con campos propios). Requiere escaneos ASV trimestrales, file integrity monitoring, pruebas de penetración.
- **SAQ D (todos los requisitos; 300+ controles, alcance máximo):** si capturaras/almacenaras datos de tarjeta directamente. **Evítalo.**

**Contraste de alcance (clave para Felipe):** procesar tarjetas directamente = SAQ D, máximo esfuerzo. Usar Checkout/Elements hospedados = SAQ A, mínimo esfuerzo. La diferencia es una **decisión de arquitectura**, no de papeleo: mantén toda captura de tarjeta dentro del iframe/redirect de Stripe. El error más común es asumir que un iframe automáticamente da SAQ A — si cargas un solo script propio (analytics, pixel) en la página de pago, puedes caer en SAQ A-EP.

**Responsabilidades residuales que SIGUEN siendo de Felipe aún con Stripe:**
- **No almacenar** PAN completo ni CVV en tu base de datos ni en logs. (Puedes guardar lo que Stripe devuelve: marca, últimos 4 dígitos, expiración — no sujeto a PCI.)
- Usar **tokens de Stripe** (customer/payment method) en vez de datos crudos.
- Mantener **TLS/HTTPS** en todo el sitio.
- **SAQ A bajo v4.0.1 ahora exige escaneos ASV trimestrales** (cada 90 días) y confirmar que tu sitio no es susceptible a ataques de scripts (e-skimming/Magecart). Nota: el **30 de enero de 2025** el PCI SSC removió los requisitos **6.4.3, 11.6.1 y 12.3.1** del SAQ A (efectivo el 31-mar-2025), pero añadió un **criterio de elegibilidad** que exige confirmar que todo el sitio está protegido contra scripts maliciosos.
- Completar y renovar el **SAQ A anualmente** y subirlo al Dashboard de Stripe.
- Obtener y archivar el **AOC de Stripe**.

**Los 12 requisitos de PCI DSS v4.0 (para contexto del agente):** (1) controles de seguridad de red/firewall; (2) configuraciones seguras (no defaults); (3) proteger datos de cuenta almacenados; (4) cifrar transmisión en redes públicas; (5) anti-malware; (6) desarrollo y sistemas seguros; (7) restringir acceso por need-to-know; (8) identificación y autenticación (MFA); (9) restringir acceso físico; (10) registrar y monitorear accesos; (11) probar seguridad regularmente (escaneos/pentest); (12) política de seguridad de la información. Con SAQ A, la mayoría se cumplen vía Stripe; los que siguen siendo tuyos son principalmente 6 (código seguro), 8 (acceso), 9 (físico, si aplica), 12 (política), y la protección de la página de pago.

**Qué debe revisar el agente en código/arquitectura para PCI:**
- Confirmar que NO hay campos `card_number`, `cvc`, `exp_month`, `exp_year` capturados/enviados a tu backend.
- Confirmar que la integración usa Stripe Elements/Checkout (iframe hospedado) y no un formulario propio que postea a tu API.
- Buscar en logs cualquier filtración de PAN/CVV.
- Verificar HTTPS forzado, headers de seguridad, e inventario de scripts en la página de pago.

### 4. ISO 27001 — MARCO VOLUNTARIO RECOMENDADO

**Qué es.** ISO/IEC 27001 es el estándar internacional (publicado por ISO e IEC; versión vigente 2022) para un **Sistema de Gestión de Seguridad de la Información (ISMS/SGSI)**. No es específico de industria ni geografía: aplica a cualquier organización que maneje información.

**Analogía.** ISO 27001 no es una lista de tareas, es un "sistema operativo" para gestionar la seguridad: te obliga a identificar riesgos, decidir qué controles aplicar y mejorar continuamente. Es como instalar un proceso de calidad, no solo poner candados sueltos.

**Estructura:**
- **Cláusulas 4-10 (obligatorias para certificación):** contexto de la organización, liderazgo, planificación (evaluación y tratamiento de riesgos), soporte, operación, evaluación del desempeño, mejora.
- **Anexo A:** 93 controles agrupados en 4 temas — **Organizacionales (A.5, 37), Personas (A.6, 8), Físicos (A.7, 14), Tecnológicos (A.8, 34)**; incluye 11 controles nuevos en la versión 2022 (p.ej. A.5.7 threat intelligence, A.5.23 seguridad en servicios cloud, A.8.28 secure coding). No implementas todos: eliges según tu evaluación de riesgos y documentas tu **Statement of Applicability (SoA)**.

**¿Aplica a Felipe?** Como obligación, no. Como herramienta, sí es muy recomendable. No es obligatorio por ley en México, pero sus controles **mapean directamente a las medidas de seguridad que la LFPDPPP sí exige (art. 18)**.

**Controles del Anexo A más relevantes para un SaaS pequeño:** políticas y roles (A.5), seguridad en servicios cloud (A.5.23), control de acceso (A.8.2-8.5), cifrado/criptografía (A.8.24), gestión de vulnerabilidades, registro y monitoreo/logging (A.8.15-8.16), desarrollo seguro/secure coding (A.8.28), gestión de incidentes, y respaldos.

**Qué implicaría certificarse:** definir alcance, evaluación de riesgos, SoA, ~20-25 políticas, auditoría interna, y auditoría externa de 2 etapas por un organismo acreditado. Certificado válido 3 años con auditorías anuales de vigilancia. Para alinearse sin certificar, basta implementar los controles relevantes y operar la evidencia (logs, actas, pruebas de respaldo).

### 5. SOC 2 — MARCO VOLUNTARIO (estándar de facto para SaaS B2B)

**Qué es.** SOC 2 (System and Organization Controls 2) es un marco de la **AICPA (American Institute of CPAs)**. No es una certificación sino un **reporte de atestación** que emite una firma de contadores públicos (CPA) sobre tus controles, evaluados contra los **Trust Services Criteria (TSC)** definidos en TSP Section 100.

**Analogía.** SOC 2 es como una carta de recomendación auditada: un tercero independiente (un CPA) examina tus controles y firma un reporte que tus clientes corporativos piden antes de confiarte sus datos.

**Los 5 Trust Services Criteria:** **Security (obligatorio, llamado "Common Criteria" CC1-CC9)**, Availability, Processing Integrity, Confidentiality, Privacy. Solo Security es obligatorio; los demás se añaden según lo que prometas a clientes. Para un SaaS típico, Security (a veces + Availability) basta para el primer reporte.

**Type I vs Type II:**
- **Type I:** evalúa el **diseño** de los controles en un punto en el tiempo (snapshot). Más rápido, bueno como primer paso.
- **Type II:** evalúa el **diseño Y la efectividad operativa** durante un periodo (típicamente 6-12 meses). Es el que los clientes enterprise realmente exigen.

**¿Aplica a Felipe?** No por ley. Es relevante cuando empieces a vender a clientes B2B grandes (cadenas de clínicas, corporativos) que lo exijan en su due diligence. Es prácticamente el estándar de facto que clientes B2B piden a proveedores SaaS.

**Qué implicaría prepararse:** definir alcance (típicamente solo producción), gap analysis, implementar controles (RBAC, MFA, cifrado, logging, gestión de cambios, gestión de vendors, respuesta a incidentes), recolectar evidencia, y contratar un CPA. Timeline típico: Type I en 3-5 meses; Type II suma 6-12 meses de ventana de observación.

### Relación entre los marcos y la ley mexicana

ISO 27001 y SOC 2 NO sustituyen a la LFPDPPP (que es ley y obligatoria), pero la **operacionalizan**: los controles técnicos de ambos (control de acceso, cifrado, gestión de incidentes, logging) son exactamente la evidencia de las "medidas de seguridad administrativas, técnicas y físicas" del art. 18 de la LFPDPPP. Implementar uno de estos marcos te da el cumplimiento técnico de la ley "gratis". Igualmente, los controles que implementes para PCI SAQ A (TLS, no almacenar datos sensibles, control de acceso) se solapan con ISO/SOC 2 y con el art. 18.

## Recommendations

**Fase 1 — Inmediato (cumplimiento legal y de pagos, lo no-negociable):**
1. **LFPDPPP:** Redacta y publica un aviso de privacidad conforme a los arts. 14-16 (landing + app). Implementa gestión de consentimiento, procesos ARCO (respuesta ≤20 días hábiles) y un plan de notificación de brechas (art. 19). Designa una persona/departamento de datos personales. Actualiza cualquier referencia al "INAI" → "Secretaría Anticorrupción y Buen Gobierno".
2. **PCI DSS:** Confirma que toda captura de tarjeta usa Stripe Checkout/Elements (iframe/redirect), que NO almacenas PAN/CVV, y que no hay fugas en logs. Completa el **SAQ A** vía el wizard de Stripe, contrata escaneos ASV trimestrales, y archiva el **AOC de Stripe**.

**Fase 2 — Higiene de seguridad (alinea con art. 18 LFPDPPP + base para ISO/SOC2):**
3. Implementa: cifrado en reposo y en tránsito, RBAC con mínimo privilegio, MFA en accesos a producción, logging de accesos a datos personales, gestión de cambios (code review + tickets), respaldos probados, y un plan de respuesta a incidentes documentado.

**Fase 3 — Cuando lo pida el mercado (no antes):**
4. Si un cliente B2B grande lo exige o levantas capital: persigue **SOC 2 Type I → Type II** (más común en venta a EE.UU./enterprise) o **ISO 27001** (más reconocido internacionalmente). Empieza por un gap analysis.

**Benchmarks que cambian estas recomendaciones:**
- Si **expandes a EE.UU. vendiendo a clínicas/hospitales humanos** → reevaluar HIPAA (improbable en veterinaria).
- Si **superas ~20,000 transacciones/año** o cambias de integración → reevaluar nivel PCI y tipo de SAQ.
- Si **empiezas a capturar datos de tarjeta directamente** → caes en SAQ D (evítalo a toda costa).
- Si un **cliente enterprise exige SOC 2/ISO** → activa Fase 3.

## Caveats
- La **nueva LFPDPPP (2025)** aún espera la armonización de su Reglamento (el Ejecutivo tenía 90 días para emitir ajustes); algunos detalles operativos (transferencias, aviso simplificado, alcance de "titular" que ahora podría incluir personas morales) podrían precisarse. Consulta a un abogado mexicano de datos para el aviso de privacidad final.
- Las referencias a artículos específicos corresponden al texto oficial de la LFPDPPP publicado por la Cámara de Diputados (diputados.gob.mx), vigente a junio 2026 (incluye la reforma del 14-nov-2025, que solo modificó el art. 4 sobre supletoriedad). Nota: la ley de 2025 renumeró artículos respecto a la de 2010 — en la de 2010, medidas de seguridad estaban en el art. 19 y notificación de brechas en el art. 20; en la de 2025 son los arts. 18 y 19.
- PCI DSS no es ley; es contractual. Tu banco adquirente o Stripe pueden imponer requisitos adicionales (p.ej. confirmar ASV scans). Verifica con ellos directamente.
- Las cifras de costos/tiempos de SOC 2 e ISO 27001 provienen de proveedores de servicios de compliance y varían según alcance; trátalas como estimaciones, no garantías.
- Este reporte es orientativo para guiar la auditoría de tu código/arquitectura por un agente de IA; no sustituye asesoría legal profesional.