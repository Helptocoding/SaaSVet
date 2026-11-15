# E02 — G09: disponibilidad por intervalos reales

Primero lee y aplica `docs/remediaciones/orden-8/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

La documentación del agente dice que la oferta de horarios «compara `start_time` exacto» y no ve citas largas ni fuera de la rejilla (deuda MP-5). Ya no es cierto: desde B2 (`9ccc31a`, 15-09) `_day_occupancy` guarda el intervalo de cada cita activa y `_vet_free` descarta cualquier hueco que se solape. Esta entrega **no cambia código de producción**: añade pruebas que fijan ese comportamiento y el límite que queda, y corrige la documentación.

El límite que queda, y que se declara: el agente ofrece citas de 30 min (`SLOT_MINUTES`), en pasos de 30 desde la apertura de cada tramo. Una ventana libre fuera de esa rejilla no se ofrece, y el dominio no tiene duración por servicio.

## Precondición

`git log --oneline -1` muestra `feat(agent): restrict TurnDecision verdict to the arbiter verdicts (order 8, G07)`. En `MATRIZ.md` G07 está en `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Si no, `BLOQUEADA`.

## Archivos permitidos

- `backend/apps/agent/tests/test_slots.py`
- `docs/modules/agent.md`
- `docs/remediaciones/orden-8/MATRIZ.md` y `docs/remediaciones/orden-8/EVIDENCIA.md`

`backend/apps/agent/tools.py` **no se toca**. Si una prueba nueva falla, es que el comportamiento no es el descrito: `BLOQUEADA`, sin ajustar la prueba ni el código.

## Contexto

- `SlotsTests` usa un día hábil a 7 días, horario de 09:00 a 13:00 en zona UTC, un solo veterinario y la API real del agente. `find_available_slots` devuelve como mucho tres horarios.
- `_book` solo reserva citas de 30 min en la rejilla. El helper nuevo `_book_range` reserva cualquier intervalo; `_book` no se modifica.
- Con la regla antigua (inicio exacto), tres de las cuatro pruebas nuevas fallan. La cuarta fija el límite de la rejilla, que no depende de esa regla.

## Cambios

Aplícalos en este orden.

### Cambio 1 — `backend/apps/agent/tests/test_slots.py`

Texto actual:

```python
    def test_excludes_occupied_slot(self):
        self._book("09:00")
        out = self._run({"date": self.day.isoformat()})
        times = [s["iso_time"] for s in out.data]
        self.assertNotIn("09:00", times)
        self.assertIn("09:30", times)
```

Texto nuevo:

```python
    def test_excludes_occupied_slot(self):
        self._book("09:00")
        out = self._run({"date": self.day.isoformat()})
        times = [s["iso_time"] for s in out.data]
        self.assertNotIn("09:00", times)
        self.assertIn("09:30", times)

    # ── G09 (orden 8): la ocupación se compara por intervalos reales ──────
    # `_day_occupancy` guarda (inicio, fin) de cada cita activa y `_vet_free`
    # descarta un hueco que se solape con cualquiera. Estas pruebas fijan ese
    # comportamiento y el límite que queda: la oferta es de 30 min, en la
    # rejilla que empieza en la apertura de cada tramo.

    def _book_range(self, start_hhmm, end_hhmm):
        """Cita de duración arbitraria, también fuera de la rejilla de 30 min."""
        from datetime import datetime
        from datetime import timezone as dt_tz
        start = datetime.strptime(start_hhmm, "%H:%M").time()
        end = datetime.strptime(end_hhmm, "%H:%M").time()
        Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, reason="x",
            status="scheduled",
            start_datetime=datetime.combine(self.day, start, tzinfo=dt_tz.utc),
            end_datetime=datetime.combine(self.day, end, tzinfo=dt_tz.utc),
        )

    def test_long_appointment_blocks_every_slot_it_covers(self):
        self._book_range("09:00", "10:30")
        out = self._run({"date": self.day.isoformat()})
        self.assertTrue(out.ok, out.client_error)
        self.assertEqual([s["iso_time"] for s in out.data], ["10:30", "11:00", "11:30"])

    def test_off_grid_appointment_blocks_the_slots_it_overlaps(self):
        self._book_range("09:15", "09:45")
        out = self._run({"date": self.day.isoformat()})
        self.assertTrue(out.ok, out.client_error)
        self.assertEqual([s["iso_time"] for s in out.data], ["10:00", "10:30", "11:00"])

    def test_exact_time_check_detects_a_partial_overlap(self):
        self._book_range("09:45", "10:15")
        exact = self._check({"date": self.day.isoformat(), "time": "10:00"})
        self.assertTrue(exact.ok, exact.client_error)
        self.assertFalse(exact.data["available"])
        self.assertEqual(exact.data["reason"], "slot_taken")

    def test_offer_stays_on_the_half_hour_grid(self):
        # Límite conocido: tras una cita de 09:00 a 09:15 queda libre desde
        # las 09:15, pero la oferta sigue la rejilla y empieza a las 09:30.
        self._book_range("09:00", "09:15")
        out = self._run({"date": self.day.isoformat()})
        self.assertTrue(out.ok, out.client_error)
        self.assertEqual(out.data[0]["iso_time"], "09:30")
```

