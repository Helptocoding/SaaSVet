# Consolidación histórica en develop — 23 de octubre de 2026

Se revisaron los 50 archivos pendientes de seis árboles. El manifiesto relaciona cada variante con su árbol, commit de origen, destino y hash SHA-256. Los árboles originales permanecen intactos. Los archivos de artifacts son texto histórico inerte: no se cargan como configuración, instrucciones de agentes ni código de la aplicación.

- La implementación actual de agenda ya contiene los tres commits equivalentes de PlanWA-02 y sus garantías posteriores de bloqueo por veterinario y estado esperado. No se reemplaza con el código antiguo, que incluía una referencia de prueba inválida. Se rescata por separado la cobertura útil de creación concurrente entre endpoints.
- Las variantes AGENTS/OCR/agtx y las rutas locales WSL se conservan como antecedentes; no sustituyen la configuración actual ni se activan archivos privados de máquina. Las tres copias idénticas se relacionan con un mismo artefacto.
- El documento actual de arquitectura mantiene Checkout y el ciclo de Invoice inmutable. La variante antigua se conserva aquí sin revertir esa descripción.
- Los doce archivos del diagnóstico causal se incorporan en docs/evals/e4-causal-audit-2026-10-03 sin cambiar bytes. Su conclusión STOP/ROOT_CAUSE_NOT_CONFIRMED es histórica, no una validación nueva.

La consolidación no activa WhatsApp/B2 ni publica textos legales. El FAIL de latencia B9 y la falta de responsable/canal de alertas siguen registrados como deudas no bloqueantes aceptadas por el usuario. Los gates reales pendientes conservan su estado.
