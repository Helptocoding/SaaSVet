"""É-F4 Fase 3 (ADR p55 §3) — ciclo de vida del compromiso.

Añade las coordenadas que faltaban (`return_to`, `supplanted_by`,
`blocked_reason`) y abre el enum de estados a `deviated / suspended / blocked /
abandoned`.

Sobre los datos existentes:

- `paused` → `deviated` es un **renombre limpio**: mismo significado, nombre
  más honesto (una pausa con dirección de retorno es un desvío). Se migra.
- `cancelled` **NO se migra**. Hoy conflaciona dos cosas —«otro objetivo lo
  suplantó» y «el cliente lo abandonó»— y no hay forma, fila por fila, de
  saber cuál fue. Reetiquetarlas a `abandoned` inventaría datos. Se quedan con
  el valor deprecado; el código nuevo escribe `suspended` o `abandoned`.

El constraint de "uno abierto por conversación" pasa a ser de **frente**
(`active|deviated`): un suspendido puede coexistir con el que lo suplantó —
que es justo lo que permite ofrecerlo de vuelta.
"""
from django.db import migrations, models


def paused_to_deviated(apps, schema_editor):
    apps.get_model('agent', 'ConversationGoal').objects.filter(
        status='paused').update(status='deviated')


def deviated_to_paused(apps, schema_editor):
    apps.get_model('agent', 'ConversationGoal').objects.filter(
        status='deviated').update(status='paused')


class Migration(migrations.Migration):

    dependencies = [
        ('agent', '0011_alter_humanhandoff_reason_code'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='conversationgoal',
            name='conversationgoal_one_open_per_conversation',
        ),
        migrations.AddField(
            model_name='conversationgoal',
            name='blocked_reason',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='conversationgoal',
            name='return_to',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='conversationgoal',
            name='supplanted_by',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AlterField(
            model_name='conversationgoal',
            name='status',
            field=models.CharField(
                choices=[
                    ('active', 'En curso'),
                    ('deviated', 'Desviado'),
                    ('suspended', 'Suspendido'),
                    ('blocked', 'Bloqueado'),
                    ('completed', 'Completado'),
                    ('abandoned', 'Abandonado'),
                    ('handoff', 'Escalado a humano'),
                    ('cancelled', 'Cancelado (deprecado)'),
                ],
                default='active', max_length=12),
        ),
        migrations.RunPython(paused_to_deviated, deviated_to_paused),
        migrations.AddConstraint(
            model_name='conversationgoal',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status__in', ('active', 'deviated'))),
                fields=('conversation',),
                name='conversationgoal_one_open_per_conversation'),
        ),
        migrations.AddConstraint(
            model_name='conversationgoal',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status', 'suspended')),
                fields=('conversation',),
                name='commitment_one_suspended_per_conversation'),
        ),
    ]