### Cambio 2 — `docs/modules/agent.md`

Texto actual (al final de «Asignación de veterinario»):

````markdown
Limitación conocida (deuda MP-5 de la auditoría): la rejilla compara
`start_time` exacto en pasos de 30 min, así que no modela duraciones distintas
ni citas fuera de rejilla. El dominio revalida el solape real al crear; si
pierde la carrera, el agente re-oferta.
````

Texto nuevo:

````markdown
**Ocupación por intervalos (deuda MP-5 de la auditoría, revalidada en el
orden 8, G09).** Desde B2 (`9ccc31a`, 15-09) `_day_occupancy` guarda el
inicio y el fin de cada cita activa, y `_vet_free` descarta un hueco que se
solape con cualquiera de ellas. Por eso una cita larga (09:00–10:30) tapa
todos los huecos que cubre y una cita fuera de la rejilla (09:15–09:45) tapa
los dos que pisa; `check_appointment_slot` detecta también el solape parcial.
Lo fijan las pruebas de `tests/test_slots.py`.

Límite que queda: el agente ofrece citas de **30 min** (`SLOT_MINUTES`, la
misma duración que la atención sin cita), en pasos de 30 desde la apertura de
cada tramo del horario. Una ventana libre fuera de esa rejilla (las 09:15 tras
una cita de 09:00 a 09:15) no se ofrece, y el dominio no tiene duración por
servicio. El dominio revalida el solape real al crear (INV-D); si pierde la
carrera, el agente re-oferta.
````

## Verificación

Desde `backend/`, conservando cada salida:

```bash
R="rtk proxy python scripts/orden8_isolated.py"
python -m py_compile apps/agent/tests/test_slots.py && echo "py_compile OK"
git diff --stat HEAD -- apps/agent/tools.py
$R makemigrations --check --dry-run 2>&1 | tail -2
$R test apps.agent.tests.test_slots --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -20
```

Esperado:

- `py_compile OK`.
- `git diff --stat` sobre `tools.py` no imprime nada.
- `No changes detected`.
- **`Ran 12 tests`** y `OK`.

## Cierre

- `MATRIZ.md`: G09 pasa a `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, con entrega E02, el commit y `EVIDENCIA.md §E02`. Completa la fila E02 del avance.
- `EVIDENCIA.md`: sección E02 con las salidas. Límites: el agente sigue ofreciendo solo citas de 30 min en la rejilla; ofrecer ventanas fuera de ella o duraciones por servicio es una extensión de producto que no entra en este orden. Sin cambios de código de producción.

Commit: `test(agent): pin interval-based availability and document grid limit (order 8, G09)`.
