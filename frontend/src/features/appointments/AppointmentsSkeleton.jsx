import Skeleton from "react-loading-skeleton";
import s from "./AppointmentsSkeleton.module.css";

const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

// Carga inicial de Citas: encabezado real, filtros y la vista de mes (vista por
// defecto) como esqueleto. Vive aparte porque los estilos de la agenda se
// inyectan dentro del render principal y aquí todavía no existen.
const AppointmentsSkeleton = () => (
    <div>
        <div className="page-header">
            <div>
                <h1 className="page-title">Citas</h1>
                <Skeleton width={180} height={12} />
            </div>
        </div>
        <div role="status" aria-label="Cargando agenda">
            <div className={s.controls} aria-hidden="true">
                <Skeleton width={250} height={35} borderRadius="var(--r-md)" />
                <Skeleton width={170} height={35} borderRadius="var(--r-md)" />
                <Skeleton width={150} height={35} borderRadius="var(--r-md)" />
                <Skeleton width={150} height={35} borderRadius="var(--r-md)" />
            </div>
            <div className={s.shell} aria-hidden="true">
                <div className={s.toolbar}>
                    <div>
                        <Skeleton width={150} height={18} />
                        <Skeleton width={110} height={28} borderRadius="var(--r-md)" />
                    </div>
                    <Skeleton width={190} height={32} borderRadius="var(--r-md)" />
                </div>
                <div className={s.weekdays}>
                    {WEEKDAYS.map(day => <span key={day}>{day}</span>)}
                </div>
                <div className={s.month}>
                    {Array.from({ length: 35 }, (_, i) => (
                        <div key={i} className={s.day}>
                            <Skeleton width={16} height={10} />
                            {i % 4 === 1 && <Skeleton height={14} borderRadius="var(--r-sm)" />}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    </div>
);

export default AppointmentsSkeleton;
