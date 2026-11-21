import Skeleton from "react-loading-skeleton";
import TableSkeleton from "../../components/TableSkeleton";
import { StatSectionSkeleton } from "../../components/StatTiles";
import s from "./PetsSkeleton.module.css";

// Carga inicial de Mascotas: encabezado real; indicadores, filtros y la vista
// elegida (tarjetas o tabla) como esqueleto.
const PetsSkeleton = ({ view = "cards" }) => (
    <div>
        <div className="page-header">
            <div>
                <h1 className="page-title">Mascotas</h1>
                <Skeleton width={110} height={12} />
            </div>
            <Skeleton width={140} height={36} borderRadius="var(--r-lg)" />
        </div>
        <div role="status" aria-label="Cargando mascotas">
            <StatSectionSkeleton count={4} />
            <div className={s.filters} aria-hidden="true">
                <Skeleton width={260} height={36} borderRadius="var(--r-lg)" />
                <Skeleton width={130} height={36} borderRadius="var(--r-lg)" />
                <Skeleton width={130} height={36} borderRadius="var(--r-lg)" />
                <Skeleton width={74} height={36} borderRadius="var(--r-lg)" containerClassName={s.pushRight} />
            </div>
            {view === "table" ? (
                <TableSkeleton rows={7} columns={[
                    {
                        label: "Mascota",
                        cell: (row) => (
                            <div className={s.petCell}>
                                <Skeleton circle width={32} height={32} />
                                <Skeleton width={110 + (row % 3) * 20} height={13} />
                            </div>
                        ),
                    },
                    { label: "Especie / Raza", width: 120 },
                    { label: "Cliente", width: 110 },
                    { label: "Edad · Sexo", width: 90 },
                    { label: "", width: 60 },
                ]} />
            ) : (
                <div className={s.cards} aria-hidden="true">
                    {[0, 1, 2, 3, 4, 5].map(i => (
                        <div key={i} className={`card ${s.card}`}>
                            <div className={s.cardHead}>
                                <Skeleton circle width={44} height={44} />
                                <div className={s.cardTitle}>
                                    <Skeleton width="70%" height={15} />
                                    <Skeleton width="50%" height={12} />
                                </div>
                            </div>
                            <div className={s.cardBody}>
                                <Skeleton width="60%" height={10} />
                                <Skeleton width="60%" height={10} />
                                <Skeleton width="80%" height={14} />
                                <Skeleton width="80%" height={14} />
                            </div>
                            <Skeleton height={30} borderRadius="var(--r-md)" />
                        </div>
                    ))}
                </div>
            )}
        </div>
    </div>
);

// Detalle de una mascota en el panel lateral mientras se cargan sus datos.
export const PetPanelSkeleton = () => (
    <div role="status" aria-label="Cargando datos de la mascota">
        {[0, 1, 2].map(section => (
            <section key={section} className={s.panelSection} aria-hidden="true">
                <Skeleton width={80} height={10} />
                {section === 0 ? (
                    <div className={s.cardHead}>
                        <Skeleton circle width={36} height={36} />
                        <div className={s.cardTitle}>
                            <Skeleton width={150} height={13} />
                            <Skeleton width={110} height={11} />
                        </div>
                    </div>
                ) : (
                    <Skeleton count={3} height={12} className={s.panelLine} />
                )}
            </section>
        ))}
    </div>
);

// Ficha de una mascota: el botón de volver es real; nombre, pestañas y las dos
// tarjetas de información (mascota y cliente) como esqueleto.
export const PetDetailSkeleton = ({ backButton }) => (
    <div>
        {backButton}
        <div role="status" aria-label="Cargando ficha de la mascota">
            <div className="page-header" aria-hidden="true">
                <div>
                    <Skeleton width={180} height={24} />
                    <Skeleton width={220} height={12} />
                </div>
            </div>
            <div className={`tabs ${s.tabs}`} aria-hidden="true">
                <Skeleton width={90} height={14} />
                <Skeleton width={90} height={14} />
                <Skeleton width={70} height={14} />
            </div>
            <div className={s.infoGrid} aria-hidden="true">
                {[7, 2].map((rows, card) => (
                    <div key={card} className="card">
                        <Skeleton width={130} height={13} className={s.infoTitle} />
                        {Array.from({ length: rows }, (_, i) => (
                            <div key={i} className="info-row">
                                <Skeleton width={80} height={11} />
                                <Skeleton width={110} height={12} />
                            </div>
                        ))}
                    </div>
                ))}
            </div>
        </div>
    </div>
);

export default PetsSkeleton;
