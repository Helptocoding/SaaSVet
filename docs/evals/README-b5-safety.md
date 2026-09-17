# Corpus técnico B5 v1

[JSON versionado](b5-safety-v1.json): textos sintéticos, expectativas discretas
y familias revisables. **VETERINARY_REVIEW_REQUIRED**. No nombres ni aprobación
de veterinarios; los resultados no son sensibilidad clínica.

125 casos: 53 positivos (críticos, indirectos y multi-turn) y 72 negativos.
Incluye negaciones, históricos, hipotéticos, contexto administrativo,
referencias/sujeto, coloquial mexicano/latino y typos acotados. Una lista `texts`
representa turnos sucesivos: el último es el actual. La prueba de ráfaga real
usa además todos los miembros del TurnContext B3 como actuales.

La métrica binaria considera URGENT/POSSIBLE_URGENT como escalar; la prueba
también exige clasificación discreta exacta. Reportar TP, FN, TN, FP; recall de
críticos y FPR separado por negación/historia/hipótesis. NO_SIGNAL nunca autoriza
decir que no hay emergencia. No optimizar sobre una accuracy que oculte FN/FP.

Desde backend, con entorno de pruebas aislado:

```text
rtk proxy python manage.py test apps.agent.tests.test_b5_corpus --verbosity 2
```

Resultados finales y límites en el [acta B5](../implementacion-b5-agente-whatsapp-2026-09-16md).
Revisión futura debe considerar nuevas paráfrasis, dialectos, contradicciones,
cambio de sujeto y errores de cobertura; incorporar los contraejemplos al corpus.
