import { useEffect, useState } from "react";
import Skeleton from "react-loading-skeleton";
import { getConfigHistory } from "../../api/organizations";
import { useAuth } from "../../auth/authContext";
import EmptyState from "../../components/EmptyState";
import Pagination from "../../components/Pagination";
import { Icon } from "../../components/icons";
import { describeConfigEvent } from "../../features/config/history";
import { apiError } from "../../utils/apiError";
import { formatDateTime, orgTz } from "../../utils/datetime";
import SettingsPanel from "./SettingsPanel";
import styles from "./config.module.css";

const PAGE_SIZE = 25;

/**
 * Historial de cambios de la configuración (ADR p70 D9): quién cambió qué y
 * cuándo, del más reciente al más antiguo. Solo lectura; el backend lo
 * restringe a quien puede editar la clínica (`organization.update`).
 */
const HistorySection = () => {
    const { user } = useAuth();
    const tz = orgTz(user);
    const [page, setPage] = useState(1);
    // `attempt` cambia al reintentar: la clave identifica la carga vigente y el
    // estado solo cambia en los callbacks de la petición, nunca en el efecto.
    const [attempt, setAttempt] = useState(0);
    const requestKey = `${page}:${attempt}`;
    const [data, setData] = useState(null);
    const [outcome, setOutcome] = useState({ key: null, error: null });

    useEffect(() => {
        let current = true;
        getConfigHistory({ page })
            .then((response) => {
                if (!current) return;
                setData(response);
                setOutcome({ key: requestKey, error: null });
            })
            .catch((err) => {
                if (!current) return;
                setOutcome({ key: requestKey, error: apiError(err, "No se pudo cargar el historial.") });
            });
        return () => { current = false; };
    }, [page, requestKey]);

    const fetching = outcome.key !== requestKey;
    const error = fetching ? null : outcome.error;
    const retry = () => setAttempt((n) => n + 1);

    const events = data?.results || [];

    let body;
    if (error) {
        body = (
            <EmptyState
                compact
                icon={Icon.AlertCircle}
                title="No se pudo cargar el historial"
                body={error}
                actions={[{ label: "Reintentar", onClick: retry, variant: "secondary" }]}
            />
        );
    } else if (!data || (fetching && outcome.error)) {
        body = (
            <div role="status" aria-label="Cargando historial" className={styles.historyList}>
                {[0, 1, 2].map((i) => (
                    <div key={i} className={styles.historyItem} aria-hidden="true">
                        <Skeleton width="45%" height={14} />
                        <Skeleton width="30%" height={11} />
                    </div>
                ))}
            </div>
        );
    } else if (events.length === 0) {
        body = (
            <EmptyState
                compact
                icon={Icon.Clock}
                title="Todavía no hay cambios registrados"
                body="Cada vez que alguien guarde un cambio en la configuración aparecerá aquí, con quién lo hizo y cuándo."
            />
        );
    } else {
        body = (
            <>
                <ul className={styles.historyList} aria-label="Cambios registrados" aria-busy={fetching}>
                    {events.map((event, index) => {
                        const { title, details } = describeConfigEvent(event);
                        const who = event.actor_name || "Alguien que ya no está en el equipo";
                        return (
                            <li key={`${event.occurred_at}-${index}`} className={styles.historyItem}>
                                <p className={styles.historyTitle}>{title}</p>
                                <p className={styles.historyMeta}>
                                    {who} · {formatDateTime(event.occurred_at, tz, "es-MX")}
                                </p>
                                {details.length > 0 && (
                                    <ul className={styles.historyDetails}>
                                        {details.map((detail) => (
                                            <li key={detail} className={styles.historyDetail}>{detail}</li>
                                        ))}
                                    </ul>
                                )}
                            </li>
                        );
                    })}
                </ul>
                {data.count > PAGE_SIZE && (
                    <div className={styles.historyFooter}>
                        <Pagination page={page} count={data.count} pageSize={PAGE_SIZE}
                            onPage={setPage} fetching={fetching} />
                    </div>
                )}
            </>
        );
    }

    return (
        <SettingsPanel
            title="Historial de cambios"
            description="Quién cambió los datos de la clínica, el horario, las reglas o los servicios, y cuándo."
            padded={false}
        >
            {body}
        </SettingsPanel>
    );
};

export default HistorySection;
