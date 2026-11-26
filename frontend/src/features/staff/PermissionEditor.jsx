// Permisos de un integrante por área (ADR p69): acordeón con una casilla por
// acción. Lo marcado parte de su rol; lo que se aparta se señala («Extra al rol»,
// «Quitado del rol») y «Restaurar valores del rol» deshace todos los ajustes.
// Presentacional: el borrador y sus reglas viven en `permissionDraft`.
import { useId, useState } from "react";
import { Icon } from "../../components/icons";
import { roleLabel } from "./roles";
import {
    codeBadge, customCounts, effectiveCodes, hasOverrides, lockReason,
} from "./permissionDraft";
import styles from "./PermissionEditor.module.css";

const BADGE_LABELS = { extra: "Extra al rol", removed: "Quitado del rol" };

function AreaPanel({ area, catalog, draft, onToggle, readOnly, isSelf, initial, open, onOpenChange }) {
    const panelId = useId();
    const effective = effectiveCodes(catalog, draft);
    const codes = area.groups.flatMap((group) => group.permissions.map((p) => p.code));
    const held = codes.filter((code) => effective.has(code)).length;
    const changed = codes.filter((code) => codeBadge(catalog, draft, code)).length;

    return (
        <section className={styles.area}>
            <h4 className={styles.areaHeading}>
                <button
                    type="button"
                    className={styles.areaToggle}
                    aria-expanded={open}
                    aria-controls={panelId}
                    onClick={() => onOpenChange(!open)}
                >
                    <span className={styles.areaName}>{area.label}</span>
                    <span className={styles.areaCount}>{held} de {codes.length}</span>
                    {changed > 0 && <span className="badge badge-info">{changed} ajustado{changed === 1 ? "" : "s"}</span>}
                    <span className={styles.chevron} aria-hidden="true">
                        {open ? <Icon.ChevronUp s={16} /> : <Icon.ChevronDown s={16} />}
                    </span>
                </button>
            </h4>
            {open && (
                <div id={panelId} className={styles.areaBody}>
                    {area.groups.map((group) => (
                        <fieldset key={group.key} className={styles.group}>
                            <legend className={styles.groupName}>{group.label}</legend>
                            {group.permissions.map((permission) => {
                                const reason = lockReason(catalog, draft, permission.code, { isSelf, initial });
                                const badge = codeBadge(catalog, draft, permission.code);
                                const inputId = `${panelId}-${permission.code}`;
                                const hintId = reason ? `${inputId}-hint` : undefined;
                                return (
                                    <div key={permission.code} className={styles.option}>
                                        <input
                                            id={inputId}
                                            type="checkbox"
                                            checked={effective.has(permission.code)}
                                            disabled={readOnly || Boolean(reason)}
                                            aria-describedby={hintId}
                                            onChange={(event) => onToggle(permission.code, event.target.checked)}
                                        />
                                        <label htmlFor={inputId} className={styles.optionLabel}>
                                            {permission.label}
                                        </label>
                                        {badge && (
                                            <span className={`badge ${badge === "extra" ? "badge-purple" : "badge-default"} ${styles.badge}`}>
                                                {BADGE_LABELS[badge]}
                                            </span>
                                        )}
                                        {reason && <span id={hintId} className={styles.hint}>{reason}</span>}
                                    </div>
                                );
                            })}
                        </fieldset>
                    ))}
                </div>
            )}
        </section>
    );
}

const READ_ONLY_NOTE = "Solo un administrador puede conceder o quitar permisos.";

export default function PermissionEditor({
    catalog, draft, onToggle, onRestore, readOnly = false, readOnlyNote = READ_ONLY_NOTE, isSelf = false, initial,
}) {
    const [openAreas, setOpenAreas] = useState(() => new Set());
    if (!catalog) return null;
    const { extra, removed } = customCounts(catalog, draft);
    const summary = extra + removed === 0
        ? `Los permisos de ${roleLabel(draft.role)}, sin ajustes.`
        : `Permisos de ${roleLabel(draft.role)} con ${[
            extra > 0 ? `${extra} extra` : null,
            removed > 0 ? `${removed} quitado${removed === 1 ? "" : "s"}` : null,
        ].filter(Boolean).join(" y ")}.`;

    const setOpen = (key, open) => setOpenAreas((current) => {
        const next = new Set(current);
        if (open) next.add(key);
        else next.delete(key);
        return next;
    });

    return (
        <div className={styles.editor}>
            <div className={styles.toolbar}>
                <div>
                    <p className={styles.summary} aria-live="polite">{summary}</p>
                    {readOnly && readOnlyNote && <p className={styles.readOnly}>{readOnlyNote}</p>}
                </div>
                {!readOnly && (
                    <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={onRestore}
                        disabled={!hasOverrides(draft)}
                    >
                        <Icon.Refresh s={14} /> Restaurar valores del rol
                    </button>
                )}
            </div>
            {catalog.areas.map((area) => (
                <AreaPanel
                    key={area.key}
                    area={area}
                    catalog={catalog}
                    draft={draft}
                    onToggle={onToggle}
                    readOnly={readOnly}
                    isSelf={isSelf}
                    initial={initial}
                    open={openAreas.has(area.key)}
                    onOpenChange={(open) => setOpen(area.key, open)}
                />
            ))}
        </div>
    );
}
