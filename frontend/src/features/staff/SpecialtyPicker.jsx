// Selector de especialidades (ADR p68): casillas del catálogo cerrado, varias a
// la vez. El valor es una lista de códigos en el orden del catálogo.
import { SPECIALTIES, orderSpecialties } from "./specialties";
import styles from "./SpecialtyPicker.module.css";

export default function SpecialtyPicker({ idPrefix, value, onChange, disabled = false, error }) {
    const selected = new Set(value || []);
    const toggle = (code, checked) => {
        const next = new Set(selected);
        if (checked) next.add(code);
        else next.delete(code);
        onChange(orderSpecialties([...next]));
    };
    return (
        <fieldset className={styles.fieldset} aria-describedby={error ? `${idPrefix}-error` : undefined}>
            <legend className="form-label">ESPECIALIDADES</legend>
            <div className={styles.grid}>
                {SPECIALTIES.map(([code, label]) => (
                    <label key={code} className={styles.option} htmlFor={`${idPrefix}-${code}`}>
                        <input
                            id={`${idPrefix}-${code}`}
                            type="checkbox"
                            checked={selected.has(code)}
                            disabled={disabled}
                            onChange={(event) => toggle(code, event.target.checked)}
                        />
                        <span>{label}</span>
                    </label>
                ))}
            </div>
            {error && <p id={`${idPrefix}-error`} className={styles.error}>{error}</p>}
        </fieldset>
    );
}
