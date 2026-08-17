"""F5 · retirar `Conversation.summary` — fase CONTRACT.

Se declaró en É-F1 como «resumen rodante» y **nunca se escribió ni se leyó**: en
producción, 20 conversaciones y 0 con contenido. La continuidad acabó
resolviéndose por otro camino (F2: el transcript se lee por contacto; F4: los
hechos duraderos salen de tools), así que el resumen habría sido una segunda
fuente de verdad —lo que prohíbe ADR p50— con su propia superficie de fuga.

**Por qué esta migración va DESPUÉS del despliegue de F2-F4 y no con ellas**:
borrar una columna es la única operación de este trabajo que no es aditiva. Entre
el `migrate` y el arranque de la versión nueva hay un instante en el que el
código viejo podría consultarla; y si hiciera falta un rollback de imagen, el
código anterior esperaría una columna que ya no está. Con F2-F4 ya en producción
(`a00afb6`), el código que se puede revertir tampoco la referencia.

Verificado vacío antes de aplicar. No hay dato que preservar, así que no hay
backfill inverso: `RemoveField` es reversible en el esquema y el contenido era
cadena vacía en el 100 % de las filas.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0017_contactidentity_public_id'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='conversation',
            name='summary',
        ),
    ]
