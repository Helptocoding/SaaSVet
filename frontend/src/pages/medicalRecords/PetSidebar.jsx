import { useEffect, useRef, useState } from "react";
import { Icon } from "../../components/icons";
import { searchPets } from "../../api/lookups";
import styles from "./medicalRecords.module.css";

const SPECIES_DOG = /perro|can[ei]|dog/i;
const SPECIES_CAT = /gato|fel[iy]|cat/i;

const getSpeciesBg = (species) => {
    if (SPECIES_DOG.test(species)) return "var(--c-primary-light)";
    if (SPECIES_CAT.test(species)) return "var(--c-purple-bg)";
    return "var(--c-subtle)";
};

const SpeciesIcon = ({ species, size = 15 }) =>
    SPECIES_DOG.test(species) ? <Icon.Dog s={size} /> :
    SPECIES_CAT.test(species) ? <Icon.Cat s={size} /> :
    <Icon.Paw s={size} />;

// Línea secundaria que diferencia homónimos: dueño · teléfono · expediente.
const petSubline = (pet) =>
    [pet.owner?.name, pet.owner?.phone, pet.legacy_id && `Exp #${pet.legacy_id}`]
        .filter(Boolean).join(" · ") ||
    [pet.species, pet.breed].filter(Boolean).join(" · ") || "—";

const PAGE_SIZE = 12;

/**
 * PetSidebar — buscador/selector de mascota del historial clínico.
 *
 * Server-side (ADR p44c): NO carga las miles de mascotas de la clínica a memoria.
 * Busca contra el backend (debounce + paginación "Ver más") y muestra contexto
 * suficiente para diferenciar homónimos (dueño · teléfono · expediente). El padre
 * ya no pasa la lista completa ni los conteos por mascota (que requerían traer
 * todos los medical records).
 */
const PetSidebar = ({
    selectedPet,
    selectedPetObj,
    onSelectPet,
    collapsed = false,
    onToggleCollapse,
}) => {
    const [query, setQuery] = useState("");
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);

    const pageRef = useRef(1);
    const reqRef = useRef(0);
    const debRef = useRef(null);

    const fetchFirst = (q) => {
        if (debRef.current) clearTimeout(debRef.current);
        setLoading(true);
        debRef.current = setTimeout(() => {
            const rid = ++reqRef.current;
            pageRef.current = 1;
            searchPets({ query: q, page: 1, pageSize: PAGE_SIZE })
                .then(({ items: rows, hasMore: more }) => {
                    if (reqRef.current !== rid) return;
                    setItems(rows);
                    setHasMore(Boolean(more));
                    setLoading(false);
                })
                .catch(() => {
                    if (reqRef.current !== rid) return;
                    setItems([]);
                    setHasMore(false);
                    setLoading(false);
                });
        }, 250);
    };

    // Carga inicial: primeras mascotas (sin query) para poder elegir sin escribir.
    useEffect(() => {
        fetchFirst("");
        return () => { if (debRef.current) clearTimeout(debRef.current); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const onQueryChange = (v) => {
        setQuery(v);
        fetchFirst(v.trim());
    };

    const loadMore = () => {
        if (loadingMore || loading || !hasMore) return;
        const rid = reqRef.current;
        const next = pageRef.current + 1;
        setLoadingMore(true);
        searchPets({ query: query.trim(), page: next, pageSize: PAGE_SIZE })
            .then(({ items: rows, hasMore: more }) => {
                if (reqRef.current !== rid) return;
                pageRef.current = next;
                setItems(prev => [...prev, ...rows]);
                setHasMore(Boolean(more));
                setLoadingMore(false);
            })
            .catch(() => { if (reqRef.current === rid) setLoadingMore(false); });
    };

    if (collapsed) {
        return (
            <aside className={`${styles.petSidebar} ${styles.petSidebarCollapsed}`}>
                <button
                    className={styles.sidebarToggleBtn}
                    onClick={onToggleCollapse}
                    title="Mostrar buscador de mascotas"
                >
                    <Icon.ChevronRight s={16} />
                </button>

                {selectedPetObj && (
                    <div className={styles.sidebarRailPet} title={selectedPetObj.name}>
                        <div
                            className={styles.sidebarRailAvatar}
                            style={{ background: getSpeciesBg((selectedPetObj.species || "").toLowerCase()) }}
                        >
                            <SpeciesIcon species={selectedPetObj.species || ""} size={14} />
                        </div>
                        <span className={styles.sidebarRailName}>
                            {selectedPetObj.name.slice(0, 2).toUpperCase()}
                        </span>
                    </div>
                )}
            </aside>
        );
    }

    return (
        <aside className={styles.petSidebar}>
            <div className={styles.sidebarHeaderRow}>
                <span className={styles.sidebarHeader}>Mascotas</span>
                <button
                    className={styles.sidebarCollapseBtn}
                    onClick={onToggleCollapse}
                    title="Ocultar buscador"
                >
                    <Icon.ChevronLeft s={15} />
                </button>
            </div>

            <div className={styles.sidebarSearchWrap}>
                <span className={styles.sidebarSearchIcon}><Icon.Search /></span>
                <input
                    className={styles.sidebarSearchInput}
                    placeholder="Nombre, dueño, teléfono, expediente…"
                    value={query}
                    onChange={e => onQueryChange(e.target.value)}
                />
            </div>

            <div className={styles.petList}>
                {loading ? (
                    <p className={styles.sidebarEmpty}>Cargando…</p>
                ) : items.length === 0 ? (
                    <p className={styles.sidebarEmpty}>Sin resultados</p>
                ) : (
                    <>
                        {items.map(pet => {
                            const sp = (pet.species || "").toLowerCase();
                            const isActive = String(pet.public_id) === String(selectedPet);
                            return (
                                <button
                                    key={pet.public_id}
                                    className={`${styles.petListItem}${isActive ? ` ${styles.petListItemActive}` : ""}`}
                                    onClick={() => onSelectPet(pet)}
                                >
                                    <div className={styles.petListIcon} style={{ background: getSpeciesBg(sp) }}>
                                        <SpeciesIcon species={sp} size={15} />
                                    </div>
                                    <div className={styles.petListInfo}>
                                        <div className={styles.petListName}>{pet.name}</div>
                                        <div className={styles.petListSub}>{petSubline(pet)}</div>
                                    </div>
                                </button>
                            );
                        })}
                        {hasMore && (
                            <button className={styles.sidebarMore} onClick={loadMore} disabled={loadingMore}>
                                {loadingMore ? "Cargando…" : "Ver más resultados"}
                            </button>
                        )}
                    </>
                )}
            </div>
        </aside>
    );
};

export default PetSidebar;
