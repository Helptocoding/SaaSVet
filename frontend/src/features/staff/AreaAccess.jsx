// «Acceso por área» de la tabla de Equipo (ADR p69): una pastilla por área con
// algún permiso; cada una abre el detalle de grupos y acciones que SÍ tiene.
import { Icon } from "../../components/icons";
import Popover from "../../components/Popover";
import { fullName } from "./staffForm";
import { groupsSummary, hasAllAreas, isCustomized, memberAreas } from "./teamView";
import styles from "./AreaAccess.module.css";

function AreaDetail({ area }) {
    return (
        <>
            <p className={styles.title}>{area.label}</p>
            <ul className={styles.groups}>
                {area.groups.map((group) => (
                    <li key={group.key}>
                        <span className={styles.groupName}>{group.label}</span>
                        <span className={styles.actions}>{group.actions.join(" · ")}</span>
                    </li>
                ))}
            </ul>
        </>
    );
}

export default function AreaAccess({ member, catalog }) {
    if (!catalog) return <span className={styles.muted}>—</span>;
    const areas = memberAreas(member, catalog);
    if (areas.length === 0) return <span className={styles.muted}>Sin acceso</span>;
    const name = fullName(member);
    // Una sola línea: quien tiene todo no necesita tres pastillas para decirlo
    // (el detalle está en su ficha); «ajustado» es un ícono con su texto accesible.
    const customized = isCustomized(member) && (
        <span className={styles.custom} title="Permisos ajustados para esta persona">
            <Icon.Sliders s={14} />
            <span className="sr-only">Permisos ajustados para esta persona</span>
        </span>
    );
    if (hasAllAreas(member, catalog)) {
        return <span className={styles.chips}><span className={styles.all}>Todas las áreas</span>{customized}</span>;
    }
    return (
        <div className={styles.chips}>
            {areas.map((area) => (
                <Popover
                    key={area.key}
                    label={`${area.label}: permisos de ${name}`}
                    ariaLabel={`${area.label}: ${groupsSummary(area.groups)}. Ver detalle`}
                    triggerClassName={styles.chip}
                    trigger={area.label}
                >
                    <AreaDetail area={area} />
                </Popover>
            ))}
            {customized}
        </div>
    );
}
