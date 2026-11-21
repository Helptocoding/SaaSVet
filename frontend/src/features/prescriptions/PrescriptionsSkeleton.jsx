import Skeleton from "react-loading-skeleton";
import TableSkeleton from "../../components/TableSkeleton";
import s from "./PrescriptionsSkeleton.module.css";

const COLUMNS = [
    { label: "Fecha", width: 90 },
    { label: "Mascota", width: 120 },
    { label: "Veterinario", width: 120 },
    { label: "Medicamentos", width: 200 },
    { label: "", width: 70 },
];

// Carga inicial de Recetas: encabezado real; aviso, filtros y la vista elegida
// (tabla o tarjetas) como esqueleto.
const PrescriptionsSkeleton = ({ view = "table" }) => (
    <div>
        <div className="page-header">
            <div>
                <h1 className="page-title">Recetas médicas</h1>
                <Skeleton width={150} height={12} />
            </div>
        </div>
        <div role="status" aria-label="Cargando recetas">
            <Skeleton height={40} borderRadius="var(--r-md)" containerClassName={s.notice} />
            <div className={s.filters} aria-hidden="true">
                <Skeleton width={280} height={36} borderRadius="var(--r-lg)" />
                <Skeleton width={170} height={36} borderRadius="var(--r-lg)" />
                <Skeleton width={230} height={36} borderRadius="var(--r-md)" />
                <Skeleton width={120} height={36} borderRadius="var(--r-lg)" />
                <Skeleton width={74} height={36} borderRadius="var(--r-lg)" containerClassName={s.pushRight} />
            </div>
            {view === "cards" ? (
                <div className={s.cards} aria-hidden="true">
                    {[0, 1, 2, 3, 4, 5].map(i => (
                        <div key={i} className={`card ${s.card}`}>
                            <Skeleton width="55%" height={15} />
                            <Skeleton width="40%" height={11} />
                            <Skeleton count={2} height={12} className={s.line} />
                            <Skeleton height={30} borderRadius="var(--r-md)" />
                        </div>
                    ))}
                </div>
            ) : (
                <TableSkeleton rows={7} columns={COLUMNS} />
            )}
        </div>
    </div>
);

export default PrescriptionsSkeleton;
