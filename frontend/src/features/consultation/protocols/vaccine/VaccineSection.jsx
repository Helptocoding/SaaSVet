import { forwardRef, useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Icon } from "../../../../components/icons";
import SearchSelect from "../../../../components/SearchSelect";
import DateField from "../../../../components/DateField";
import { getProductLots } from "../../../../api/inventory";
import styles from "../../../../pages/medicalRecords/consultationForm.module.css";
import {
  getVaccinePresets,
  getVaccinePreset,
  computeNextDue,
  todayISO,
} from "./vaccinePresets";

const OTHER_ID = "__other__";

/**
 * Sección "Vacuna aplicada" — primer protocolo clínico (ver
 * features/consultation/protocols). Presentacional puro: el estado vive en el
 * container (ConsultationForm) como slice `protocolDraft.vaccine`, que autoguarda
 * en `MedicalRecord.consultation_draft`. NO crea el VaccineRecord: eso ocurre en
 * el backend al finalizar la consulta (apply_consultation_draft_on_close).
 *
 * `value` = { presetId, vaccine_name, application_date, scheduleBooster,
 *             next_due_date, notes, _boosterMonths, _boosterEdited }
 */
const VaccineSection = forwardRef(function VaccineSection(
  { value, onChange, history = [], species, disabled, fmtDate, products = [] },
  ref
) {
  const v = value || {};
  const isOther = v.presetId === OTHER_ID;
  const [lots, setLots] = useState([]);

  // ── Producto de inventario (opcional) + lote (A2) ──
  const handleProductSearch = useCallback(
    async (q) => {
      const lower = (q || "").trim().toLowerCase();
      return (products || [])
        .filter((p) => p.is_active !== false)
        .filter((p) => (!lower ? true : (p.name || "").toLowerCase().includes(lower)))
        .slice(0, 10)
        .map((p) => ({ id: p.id, label: p.name }));
    },
    [products]
  );

  const handleSelectProduct = useCallback(
    (item) => {
      const p = item ? (products || []).find((x) => x.id === item.id) : null;
      onChange({
        product_id: p?.id ?? null,
        product_public_id: p?.public_id ?? null,
        product_name: p?.name ?? "",
        product_tracks_lots: !!p?.tracks_lots,
        lot_id: null,
        lot_label: null,
      });
    },
    [onChange, products]
  );

  const productValue = v.product_id ? { id: v.product_id, label: v.product_name } : null;

  // Carga los lotes elegibles cuando el producto usa lotes; auto-selecciona FEFO.
  useEffect(() => {
    if (!v.product_public_id || !v.product_tracks_lots) {
      setLots([]);
      return undefined;
    }
    let active = true;
    (async () => {
      try {
        const data = await getProductLots(v.product_public_id, { with_stock: "true" });
        const list = (Array.isArray(data) ? data : data?.results || [])
          .filter((l) => l.effective_status === "active");
        if (!active) return;
        setLots(list);
        if (!v.lot_id && list[0]) {
          onChange({
            lot_id: list[0].id,
            lot_label: `${list[0].lot_number}${list[0].expiry_date ? ` · vence ${list[0].expiry_date}` : ""}`,
          });
        }
      } catch {
        if (active) setLots([]);
      }
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [v.product_public_id, v.product_tracks_lots]);

  const handleSearch = useCallback(
    async (q) => {
      const lower = (q || "").trim().toLowerCase();
      const base = getVaccinePresets({ species }).filter((p) =>
        !lower ? true : p.name.toLowerCase().includes(lower)
      );
      const opts = base.map((p) => ({ id: p.id, label: p.name }));
      opts.push({ id: OTHER_ID, label: "Otra vacuna…" });
      return opts;
    },
    [species]
  );

  const selectValue = v.presetId
    ? { id: v.presetId, label: isOther ? "Otra vacuna…" : v.vaccine_name }
    : null;

  const handleSelectVaccine = useCallback(
    (item) => {
      if (!item) {
        onChange({
          presetId: null, vaccine_name: "", _boosterMonths: null,
          scheduleBooster: false, next_due_date: null, _boosterEdited: false,
        });
        return;
      }
      if (item.id === OTHER_ID) {
        onChange({
          presetId: OTHER_ID, vaccine_name: "", _boosterMonths: null,
          scheduleBooster: false, next_due_date: null, _boosterEdited: false,
        });
        return;
      }
      const preset = getVaccinePreset(item.id);
      if (!preset) return;
      const appDate = v.application_date || todayISO();
      onChange({
        presetId: preset.id,
        vaccine_name: preset.name,
        _boosterMonths: preset.boosterMonths,
        scheduleBooster: preset.boosterMonths != null,
        next_due_date: computeNextDue(appDate, preset.boosterMonths),
        _boosterEdited: false,
      });
    },
    [onChange, v.application_date]
  );

  const handleApplicationDate = useCallback(
    (application_date) => {
      const patch = { application_date };
      // Recalcula el refuerzo sugerido si el usuario no lo editó a mano.
      if (v.scheduleBooster && !v._boosterEdited && v._boosterMonths != null) {
        patch.next_due_date = computeNextDue(application_date, v._boosterMonths);
      }
      onChange(patch);
    },
    [onChange, v.scheduleBooster, v._boosterEdited, v._boosterMonths]
  );

  const handleToggleBooster = useCallback(() => {
    const on = !v.scheduleBooster;
    onChange({
      scheduleBooster: on,
      next_due_date: on
        ? (v._boosterEdited ? v.next_due_date : computeNextDue(v.application_date, v._boosterMonths))
        : null,
    });
  }, [onChange, v.scheduleBooster, v._boosterEdited, v.next_due_date, v.application_date, v._boosterMonths]);

  const handleNextDue = useCallback(
    (next_due_date) => onChange({ next_due_date, _boosterEdited: true }),
    [onChange]
  );

  // Ayuda contextual / hint del refuerzo.
  const hasProtocol = v._boosterMonths != null && !isOther;
  const boosterHint = v.scheduleBooster
    ? (v._boosterEdited ? "Personalizado" : (hasProtocol ? "Calculado según protocolo" : null))
    : null;
  const boosterHelp =
    v.scheduleBooster && !v._boosterEdited && hasProtocol
      ? `Refuerzo recomendado en ${v._boosterMonths} meses. Puedes modificar esta fecha si el protocolo clínico del paciente lo requiere.`
      : null;

  // Ayuda histórica (no bloqueante): última aplicación de esta misma vacuna.
  const name = (v.vaccine_name || "").trim().toLowerCase();
  const prior =
    name && history.find((h) => (h.vaccine_name || "").trim().toLowerCase() === name);

  return (
    <motion.section
      ref={ref}
      className={styles.section}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.04 }}
    >
      <div className={styles.secHead}>
        <div className={styles.secIcon}>
          <Icon.Syringe s={17} />
        </div>
        <div>
          <h2 className={styles.secTitle}>Vacuna aplicada</h2>
          <p className={styles.secSub}>Se registra en el historial de vacunación al finalizar la consulta.</p>
        </div>
      </div>

      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Vacuna <span className={styles.req}>*</span></label>
          <SearchSelect
            placeholder="Buscar vacuna…"
            value={selectValue}
            onChange={handleSelectVaccine}
            onSearch={handleSearch}
            disabled={disabled}
            maxSuggestions={10}
          />
          {isOther && (
            <input
              className={styles.control}
              style={{ marginTop: 8 }}
              placeholder="Nombre de la vacuna"
              value={v.vaccine_name || ""}
              disabled={disabled}
              onChange={(e) => onChange({ vaccine_name: e.target.value })}
            />
          )}
          {prior && (
            <div className={styles.vaccineHistory}>
              <Icon.Clock s={13} />
              <span>
                Última {prior.vaccine_name}: {fmtDate ? fmtDate(prior.application_date) : prior.application_date}
                {prior.applied_by_name ? ` · ${prior.applied_by_name}` : ""}
              </span>
            </div>
          )}
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel}>Fecha de aplicación <span className={styles.req}>*</span></label>
          <DateField
            value={v.application_date || ""}
            onChange={handleApplicationDate}
            max={todayISO()}
            disabled={disabled}
            inputClassName={styles.control}
          />
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Producto de inventario (opcional)</label>
        <SearchSelect
          placeholder="Ligar al vial en inventario…"
          value={productValue}
          onChange={handleSelectProduct}
          onSearch={handleProductSearch}
          disabled={disabled}
          maxSuggestions={10}
        />
        <p className={styles.note}>
          Ligarla descuenta 1 dosis del inventario y guarda lote y caducidad en el registro.
        </p>
        {v.product_id && v.product_tracks_lots && (
          <div style={{ marginTop: 10 }}>
            <label className={styles.fieldLabel}>
              Lote (FEFO) <span className={styles.req}>*</span>
            </label>
            <select
              className={styles.control}
              value={v.lot_id ?? ""}
              disabled={disabled}
              onChange={(e) => {
                const l = lots.find((x) => String(x.id) === e.target.value) || null;
                onChange({
                  lot_id: l?.id ?? null,
                  lot_label: l ? `${l.lot_number}${l.expiry_date ? ` · vence ${l.expiry_date}` : ""}` : null,
                });
              }}
            >
              {lots.length === 0 && <option value="">Sin lotes disponibles</option>}
              {lots.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.lot_number}{l.expiry_date ? ` · vence ${l.expiry_date}` : ""} · {Math.round(Number(l.quantity_on_hand))} disp.
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className={styles.field}>
        <div className={styles.switchRow}>
          <button
            type="button"
            role="switch"
            aria-checked={!!v.scheduleBooster}
            className={`${styles.switch} ${v.scheduleBooster ? styles.switchOn : ""}`}
            disabled={disabled}
            onClick={handleToggleBooster}
          >
            <span className={styles.switchThumb} />
          </button>
          <span className={styles.switchLabel}>Programar próximo refuerzo</span>
        </div>

        {v.scheduleBooster && (
          <div style={{ marginTop: 12 }}>
            <label className={styles.fieldLabel}>
              Próximo refuerzo
              {boosterHint && <span className={styles.protocolHint}>{boosterHint}</span>}
            </label>
            <DateField
              value={v.next_due_date || ""}
              onChange={handleNextDue}
              min={v.application_date || undefined}
              disabled={disabled}
              clearable
              inputClassName={styles.control}
            />
            {boosterHelp && <p className={styles.note}>{boosterHelp}</p>}
          </div>
        )}
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Notas</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Reacciones observadas, observaciones clínicas…"
          value={v.notes || ""}
          disabled={disabled}
          onChange={(e) => onChange({ notes: e.target.value })}
        />
      </div>
    </motion.section>
  );
});

export default VaccineSection;
