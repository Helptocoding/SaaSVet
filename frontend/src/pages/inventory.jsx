import { useEffect, useMemo, useRef, useState } from "react";
import { useConfirm } from "../components/useConfirm";
import { apiError } from "../utils/apiError";
import handleFormError from "../utils/handleFormError";
import { toList } from "../utils/toList";
import {
    getProducts, createProduct, updateProduct, deleteProduct,
    adjustStock, getUnitChoices, createPresentation, updatePresentation,
} from "../api/inventory";
import { useAuth } from "../auth/authContext";
import { Icon } from "../components/icons";
import { toast } from "sonner";
import StockEntryModal from "../components/StockEntryModal";
import s from "./inventory.module.css";
import ProductCreationTour from "../features/inventory/tutorial/ProductCreationTour";
import { useProductTour } from "../features/inventory/tutorial/useProductTour";
import MultiPresentationAnimation from "../features/inventory/tutorial/MultiPresentationAnimation";

// ── Constants ─────────────────────────────────────────────
const CATEGORY_LABELS = {
    medication: "Medicamento", food: "Alimento",
    accessory: "Accesorio", other: "Otro",
};

const CATEGORY_UNITS = {
    medication: ["tablet", "capsule", "ml", "vial", "ampoule", "bottle", "tube", "unit"],
    food:       ["kg", "g", "bag", "unit"],
    accessory:  ["piece", "unit"],
    other:      null,
};

const EMPTY_WIZARD_PRODUCT = {
    name: "", internal_code: "", description: "",
    category: "other", requires_prescription: false,
    min_stock: "",
};

// Friendly counting units for Block 2. key = select value; backendUnit = API enum.
const STOCK_COUNTING_UNITS = [
    { key: "piece",    label: "Pieza",      backendUnit: "piece" },
    { key: "caja",     label: "Caja",       backendUnit: "unit"  },
    { key: "paquete",  label: "Paquete",    backendUnit: "unit"  },
    { key: "bag",      label: "Bolsa",      backendUnit: "bag"   },
    { key: "bottle",   label: "Frasco",     backendUnit: "bottle"},
    { key: "blister",  label: "Blíster",    backendUnit: "unit"  },
    { key: "ampoule",  label: "Ampolleta",  backendUnit: "ampoule"},
    { key: "vial",     label: "Vial",       backendUnit: "vial"  },
    { key: "tablet",   label: "Tableta",    backendUnit: "tablet"},
    { key: "capsule",  label: "Cápsula",    backendUnit: "capsule"},
    { key: "tube",     label: "Tubo",       backendUnit: "tube"  },
    { key: "unit",     label: "Unidad",     backendUnit: "unit"  },
    { key: "ml",       label: "ml",         backendUnit: "ml"    },
    { key: "g",        label: "g",          backendUnit: "g"     },
    { key: "kg",       label: "kg",         backendUnit: "kg"    },
];

// Sub-unit options for "Cada [caja] contiene X [...]"
const SUB_UNIT_OPTIONS = [
    { key: "piece",   label: "piezas",   backendUnit: "piece"  },
    { key: "tablet",  label: "tabletas", backendUnit: "tablet" },
    { key: "capsule", label: "cápsulas", backendUnit: "capsule"},
    { key: "ml",      label: "ml",       backendUnit: "ml"     },
    { key: "g",       label: "g",        backendUnit: "g"      },
    { key: "dose",    label: "dosis",    backendUnit: "unit"   },
];

const EMPTY_ADJUST = { movement_type: "in", quantity: 1, reason: "" };

const TUTORIAL_STEPS = [
    {
        id: "tut-name",
        icon: "✏️",
        title: "Nombre del producto",
        text: "Primero agrega el producto que tienes en la clínica.\n\nEjemplo:\nJeringa 5ml\n\nNo importa si la compras por caja o paquete.\nEso lo configuraremos en los siguientes pasos.",
    },
    {
        id: "tut-inventory",
        icon: "📦",
        title: "Cantidad disponible",
        text: "Aquí registra cuánto tienes actualmente.\n\nEjemplo:\nSi tienes 5 cajas de jeringas y cada caja trae 100, solo indica:\n  · 5 cajas\n  · 100 por caja\n\nEl sistema calculará automáticamente que tienes 500 jeringas disponibles.",
    },
    {
        id: "tut-sales",
        icon: "🏷️",
        title: "Formas de venta",
        text: "Indica cómo quieres vender este producto.\nPuedes tener una o varias formas.\n\nEjemplo:\n  · Jeringa individual → descuenta 1 pieza\n  · Caja completa → descuenta 100 piezas\n\nAmbas usan el mismo inventario.",
    },
    {
        id: null,
        icon: "✅",
        title: "Ejemplo completo",
        text: "Producto: Jeringa 5ml\n\nTienes:\n  · 5 cajas de 100\n  · Inventario: 500 jeringas disponibles\n\nPuedes vender:\n  · 1 jeringa individual\n  · Caja completa (100 piezas)\n\nEl sistema siempre mantiene actualizado el inventario.",
    },
];
const TUTORIAL_KEY = "inventory_product_tutorial_seen";

const newSalesPres = (unitLabel = "Unidad") => ({
    _localId: `sp_${Date.now()}_${Math.random().toString(36).slice(2)}`,
    publicId: null,
    _legacyStock: 0,
    name: unitLabel,
    conversion_factor: 1,
    sale_price: "",
    purchase_price: "",
    barcode: "",
});

// ── Helpers ────────────────────────────────────────────────
const stockStatus = (product) => {
    const pres = product.presentation || {};
    const stock = parseFloat(product.stock_quantity ?? pres.stock ?? 0) || 0;
    const min = parseFloat(product.min_stock ?? pres.min_stock ?? 0) || 0;
    if (stock <= 0) return { pct: 0, state: "crit", label: "Agotado" };
    if (min > 0 && stock < min) return { pct: Math.min((stock / min) * 100, 100), state: "low", label: "Stock bajo" };
    const top = min > 0 ? min * 3 : 100;
    return { pct: Math.max(Math.min((stock / top) * 100, 100), 15), state: "ok", label: "Normal" };
};

const fmt = (n) => Math.round(parseFloat(n ?? 0) || 0);
const fmtCur = (n, locale = navigator.language) =>
    (parseFloat(n ?? 0) || 0).toLocaleString(locale, { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const easeOutExpo = (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t));

// ── Category icon ──────────────────────────────────────────
const ICON_COLOR = { medication: "#3b82f6", food: "#0d9488", accessory: "#7c3aed", other: "#94a3b8" };
const CATEGORY_ICON = { medication: Icon.Pill, food: Icon.ShoppingBag, accessory: Icon.Package, other: Icon.Box };

const CategoryIcon = ({ category, size = 18 }) => {
    const c = ICON_COLOR[category] || ICON_COLOR.other;
    const IconComp = CATEGORY_ICON[category] || CATEGORY_ICON.other;
    return <IconComp s={size} c={c} />;
};

const ICO_CLS = { medication: s.icoMed, food: s.icoFood, accessory: s.icoAcc, other: s.icoOther };
const BADGE_CLS = { medication: s.badgeBlue, food: s.badgeGreen, accessory: s.badgePurple, other: s.badgeGray };

// ── SortableHeader ─────────────────────────────────────────
const SortHeader = ({ col, label, sortCol, sortDir, onSort, align = "left" }) => {
    const active = sortCol === col;
    const ArrowIcon = active ? (sortDir === "asc" ? Icon.ArrowUp : Icon.ArrowDown) : Icon.ArrowUpDown;
    return (
        <th className={`${s.th} ${s.sortable}`} style={{ textAlign: align }} onClick={() => onSort(col)}>
            <span className={s.thInner}>
                {label}
                <span className={`${s.sortArrow} ${active ? s.active : ""}`}>
                    <ArrowIcon s={11} c="currentColor" />
                </span>
            </span>
        </th>
    );
};

// ── Component ──────────────────────────────────────────────
const Inventory = () => {
    const { token, user, initializing } = useAuth();
    const confirm = useConfirm();

    const [products, setProducts] = useState([]);
    const [loading, setLoading] = useState(true);

    const [unitChoices, setUnitChoices] = useState([]);
    const [unitsLoaded, setUnitsLoaded] = useState(false);

    const [filterCategory, setFilterCategory] = useState("");
    const [searchText, setSearchText] = useState("");
    const [stockFilter, setStockFilter] = useState("");
    const [sortCol, setSortCol] = useState("name");
    const [sortDir, setSortDir] = useState("asc");
    const [viewMode, setViewMode] = useState("table");
    const [alertDismissed, setAlertDismissed] = useState(false);

    // Wizard state (create / edit product)
    const [wizardOpen, setWizardOpen] = useState(false);
    const [wizardEditing, setWizardEditing] = useState(null);
    const [wizardProduct, setWizardProduct] = useState(EMPTY_WIZARD_PRODUCT);
    const [salesPres, setSalesPres] = useState([newSalesPres()]);
    const [countQty, setCountQty] = useState("");
    const [countUnit, setCountUnit] = useState("piece");
    const [divides, setDivides] = useState(null); // null | true | false
    const [dividesCount, setDividesCount] = useState("");
    const [dividesUnit, setDividesUnit] = useState("piece");
    const [showDetails, setShowDetails] = useState(false);
    const [wizardErrors, setWizardErrors] = useState({});
    const [showSummary, setShowSummary] = useState(false);
    const [tutorialStep, setTutorialStep] = useState(null);

    const [showAdjustModal, setShowAdjustModal] = useState(false);
    const [adjustingProduct, setAdjustingProduct] = useState(null);
    const [adjustForm, setAdjustForm] = useState(EMPTY_ADJUST);

    const [stockEntryOpen, setStockEntryOpen] = useState(false);

    const [wizardMode, setWizardMode] = useState(null); // null | "simple" | "multi"
    const [showMultiAnim, setShowMultiAnim] = useState(false);
    const [tutorialMode, setTutorialMode] = useState(false);
    const tour = useProductTour();
    const presSecondAutoRef = useRef({ nameEdited: false, cfEdited: false });

    const [saving, setSaving] = useState(false);
    const [animatedTotalVal, setAnimatedTotalVal] = useState(0);
    const [isTotalValAnimating, setIsTotalValAnimating] = useState(false);
    const totalValFrameRef = useRef(null);
    const displayedTotalValRef = useRef(0);
    const hasAnimatedTotalValRef = useRef(false);

    useEffect(() => { if (token) loadAll(); }, [token]);

    useEffect(() => {
        getUnitChoices()
            .then(data => { setUnitChoices(data); setUnitsLoaded(true); })
            .catch(() => setUnitsLoaded(true));
    }, []);

    const loadAll = async () => {
        setLoading(true);
        try {
            setProducts(toList(await getProducts()));
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const canManage = user?.role === "ADMIN";

    // ── Metrics ───────────────────────────────────────────
    const metrics = useMemo(() => {
        const active = products.filter(p => p.is_active !== false);
        return {
            total: active.length,
            medications: active.filter(p => p.category === "medication").length,
            lowStock: active.filter(p => p.presentation?.is_low_stock).length,
            outOfStock: active.filter(p => parseFloat(p.stock_quantity ?? (p.presentation || {}).stock ?? 0) <= 0).length,
            totalVal: active.reduce((acc, p) => {
                const pres = p.presentation || {};
                const sqty = parseFloat(p.stock_quantity ?? pres.stock ?? 0) || 0;
                const cf = parseFloat(pres.conversion_factor ?? 1) || 1;
                return acc + (parseFloat(pres.sale_price ?? 0) || 0) / cf * sqty;
            }, 0),
        };
    }, [products]);

    const alertProducts = useMemo(() => {
        const low = products.filter(p => p.is_active !== false && p.presentation?.is_low_stock);
        return [...low].sort((a, b) => {
            const aOut = parseFloat(a.presentation?.stock ?? 1) <= 0 ? 0 : 1;
            const bOut = parseFloat(b.presentation?.stock ?? 1) <= 0 ? 0 : 1;
            return aOut - bOut;
        });
    }, [products]);

    useEffect(() => {
        const nextValue = Math.round(metrics.totalVal);

        if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
            displayedTotalValRef.current = nextValue;
            hasAnimatedTotalValRef.current = true;
            setIsTotalValAnimating(false);
            setAnimatedTotalVal(nextValue);
            return undefined;
        }

        const media = typeof window.matchMedia === "function"
            ? window.matchMedia("(prefers-reduced-motion: reduce)")
            : null;

        if (media?.matches) {
            displayedTotalValRef.current = nextValue;
            hasAnimatedTotalValRef.current = true;
            setIsTotalValAnimating(false);
            setAnimatedTotalVal(nextValue);
            return undefined;
        }

        const isFirstLift = !hasAnimatedTotalValRef.current && nextValue > 0 && displayedTotalValRef.current === 0;
        const startValue = isFirstLift
            ? Math.max(Math.round(nextValue * 0.82), nextValue - 250000)
            : displayedTotalValRef.current;
        const delta = nextValue - startValue;

        if (delta === 0) {
            displayedTotalValRef.current = nextValue;
            hasAnimatedTotalValRef.current = true;
            setIsTotalValAnimating(false);
            setAnimatedTotalVal(nextValue);
            return undefined;
        }

        const duration = isFirstLift ? 680 : 460;
        const startedAt = performance.now();

        displayedTotalValRef.current = startValue;
        setAnimatedTotalVal(startValue);
        setIsTotalValAnimating(true);

        const tick = (now) => {
            const progress = Math.min((now - startedAt) / duration, 1);
            const eased = easeOutExpo(progress);
            const currentValue = Math.round(startValue + (delta * eased));
            displayedTotalValRef.current = currentValue;
            setAnimatedTotalVal(currentValue);
            if (progress < 1) {
                totalValFrameRef.current = window.requestAnimationFrame(tick);
            } else {
                displayedTotalValRef.current = nextValue;
                hasAnimatedTotalValRef.current = true;
                totalValFrameRef.current = null;
                setAnimatedTotalVal(nextValue);
                setIsTotalValAnimating(false);
            }
        };

        if (totalValFrameRef.current) window.cancelAnimationFrame(totalValFrameRef.current);
        totalValFrameRef.current = window.requestAnimationFrame(tick);

        return () => {
            if (totalValFrameRef.current) {
                window.cancelAnimationFrame(totalValFrameRef.current);
                totalValFrameRef.current = null;
            }
            setIsTotalValAnimating(false);
        };
    }, [metrics.totalVal]);

    const insights = useMemo(() => ([
        { label: "Total", value: metrics.total },
        { label: "Medicamentos", value: metrics.medications },
        { label: "Bajo stock", value: metrics.lowStock, tone: metrics.lowStock > 0 ? "warning" : "default" },
        { label: "Sin stock", value: metrics.outOfStock, tone: metrics.outOfStock > 0 ? "danger" : "default" },
        { label: "Valor stock", value: `$${fmtCur(animatedTotalVal)}`, tone: "value" },
    ]), [animatedTotalVal, metrics]);

    // ── Multi mode: auto-init 2nd salesPres + auto-sync name/cf ──
    useEffect(() => {
        if (wizardMode !== "multi" || wizardEditing) return;
        presSecondAutoRef.current = { nameEdited: false, cfEdited: false };
        setSalesPres(prev => prev.length < 2 ? [...prev, newSalesPres()] : prev);
    }, [wizardMode, wizardEditing]);

    useEffect(() => {
        if (wizardMode !== "multi" || wizardEditing || presSecondAutoRef.current.nameEdited) return;
        const label = STOCK_COUNTING_UNITS.find(u => u.key === countUnit)?.label || countUnit;
        setSalesPres(prev => prev.length >= 2
            ? prev.map((p, i) => i === 1 ? { ...p, name: label } : p)
            : prev);
    }, [countUnit, wizardMode, wizardEditing]);

    useEffect(() => {
        if (wizardMode !== "multi" || wizardEditing || presSecondAutoRef.current.cfEdited) return;
        const cf = Number(dividesCount) || 1;
        setSalesPres(prev => prev.length >= 2
            ? prev.map((p, i) => i === 1 ? { ...p, conversion_factor: cf } : p)
            : prev);
    }, [dividesCount, wizardMode, wizardEditing]);

    // ── Tutorial scroll ───────────────────────────────────
    useEffect(() => {
        if (tutorialStep === null) return;
        const stepId = TUTORIAL_STEPS[tutorialStep]?.id;
        if (!stepId) return;
        const timer = setTimeout(() => {
            document.querySelector(`[data-tutorial-id="${stepId}"]`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 120);
        return () => clearTimeout(timer);
    }, [tutorialStep]);

    // ── Sort handler ──────────────────────────────────────
    const handleSort = (col) => {
        if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
        else { setSortCol(col); setSortDir("asc"); }
    };

    // ── Filtered + sorted list ────────────────────────────
    const filteredProducts = useMemo(() => {
        let list = products.filter(p => {
            if (filterCategory && p.category !== filterCategory) return false;
            if (searchText) {
                const q = searchText.toLowerCase();
                if (!p.name.toLowerCase().includes(q) && !(p.description || "").toLowerCase().includes(q)) return false;
            }
            const st = stockStatus(p).state;
            if (stockFilter === "ok" && st !== "ok") return false;
            if (stockFilter === "low" && st !== "low") return false;
            if (stockFilter === "crit" && st !== "crit") return false;
            return true;
        });

        list.sort((a, b) => {
            let va, vb;
            if (sortCol === "name") {
                va = a.name.toLowerCase(); vb = b.name.toLowerCase();
            } else if (sortCol === "stock") {
                va = parseFloat((a.presentation || {}).stock ?? 0) || 0;
                vb = parseFloat((b.presentation || {}).stock ?? 0) || 0;
            } else if (sortCol === "price") {
                va = parseFloat((a.presentation || {}).sale_price ?? 0) || 0;
                vb = parseFloat((b.presentation || {}).sale_price ?? 0) || 0;
            } else if (sortCol === "value") {
                const aP = a.presentation || {};
                va = (parseFloat(aP.sale_price ?? 0) || 0) * (parseFloat(aP.stock ?? 0) || 0);
                const bP = b.presentation || {};
                vb = (parseFloat(bP.sale_price ?? 0) || 0) * (parseFloat(bP.stock ?? 0) || 0);
            } else if (sortCol === "cat") {
                va = a.category; vb = b.category;
            } else if (sortCol === "status") {
                const order = { crit: 0, low: 1, ok: 2 };
                va = order[stockStatus(a).state]; vb = order[stockStatus(b).state];
            } else return 0;
            if (va < vb) return sortDir === "asc" ? -1 : 1;
            if (va > vb) return sortDir === "asc" ? 1 : -1;
            return 0;
        });
        return list;
    }, [products, filterCategory, searchText, stockFilter, sortCol, sortDir]);

    const filteredTotalVal = useMemo(() =>
        filteredProducts.reduce((acc, p) => {
            const pres = p.presentation || {};
            const sqty = parseFloat(p.stock_quantity ?? pres.stock ?? 0) || 0;
            const cf = parseFloat(pres.conversion_factor ?? 1) || 1;
            return acc + (parseFloat(pres.sale_price ?? 0) || 0) / cf * sqty;
        }, 0),
        [filteredProducts]
    );

    // ── Preview ajuste de stock ───────────────────────────
    const previewStock = () => {
        if (!adjustingProduct || !adjustForm.quantity) return null;
        const qty = parseFloat(adjustForm.quantity) || 0;
        const pres = adjustingProduct.presentation || {};
        const cf = parseFloat(pres.conversion_factor ?? 1) || 1;
        const qtyBase = qty * cf;
        const current = parseFloat(adjustingProduct.stock_quantity ?? pres.stock ?? 0) || 0;
        if (adjustForm.movement_type === "in") return current + qtyBase;
        if (adjustForm.movement_type === "out") return Math.max(current - qtyBase, 0);
        if (adjustForm.movement_type === "adjustment") return qtyBase;
        return null;
    };

    // ── Wizard handlers ───────────────────────────────────
    const openWizardCreate = () => {
        setWizardOpen(true);
        setWizardEditing(null);
        setWizardProduct({ ...EMPTY_WIZARD_PRODUCT });
        setSalesPres([newSalesPres()]);
        setCountQty(""); setCountUnit("piece");
        setDivides(null); setDividesCount(""); setDividesUnit("piece");
        setShowDetails(false);
        setWizardErrors({});
        setShowSummary(false);
        setTutorialStep(null);
        setWizardMode(null);
        presSecondAutoRef.current = { nameEdited: false, cfEdited: false };
    };

    const openWizardEdit = (product, e) => {
        e?.stopPropagation();
        const presentations = product.presentations || [];
        const editBaseUnit = presentations[0]?.base_unit || product.base_unit || "piece";
        const loadedSalesPres = presentations.map(p => ({
            _localId: `existing_${p.id}`,
            publicId: p.public_id,
            _legacyStock: parseFloat(p.stock || 0) || 0,
            name: p.name || "",
            conversion_factor: parseFloat(p.conversion_factor ?? 1) || 1,
            sale_price: p.sale_price || "",
            purchase_price: p.purchase_price || "",
            barcode: p.barcode || "",
        }));

        setWizardOpen(true);
        setWizardEditing(product);
        setWizardProduct({
            name: product.name || "",
            internal_code: product.internal_code || "",
            description: product.description || "",
            category: product.category || "other",
            requires_prescription: product.requires_prescription || false,
            min_stock: parseFloat(product.min_stock ?? 0) || 0,
        });
        setSalesPres(loadedSalesPres.length > 0 ? loadedSalesPres : [newSalesPres()]);
        const editCountKey = STOCK_COUNTING_UNITS.find(u => u.backendUnit === editBaseUnit)?.key || "piece";
        setCountUnit(editCountKey);
        setCountQty(""); setDivides(null); setDividesCount(""); setDividesUnit("piece");
        setShowDetails(!!(product.description || product.internal_code || product.requires_prescription));
        setWizardErrors({});
        setShowSummary(false);
        setTutorialStep(null);
    };

    const finishTutorial = () => {
        localStorage.setItem(TUTORIAL_KEY, "true");
        setTutorialStep(null);
    };

    const closeWizard = () => {
        setWizardOpen(false);
        setWizardEditing(null);
        setWizardProduct({ ...EMPTY_WIZARD_PRODUCT });
        setSalesPres([newSalesPres()]);
        setCountQty(""); setCountUnit("piece");
        setDivides(null); setDividesCount(""); setDividesUnit("piece");
        setShowDetails(false);
        setWizardErrors({});
        setShowSummary(false);
        setTutorialStep(null);
        setTutorialMode(false);
        setWizardMode(null);
        presSecondAutoRef.current = { nameEdited: false, cfEdited: false };
    };

    const switchMode = () => {
        setWizardMode(null);
        setCountQty(""); setCountUnit("piece");
        setDivides(null); setDividesCount(""); setDividesUnit("piece");
        setSalesPres([newSalesPres()]);
        setWizardErrors({});
        presSecondAutoRef.current = { nameEdited: false, cfEdited: false };
    };

    const handleSubmit = () => {
        const errs = {};
        if (!wizardProduct.name.trim()) errs.name = "El nombre es obligatorio.";

        if (!wizardEditing) {
            if (!(Number(countQty) > 0)) errs.count_qty = "Ingresa la cantidad.";
            if (wizardMode === "multi") {
                if (!(Number(dividesCount) >= 1)) errs.divides_count = "Ingresa cuántas partes tiene cada unidad.";
            }
        }

        if (!(Number(salesPres[0]?.sale_price) > 0)) errs.sp_0_price = "El precio es obligatorio.";
        salesPres.forEach((p, i) => {
            if (i > 0 && !p.name.trim()) errs[`sp_${i}_name`] = "El nombre es obligatorio.";
            if (i > 0 && !(Number(p.sale_price) > 0)) errs[`sp_${i}_price`] = "El precio debe ser mayor a 0.";
        });

        if (Object.keys(errs).length) { setWizardErrors(errs); return; }
        setWizardErrors({});
        if (wizardEditing) {
            handleWizardSave();
        } else {
            setShowSummary(true);
        }
    };

    const requestCloseWizard = async () => {
        if (tutorialMode) { closeWizard(); tour.skip(); return; }
        const hasData = wizardProduct.name.trim().length > 0
            || showSummary
            || countQty !== ""
            || salesPres.some(p => p.sale_price);
        if (!hasData) { closeWizard(); return; }
        const ok = await confirm({
            message: "¿Seguro que quieres salir? Los datos ingresados se perderán y tendrás que volver a llenarlos.",
            confirmText: "Sí, salir",
            dangerMode: false,
        });
        if (ok) closeWizard();
    };

    const handleWizardSave = async () => {
        if (tutorialMode) {
            setTutorialMode(false);
            tour.finish();
            return;
        }
        setSaving(true);
        setWizardErrors({});
        try {
            const countUnitData = STOCK_COUNTING_UNITS.find(u => u.key === countUnit) || { backendUnit: "unit", label: countUnit };
            const dividesUnitData = STOCK_COUNTING_UNITS.find(u => u.key === dividesUnit) || { backendUnit: "piece", label: dividesUnit };
            const baseUnit = divides ? dividesUnitData.backendUnit : countUnitData.backendUnit;
            const buLabel = divides ? dividesUnitData.label : countUnitData.label;
            const sp0 = salesPres[0];
            const sp0cf = 1; // first pres always cf=1
            const sp0AutoName = divides ? (dividesUnitData.label || "Unidad") : (countUnitData.label || "Unidad");
            const minStockBase = Number(wizardProduct.min_stock) || 0;

            const presBase = {
                name: sp0AutoName,
                base_unit: baseUnit,
                quantity: sp0cf,
                conversion_factor: sp0cf,
                sale_price: sp0.sale_price,
                ...(sp0.purchase_price ? { purchase_price: sp0.purchase_price } : {}),
                // trim: el lookup del POS es match exacto — un espacio colado
                // (típico al escanear dentro del input) rompería el escaneo.
                ...(sp0.barcode?.trim() ? { barcode: sp0.barcode.trim() } : {}),
                min_stock: sp0cf > 0 ? minStockBase / sp0cf : 0,
            };

            const productMeta = {
                name: wizardProduct.name,
                internal_code: wizardProduct.internal_code || "",
                description: wizardProduct.description || "",
                category: wizardProduct.category,
                requires_prescription: wizardProduct.requires_prescription,
            };

            if (wizardEditing) {
                await updateProduct(wizardEditing.public_id, {
                    ...productMeta,
                    base_unit: baseUnit,
                    presentation_input: { ...presBase, stock: sp0._legacyStock },
                });

                const failedPres = [];
                for (const pres of salesPres.slice(1)) {
                    try {
                        const payload = {
                            name: pres.name,
                            base_unit: baseUnit,
                            quantity: Number(pres.conversion_factor) || 1,
                            conversion_factor: Number(pres.conversion_factor) || 1,
                            sale_price: pres.sale_price,
                            ...(pres.purchase_price ? { purchase_price: pres.purchase_price } : {}),
                            ...(pres.barcode?.trim() ? { barcode: pres.barcode.trim() } : {}),
                        };
                        if (pres.publicId) {
                            await updatePresentation(pres.publicId, payload);
                        } else {
                            await createPresentation(wizardEditing.public_id, { ...payload, stock: 0, min_stock: 0 });
                        }
                    } catch {
                        failedPres.push(pres.name || "(sin nombre)");
                    }
                }
                if (failedPres.length) {
                    toast.warning(`Producto actualizado. Fallaron ${failedPres.length} presentación(es): ${failedPres.join(", ")}.`);
                } else {
                    toast.success("Producto actualizado");
                }
            } else {
                const computedStock = divides
                    ? (Number(countQty) || 0) * (Number(dividesCount) || 0)
                    : (Number(countQty) || 0);
                const stockInSp0Units = computedStock; // sp0cf is always 1

                const created = await createProduct({
                    ...productMeta,
                    base_unit: baseUnit,
                    presentation_input: { ...presBase, stock: stockInSp0Units },
                });

                const failedPres = [];
                for (const pres of salesPres.slice(1)) {
                    try {
                        await createPresentation(created.public_id, {
                            name: pres.name,
                            base_unit: baseUnit,
                            quantity: Number(pres.conversion_factor) || 1,
                            conversion_factor: Number(pres.conversion_factor) || 1,
                            sale_price: pres.sale_price,
                            ...(pres.purchase_price ? { purchase_price: pres.purchase_price } : {}),
                            ...(pres.barcode?.trim() ? { barcode: pres.barcode.trim() } : {}),
                            stock: 0, min_stock: 0,
                        });
                    } catch {
                        failedPres.push(pres.name || "(sin nombre)");
                    }
                }

                const stockLabel = divides ? dividesUnitData.label : countUnitData.label;
                const stockMsg = ` Stock ingresado: ${fmt(computedStock)} ${stockLabel}.`;
                if (failedPres.length) {
                    toast.warning(`Producto creado.${stockMsg} No se guardaron ${failedPres.length} presentación(es): ${failedPres.join(", ")}. Agrégalas desde edición.`);
                } else {
                    toast.success(`Producto creado.${stockMsg}`);
                }
            }
            closeWizard();
            await loadAll();
        } catch (err) {
            handleFormError(err, setWizardErrors);
        } finally {
            setSaving(false);
        }
    };

    const updateSalesPres = (idx, field, value) => {
        if (idx === 1 && field === "name") presSecondAutoRef.current.nameEdited = true;
        if (idx === 1 && field === "conversion_factor") presSecondAutoRef.current.cfEdited = true;
        setSalesPres(prev => prev.map((p, i) => i === idx ? { ...p, [field]: value } : p));
    };

    const addSalesPres = (unitLabel) =>
        setSalesPres(prev => [...prev, newSalesPres(unitLabel)]);

    const removeSalesPres = (idx) =>
        setSalesPres(prev => prev.filter((_, i) => i !== idx));

    // ── Other handlers ────────────────────────────────────
    const handleDelete = async (id) => {
        const ok = await confirm({ message: "¿Eliminar este producto del inventario?", confirmText: "Eliminar", dangerMode: true });
        if (!ok) return;
        try {
            await toast.promise(deleteProduct(id), {
                loading: 'Eliminando...',
                success: 'Producto eliminado',
                error: (err) => err.response?.data?.detail || "No se puede eliminar: tiene movimientos asociados"
            });
            await loadAll();
        } catch { }
    };

    const handleAdjust = async (e) => {
        e.preventDefault();
        if (!adjustForm.quantity || parseFloat(adjustForm.quantity) <= 0) {
            toast.error("La cantidad debe ser mayor a 0"); return;
        }
        setSaving(true);
        try {
            await toast.promise(adjustStock(adjustingProduct.public_id, { ...adjustForm, quantity: parseFloat(adjustForm.quantity) }), {
                loading: 'Ajustando stock...',
                success: 'Stock ajustado correctamente',
                error: (err) => apiError(err, "Error al ajustar")
            });
            await loadAll();
            closeAdjustModal();
        } catch { } finally {
            setSaving(false);
        }
    };

    const openAdjust = (product, e) => {
        e?.stopPropagation();
        setAdjustingProduct(product);
        setAdjustForm(EMPTY_ADJUST);
        setShowAdjustModal(true);
    };

    const closeAdjustModal = () => {
        setShowAdjustModal(false);
        setAdjustingProduct(null);
        setAdjustForm(EMPTY_ADJUST);
    };

    if (initializing || loading) return (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
            <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</p>
        </div>
    );

    // ── Render ────────────────────────────────────────────
    return (
        <div>
            {/* ── Page header ── */}
            <div className={s.phead}>
                <div>
                    <div className={s.ptag}>Control de stock</div>
                    <h1 className={s.ptitle}>Inventario</h1>
                    <p className={s.psub}>Productos, medicamentos y suministros de la clínica</p>
                </div>
                {canManage && (
                    <div className={s.pacts}>
                        <button
                            className={s.btnTutorial}
                            onClick={() => tour.start({
                                openWizardCreate,
                                setWizardProduct,
                                setWizardMode,
                                setCountQty,
                                setCountUnit,
                                setDivides,
                                setDividesCount,
                                setDividesUnit,
                                updateSalesPres,
                                addSalesPres,
                                setTutorialMode,
                            })}
                            title="Ver ejemplo guiado de cómo agregar un producto"
                        >
                            <Icon.Help s={13} />
                            Ver ejemplo
                        </button>
                        <button
                            className={s.btnTutorial}
                            onClick={() => setStockEntryOpen(true)}
                            title="Sumar mercancía recibida escaneando código de barras o código interno"
                        >
                            <Icon.Package s={13} />
                            Entrada de stock
                        </button>
                        <button className={s.btnPrime} onClick={() => openWizardCreate()}>
                            <Icon.Plus s={13} />
                            Nuevo Producto
                        </button>
                    </div>
                )}
            </div>

            {/* ── Linear insights ── */}
            <section className={s.stats} aria-label="Resumen de inventario">
                <div className={s.statsIntro}>
                    <span className={s.statsEyebrow}>Linear Insights</span>
                </div>
                <div className={s.statsStrip}>
                    {insights.map((item, index) => (
                        <div key={item.label} className={`${s.statBlock} ${index === insights.length - 1 ? s.statBlockLast : ""}`}>
                            <div className={`${s.statValue} ${item.tone ? s[`statValue${item.tone.charAt(0).toUpperCase()}${item.tone.slice(1)}`] : ""} ${item.tone === "value" && isTotalValAnimating ? s.statValueCounting : ""}`}>
                                {item.value}
                            </div>
                            <div className={s.statLabel}>{item.label}</div>
                        </div>
                    ))}
                </div>
            </section>

            {/* ── Alert bar ── */}
            {!alertDismissed && alertProducts.length > 0 && (
                <div className={s.alertBar}>
                    <Icon.AlertTriangle s={14} />
                    <span>
                        <strong>{alertProducts.length} producto{alertProducts.length !== 1 ? "s" : ""}</strong> requieren atención:{" "}
                        {alertProducts.slice(0, 3).map(p => p.name.split(" ").slice(0, 2).join(" ")).join(", ")}
                        {alertProducts.length > 3 ? "…" : ""}.
                    </span>
                    <button onClick={() => setAlertDismissed(true)} style={{ display: "flex", alignItems: "center" }}>
                        <Icon.X s={14} />
                    </button>
                </div>
            )}

            {/* ── Toolbar ── */}
            <div className={s.toolbar}>
                <div className={s.tsearch}>
                    <Icon.Search s={13} />
                    <input
                        type="text"
                        placeholder="Buscar producto..."
                        value={searchText}
                        onChange={e => setSearchText(e.target.value)}
                    />
                </div>
                <div className={s.tsel}>
                    <Icon.Sliders s={13} />
                    <select value={stockFilter} onChange={e => setStockFilter(e.target.value)}>
                        <option value="">Todo el stock</option>
                        <option value="ok">Normal</option>
                        <option value="low">Stock bajo</option>
                        <option value="crit">Sin stock</option>
                    </select>
                </div>
                <div className={s.viewTog}>
                    <button className={`${s.vt} ${viewMode === "table" ? s.vtOn : ""}`} title="Tabla" onClick={() => setViewMode("table")}>
                        <Icon.Rows s={14} />
                    </button>
                    <button className={`${s.vt} ${viewMode === "grid" ? s.vtOn : ""}`} title="Cuadrícula" onClick={() => setViewMode("grid")}>
                        <Icon.Grid s={14} />
                    </button>
                </div>
                <span className={s.ctLbl}>{filteredProducts.length} producto{filteredProducts.length !== 1 ? "s" : ""}</span>
            </div>

            {/* ── Category chips ── */}
            <div className={s.chipRow}>
                {[
                    { value: "", label: "Todos" },
                    { value: "medication", label: "Medicamentos" },
                    { value: "food", label: "Alimentos" },
                    { value: "accessory", label: "Accesorios" },
                    { value: "other", label: "Otros" },
                ].map(cat => (
                    <button
                        key={cat.value}
                        className={`${s.chip} ${filterCategory === cat.value ? s.chipOn : ""}`}
                        onClick={() => setFilterCategory(cat.value)}
                    >
                        {cat.label}
                    </button>
                ))}
            </div>

            {/* ── Contenido: tabla o grid ── */}
            {filteredProducts.length === 0 ? (
                <div className={s.listEmpty}>
                    <span style={{ display: "block", textAlign: "center", opacity: 0.18 }}>
                        <Icon.Frown s={32} />
                    </span>
                    <p>{searchText ? `Sin resultados para "${searchText}"` : "No hay productos registrados"}</p>
                </div>
            ) : viewMode === "table" ? (
                <div className={s.tableWrap}>
                    <table className={s.table}>
                        <thead>
                            <tr>
                                <SortHeader col="name" label="Producto" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                                <SortHeader col="cat" label="Categoría" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                                <SortHeader col="stock" label="Stock" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                                <SortHeader col="status" label="Estado" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                                <SortHeader col="price" label="Precio unit." sortCol={sortCol} sortDir={sortDir} onSort={handleSort} align="right" />
                                <SortHeader col="value" label="Valor en stock" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} align="right" />
                                {canManage && <th className={s.th}>Acciones</th>}
                            </tr>
                        </thead>
                        <tbody>
                            {filteredProducts.map(product => {
                                const pres = product.presentation || {};
                                const stockVal = parseFloat(product.stock_quantity ?? pres.stock ?? 0) || 0;
                                const salePrice = parseFloat(pres.sale_price ?? 0) || 0;
                                const cf = parseFloat(pres.conversion_factor ?? 1) || 1;
                                const unitDisplay = product.base_unit
                                    ? (product.base_unit_display || product.base_unit)
                                    : (pres.base_unit_display || pres.base_unit || "ud.");
                                const val = (salePrice / cf) * stockVal;
                                const st = stockStatus(product);
                                const multiPres = (product.presentations?.length || 0) > 1;
                                return (
                                    <tr key={product.id}>
                                        <td className={s.td}>
                                            <div className={s.prodCell}>
                                                <div className={`${s.prodIco} ${ICO_CLS[product.category] || s.icoOther}`}>
                                                    <CategoryIcon category={product.category} />
                                                </div>
                                                <div>
                                                    <div className={s.prodName}>{product.name}</div>
                                                    {product.internal_code && (
                                                        <div className={s.prodDesc}>{product.internal_code}</div>
                                                    )}
                                                    {product.description && (
                                                        <div className={s.prodDesc}>{product.description}</div>
                                                    )}
                                                    <div style={{ display: "flex", gap: "4px", marginTop: "3px", flexWrap: "wrap" }}>
                                                        {multiPres && (
                                                            <span className={`${s.badge} ${s.badgeGray}`}>
                                                                {product.presentations.length} presentaciones
                                                            </span>
                                                        )}
                                                        {product.requires_prescription && (
                                                            <span className={`${s.badge} ${s.badgePurple}`}>Receta</span>
                                                        )}
                                                        {!product.is_active && (
                                                            <span className={`${s.badge} ${s.badgeGray}`}>Inactivo</span>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className={s.td}>
                                            <span className={`${s.badge} ${BADGE_CLS[product.category] || s.badgeGray}`}>
                                                {CATEGORY_LABELS[product.category] || "Otro"}
                                            </span>
                                        </td>
                                        <td className={s.td}>
                                            <div className={s.stockCell}>
                                                <span className={`${s.stockNum} ${st.state === "crit" ? s.stockNumCrit : st.state === "low" ? s.stockNumLow : ""}`}>
                                                    {fmt(stockVal)}
                                                </span>
                                                <span className={s.stockUnit}>{unitDisplay}</span>
                                                <div className={s.miniBar}>
                                                    <div
                                                        className={`${s.miniBarFill} ${st.state === "crit" ? s.barCrit : st.state === "low" ? s.barLow : s.barOk}`}
                                                        style={{ width: `${st.pct}%` }}
                                                    />
                                                </div>
                                            </div>
                                        </td>
                                        <td className={s.td}>
                                            <span className={`${s.pill} ${st.state === "crit" ? s.pillCrit : st.state === "low" ? s.pillLow : s.pillOk}`}>
                                                <span className={`${s.pillDot} ${st.state === "crit" ? s.dotCrit : st.state === "low" ? s.dotLow : s.dotOk}`} />
                                                {st.label}
                                            </span>
                                        </td>
                                        <td className={s.td} style={{ textAlign: "right" }}>
                                            {salePrice > 0 ? (
                                                <div className={s.valMain}>${fmtCur(salePrice)}</div>
                                            ) : (
                                                <span style={{ color: "var(--c-text-3)", fontSize: "12px" }}>—</span>
                                            )}
                                            {unitDisplay && salePrice > 0 && (
                                                <div className={s.valSub}>por {unitDisplay}</div>
                                            )}
                                        </td>
                                        <td className={s.td} style={{ textAlign: "right" }}>
                                            {val > 0 ? (
                                                <div className={s.valMain}>${fmtCur(val)}</div>
                                            ) : (
                                                <span style={{ color: "var(--c-text-3)", fontSize: "12px" }}>—</span>
                                            )}
                                        </td>
                                        {canManage && (
                                            <td className={s.td}>
                                                <div className={s.actCell}>
                                                    <button className={`${s.ab} ${s.abAj}`} onClick={e => openAdjust(product, e)} title="Ajustar stock"><Icon.Package s={14} /></button>
                                                    <button className={`${s.ab} ${s.abEd}`} onClick={e => openWizardEdit(product, e)} title="Editar"><Icon.Edit s={14} /></button>
                                                    <button className={`${s.ab} ${s.abDl}`} onClick={e => { e.stopPropagation(); handleDelete(product.public_id); }} title="Eliminar"><Icon.Trash s={14} /></button>
                                                </div>
                                            </td>
                                        )}
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    <div className={s.tableFooter}>
                        <span>{filteredProducts.length} de {products.length} productos</span>
                        {filteredTotalVal > 0 && (
                            <span>
                                Valor total (filtrado):{" "}
                                <span className={s.footerTotal}>${fmtCur(filteredTotalVal)}</span>
                            </span>
                        )}
                    </div>
                </div>
            ) : (
                /* ── Grid view ── */
                <div className={s.prodGrid}>
                    {filteredProducts.map(product => {
                        const pres = product.presentation || {};
                        const stockVal = parseFloat(product.stock_quantity ?? pres.stock ?? 0) || 0;
                        const unitDisplay = product.base_unit || pres.base_unit_display || pres.base_unit || "ud.";
                        const st = stockStatus(product);
                        const multiPres = (product.presentations?.length || 0) > 1;
                        return (
                            <div key={product.id} className={s.pg}>
                                <div className={s.pgTop}>
                                    <div className={`${s.pgIco} ${ICO_CLS[product.category] || s.icoOther}`}>
                                        <CategoryIcon category={product.category} size={18} />
                                    </div>
                                    <span className={`${s.badge} ${BADGE_CLS[product.category] || s.badgeGray}`}>
                                        {CATEGORY_LABELS[product.category] || "Otro"}
                                    </span>
                                </div>
                                <div className={s.pgName}>{product.name}</div>
                                {multiPres && (
                                    <div style={{ display: "flex", gap: "4px", flexWrap: "wrap", marginBottom: "6px" }}>
                                        {product.presentations.map(p => (
                                            <span key={p.id} className={`${s.badge} ${s.badgeGray}`} style={{ fontSize: "9.5px" }}>
                                                {p.name}
                                            </span>
                                        ))}
                                    </div>
                                )}
                                {product.description && <div className={s.pgDesc}>{product.description}</div>}
                                <div className={s.pgStk}>
                                    <span className={`${s.pgStkV} ${st.state === "crit" ? s.stockNumCrit : st.state === "low" ? s.stockNumLow : ""}`}>
                                        {fmt(stockVal)}
                                    </span>
                                    <span className={s.pgStkU}>{unitDisplay}</span>
                                </div>
                                <div className={s.pgBar}>
                                    <div className={`${s.pgBarF} ${st.state === "crit" ? s.barCrit : st.state === "low" ? s.barLow : s.barOk}`} style={{ width: `${st.pct}%` }} />
                                </div>
                                {canManage && (
                                    <div className={s.pgFoot}>
                                        <button className={s.pgAdj} onClick={e => openAdjust(product, e)}>Ajustar</button>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {/* ── Modal: Wizard Producto ── */}
            {wizardOpen && (() => {
                const cud = STOCK_COUNTING_UNITS.find(u => u.key === countUnit) || { label: countUnit, backendUnit: countUnit };
                const dud = STOCK_COUNTING_UNITS.find(u => u.key === dividesUnit) || { label: dividesUnit, backendUnit: dividesUnit };
                const countUnitLabel = cud.label;
                const dividesUnitLabel = dud.label;
                const baseUnitLabel = divides ? dividesUnitLabel : countUnitLabel;
                const editBaseUnitLabel = wizardEditing
                    ? (STOCK_COUNTING_UNITS.find(u => u.backendUnit === (wizardEditing.base_unit || "piece"))?.label || wizardEditing.base_unit || "unidad")
                    : baseUnitLabel;
                const baseUnitLabelForSales = wizardEditing ? editBaseUnitLabel : baseUnitLabel;
                const computedStock = !wizardEditing && divides === true
                    ? (Number(countQty) || 0) * (Number(dividesCount) || 0)
                    : (!wizardEditing && divides === false ? Number(countQty) || 0 : 0);

                return (
                    <div className="modal-overlay">
                        <div className="modal modal-md">
                            <div className="modal-header">
                                <div>
                                    <h3>{showSummary ? "Confirmar producto" : wizardEditing ? "Editar Producto" : wizardMode === "simple" ? "Producto normal" : wizardMode === "multi" ? "Varias formas de venta" : "Nuevo Producto"}</h3>
                                    {showSummary && <p style={{ fontSize: "12px", color: "var(--c-text-3)", marginTop: "2px" }}>Revisa los datos antes de guardar</p>}
                                </div>
                                <button className="modal-close" onClick={requestCloseWizard}><Icon.X s={16} /></button>
                            </div>

                            <div className="modal-body">
                                {/* ── Summary ── */}
                                {showSummary && (
                                    <div>
                                        <div className={s.summaryHead}>
                                            <div className={`${s.prodIco} ${ICO_CLS[wizardProduct.category] || s.icoOther}`}>
                                                <CategoryIcon category={wizardProduct.category} />
                                            </div>
                                            <div>
                                                <div className={s.summaryProdName}>{wizardProduct.name}</div>
                                                <div style={{ display: "flex", gap: "6px", marginTop: "5px", flexWrap: "wrap", alignItems: "center" }}>
                                                    <span className={`${s.badge} ${BADGE_CLS[wizardProduct.category] || s.badgeGray}`}>{CATEGORY_LABELS[wizardProduct.category]}</span>
                                                    {Number(wizardProduct.min_stock) > 0 && <span className={s.summaryMeta}>Mínimo: {wizardProduct.min_stock} {baseUnitLabel}</span>}
                                                </div>
                                            </div>
                                        </div>

                                        <div style={{ marginTop: 16, padding: "12px 14px", background: "var(--c-subtle)", borderRadius: "var(--r-lg)" }}>
                                            <div style={{ fontSize: "10.5px", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".07em", color: "var(--c-text-3)", marginBottom: "5px" }}>Inventario inicial</div>
                                            <div style={{ fontSize: "20px", fontWeight: 800, color: "var(--c-text)", lineHeight: 1 }}>
                                                {fmt(computedStock)} <span style={{ fontSize: "13px", fontWeight: 500, color: "var(--c-text-2)" }}>{baseUnitLabelForSales}</span>
                                            </div>
                                            {divides === true && Number(dividesCount) > 0 && (
                                                <div style={{ fontSize: "12px", color: "var(--c-text-3)", marginTop: "3px" }}>
                                                    {countQty} {countUnitLabel.toLowerCase()} × {dividesCount} {dividesUnitLabel}
                                                </div>
                                            )}
                                        </div>

                                        <div style={{ marginTop: 16 }}>
                                            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".07em", color: "var(--c-text-3)", marginBottom: "10px" }}>
                                                {salesPres.length === 1 ? "Forma de venta" : `${salesPres.length} formas de venta`}
                                            </div>
                                            <div className={s.summaryTable}>
                                                <div className={s.summaryTableHead}>
                                                    <span>Nombre</span><span>Contiene</span><span>Precio venta</span><span>Costo</span>
                                                </div>
                                                {salesPres.map((p, i) => (
                                                    <div key={i} className={s.summaryTableRow}>
                                                        <span style={{ fontWeight: 600 }}>{p.name || "—"}</span>
                                                        <span>{p.conversion_factor} {baseUnitLabelForSales}</span>
                                                        <span>${parseFloat(p.sale_price || 0).toFixed(2)}</span>
                                                        <span style={{ color: "var(--c-text-3)" }}>{p.purchase_price ? `$${parseFloat(p.purchase_price).toFixed(2)}` : "—"}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* ── Form ── */}
                                {!showSummary && (
                                    <div>
                                        {/* ─── Mode selector (create only, no mode chosen) ─── */}
                                        {!wizardEditing && wizardMode === null && (
                                            <div data-demo="mode-selector">
                                                <p className={s.modeSelectorTitle}>¿Cómo se vende este producto?</p>
                                                <div className={s.modeCards}>
                                                    <button
                                                        type="button"
                                                        className={s.modeCard}
                                                        data-demo="mode-simple"
                                                        onClick={() => { setWizardMode("simple"); setDivides(false); }}
                                                    >
                                                        <div className={s.modeCardIco}><Icon.Package s={22} /></div>
                                                        <div className={s.modeCardTitle}>Producto normal</div>
                                                        <div className={s.modeCardDesc}>Para productos que vendes siempre de la misma forma</div>
                                                        <div className={s.modeCardEx}>Shampoo, collar, alimento, medicamento cerrado...</div>
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className={s.modeCard}
                                                        data-demo="mode-multi"
                                                        onClick={() => { setWizardMode("multi"); setDivides(true); }}
                                                    >
                                                        <div className={s.modeCardIco}><Icon.Boxes s={22} /></div>
                                                        <div className={s.modeCardTitle}>Varias formas de venta</div>
                                                        <div className={s.modeCardDesc}>Cuando el mismo inventario puede venderse en diferentes cantidades</div>
                                                        <div className={s.modeCardEx}>Caja de jeringas → jeringa individual o caja completa</div>
                                                    </button>
                                                </div>
                                                <div className={s.modeNote}>
                                                    <Icon.AlertCircle s={13} />
                                                    <span>Alimento 2kg y alimento 10kg → son dos productos normales. Crea un producto por tamaño.</span>
                                                </div>
                                                <div style={{ display: "flex", justifyContent: "center", marginTop: 10 }}>
                                                    <button
                                                        type="button"
                                                        style={{
                                                            background: "none", border: "none", cursor: "pointer",
                                                            fontSize: "12px", color: "var(--c-text-3)", fontFamily: "inherit",
                                                            display: "inline-flex", alignItems: "center", gap: "5px",
                                                            padding: "4px 8px", borderRadius: "var(--r-sm)",
                                                        }}
                                                        onClick={() => setShowMultiAnim(true)}
                                                    >
                                                        <Icon.Help s={12} /> ¿Cómo funciona "Varias formas"?
                                                    </button>
                                                </div>
                                            </div>
                                        )}

                                        {/* ─── Form fields (mode chosen or editing) ─── */}
                                        {(wizardEditing || wizardMode !== null) && (
                                            <>
                                                {/* Chosen mode badge + back link */}
                                                {!wizardEditing && (
                                                    <div className={s.modeChosen}>
                                                        <span className={s.modeChosenBadge}>
                                                            {wizardMode === "simple"
                                                                ? <><Icon.Package s={11} /> Producto normal</>
                                                                : <><Icon.Boxes s={11} /> Varias formas de venta</>}
                                                        </span>
                                                        <button type="button" className={s.modeBackBtn} onClick={switchMode}>
                                                            Cambiar tipo
                                                        </button>
                                                    </div>
                                                )}

                                                {/* ─── Tutorial guide card ─── */}
                                                {tutorialStep !== null && (() => {
                                                    const ts = TUTORIAL_STEPS[tutorialStep];
                                                    const isLast = tutorialStep === TUTORIAL_STEPS.length - 1;
                                                    return (
                                                        <div className={s.tutCard}>
                                                            <div className={s.tutHeader}>
                                                                <span className={s.tutIconBig}>{ts.icon}</span>
                                                                <div style={{ flex: 1 }}>
                                                                    <div className={s.tutTitle}>{ts.title}</div>
                                                                    <div className={s.tutStepLabel}>Paso {tutorialStep + 1} de {TUTORIAL_STEPS.length}</div>
                                                                </div>
                                                                <button type="button" className={s.tutSkipBtn} onClick={finishTutorial}>Saltar</button>
                                                            </div>
                                                            <div className={s.tutBody}>{ts.text}</div>
                                                            <div className={s.tutNav}>
                                                                <div className={s.tutDots}>
                                                                    {TUTORIAL_STEPS.map((_, i) => (
                                                                        <span key={i} className={`${s.tutDot} ${i === tutorialStep ? s.tutDotOn : i < tutorialStep ? s.tutDotDone : ""}`} />
                                                                    ))}
                                                                </div>
                                                                <div className={s.tutNavBtns}>
                                                                    {tutorialStep > 0 && (
                                                                        <button type="button" className={s.tutNavBtn} onClick={() => setTutorialStep(t => t - 1)}>← Anterior</button>
                                                                    )}
                                                                    <button
                                                                        type="button"
                                                                        className={`${s.tutNavBtn} ${s.tutNavBtnPrime}`}
                                                                        onClick={isLast ? finishTutorial : () => setTutorialStep(t => t + 1)}
                                                                    >
                                                                        {isLast ? "Entendido ✓" : "Siguiente →"}
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    );
                                                })()}

                                                {/* ─── BLOQUE 1: Producto ─── */}
                                                <div className="form-group" data-tutorial-id="tut-name" data-demo="product-name">
                                                    <label className="form-label">NOMBRE DEL PRODUCTO *</label>
                                                    <input
                                                        className={`input${wizardErrors.name ? " input-error" : ""}`}
                                                        value={wizardProduct.name}
                                                        onChange={e => setWizardProduct(p => ({ ...p, name: e.target.value }))}
                                                        placeholder="Ej: Jeringa 3ml, Amoxicilina 500mg..."
                                                        autoFocus
                                                    />
                                                    {wizardErrors.name && <p className={s.fieldErr}>{wizardErrors.name}</p>}
                                                </div>

                                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 14px" }}>
                                                    <div className="form-group">
                                                        <label className="form-label">CATEGORÍA</label>
                                                        <select className="select-input" value={wizardProduct.category}
                                                            onChange={e => {
                                                                setWizardProduct(p => ({ ...p, category: e.target.value }));
                                                            }}>
                                                            <option value="medication">Medicamento</option>
                                                            <option value="food">Alimento</option>
                                                            <option value="accessory">Accesorio</option>
                                                            <option value="other">Otro</option>
                                                        </select>
                                                    </div>
                                                    <div className="form-group">
                                                        <label className="form-label">CÓDIGO INTERNO <span style={{ fontWeight: 400, color: "var(--c-text-3)" }}>(opcional)</span></label>
                                                        <input className={`input${wizardErrors.internal_code ? " input-error" : ""}`}
                                                            value={wizardProduct.internal_code}
                                                            onChange={e => setWizardProduct(p => ({ ...p, internal_code: e.target.value }))}
                                                            placeholder="Ej: MED-001" />
                                                        {wizardErrors.internal_code && <p className={s.fieldErr}>{wizardErrors.internal_code}</p>}
                                                    </div>
                                                </div>

                                                <button type="button" className={s.detailsToggle} onClick={() => setShowDetails(v => !v)}>
                                                    {showDetails ? "▾" : "▸"} {showDetails ? "Ocultar" : "Descripción y receta médica"}
                                                </button>
                                                {showDetails && (
                                                    <div style={{ marginTop: 10 }}>
                                                        <div className="form-group">
                                                            <label className="form-label">DESCRIPCIÓN</label>
                                                            <textarea className="textarea-input" style={{ minHeight: "52px" }}
                                                                value={wizardProduct.description}
                                                                onChange={e => setWizardProduct(p => ({ ...p, description: e.target.value }))}
                                                                placeholder="Descripción breve..." />
                                                        </div>
                                                        <div className="form-group" style={{ marginBottom: 0 }}>
                                                            <label className="checkbox-label">
                                                                <input type="checkbox"
                                                                    checked={wizardProduct.requires_prescription}
                                                                    onChange={e => setWizardProduct(p => ({ ...p, requires_prescription: e.target.checked }))} />
                                                                Requiere receta médica
                                                            </label>
                                                        </div>
                                                    </div>
                                                )}

                                                {/* ─── BLOQUE 2: Existencia inicial (solo create) ─── */}
                                                {!wizardEditing && (
                                                    <>
                                                        <div className={s.formDivider} />

                                                        {wizardMode === "simple" ? (
                                                            /* Modo simple: solo cantidad + unidad, sin pregunta de división */
                                                            <>
                                                                <div data-demo="stock-section" style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".07em", color: "var(--c-text-3)", marginBottom: "10px" }}>
                                                                    ¿Cuánto tienes actualmente?
                                                                </div>
                                                                <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1.4fr", gap: "0 12px" }}>
                                                                    <div className="form-group">
                                                                        <label className="form-label">CANTIDAD *</label>
                                                                        <input type="number" min="0" step="1"
                                                                            className={`input${wizardErrors.count_qty ? " input-error" : ""}`}
                                                                            value={countQty}
                                                                            onChange={e => setCountQty(e.target.value)}
                                                                            placeholder="0" />
                                                                        {wizardErrors.count_qty && <p className={s.fieldErr}>{wizardErrors.count_qty}</p>}
                                                                    </div>
                                                                    <div className="form-group">
                                                                        <label className="form-label">UNIDAD</label>
                                                                        <select className="select-input" value={countUnit}
                                                                            onChange={e => setCountUnit(e.target.value)}>
                                                                            {STOCK_COUNTING_UNITS.map(u => <option key={u.key} value={u.key}>{u.label}</option>)}
                                                                        </select>
                                                                    </div>
                                                                </div>
                                                                {Number(countQty) > 0 && (
                                                                    <div className={s.stockPreview}>
                                                                        <strong>{fmt(Number(countQty))}</strong> {countUnitLabel} disponibles
                                                                    </div>
                                                                )}
                                                            </>
                                                        ) : (
                                                            /* Modo multi: cantidad + división directa (sin toggle) */
                                                            <>
                                                                <div data-demo="stock-section" style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".07em", color: "var(--c-text-3)", marginBottom: "10px" }}>
                                                                    ¿Cuánto tienes actualmente?
                                                                </div>
                                                                <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1.4fr", gap: "0 12px" }}>
                                                                    <div className="form-group">
                                                                        <label className="form-label">CANTIDAD *</label>
                                                                        <input type="number" min="0" step="1"
                                                                            className={`input${wizardErrors.count_qty ? " input-error" : ""}`}
                                                                            value={countQty}
                                                                            onChange={e => setCountQty(e.target.value)}
                                                                            placeholder="0" />
                                                                        {wizardErrors.count_qty && <p className={s.fieldErr}>{wizardErrors.count_qty}</p>}
                                                                    </div>
                                                                    <div className="form-group">
                                                                        <label className="form-label">CONTADO COMO</label>
                                                                        <select className="select-input" value={countUnit}
                                                                            onChange={e => setCountUnit(e.target.value)}>
                                                                            {STOCK_COUNTING_UNITS.map(u => <option key={u.key} value={u.key}>{u.label}</option>)}
                                                                        </select>
                                                                    </div>
                                                                </div>
                                                                <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "0 12px" }}>
                                                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                                                        <label className="form-label">{`CADA ${countUnitLabel.toUpperCase()} CONTIENE *`}</label>
                                                                        <input type="number" min="1" step="1"
                                                                            className={`input${wizardErrors.divides_count ? " input-error" : ""}`}
                                                                            value={dividesCount}
                                                                            onChange={e => setDividesCount(e.target.value)}
                                                                            placeholder="Ej: 100" />
                                                                        {wizardErrors.divides_count && <p className={s.fieldErr}>{wizardErrors.divides_count}</p>}
                                                                    </div>
                                                                    <div className="form-group" style={{ marginBottom: 0 }}>
                                                                        <label className="form-label">UNIDAD</label>
                                                                        <select className="select-input" value={dividesUnit}
                                                                            onChange={e => setDividesUnit(e.target.value)}>
                                                                            {SUB_UNIT_OPTIONS.map(u => <option key={u.key} value={u.key}>{u.label}</option>)}
                                                                        </select>
                                                                    </div>
                                                                </div>
                                                                {Number(countQty) > 0 && (
                                                                    <div className={s.stockPreview}>
                                                                        {dividesCount
                                                                            ? <>{countQty} {countUnitLabel.toLowerCase()} × {dividesCount} = <strong>{fmt((Number(countQty) || 0) * (Number(dividesCount) || 0))}</strong> {dividesUnitLabel} disponibles</>
                                                                            : <>Indica cuántas {dividesUnitLabel} tiene cada {countUnitLabel.toLowerCase()} →</>
                                                                        }
                                                                    </div>
                                                                )}
                                                            </>
                                                        )}
                                                    </>
                                                )}

                                                {/* ─── BLOQUE 3: Formas de venta ─── */}
                                                <div className={s.formDivider} />
                                                <div data-tutorial-id="tut-sales" style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".07em", color: "var(--c-text-3)", marginBottom: "12px" }}>
                                                    {wizardEditing ? "Formas de venta" : "¿Cómo lo venderás?"}
                                                    {!wizardEditing && computedStock > 0 && (
                                                        <span style={{ fontWeight: 400, textTransform: "none", fontSize: "12px", color: "var(--c-text-2)", marginLeft: "8px" }}>
                                                            Disponible: {fmt(computedStock)} {baseUnitLabelForSales}
                                                        </span>
                                                    )}
                                                </div>

                                                {salesPres.map((sp, idx) => {
                                                    const errName = idx > 0 ? wizardErrors[`sp_${idx}_name`] : null;
                                                    const errPrice = idx === 0
                                                        ? (wizardErrors.sp_0_price || wizardErrors["presentation_input.sale_price"] || wizardErrors.sale_price)
                                                        : wizardErrors[`sp_${idx}_price`];
                                                    const canRemove = idx > 0 && !sp.publicId;
                                                    return (
                                                        <div key={sp._localId} className={idx > 0 ? s.presCard : undefined} style={idx > 0 ? undefined : { marginBottom: 4 }} data-demo={`sale-${idx}`}>
                                                            {idx > 0 && (
                                                                <div className={s.presCardHead}>
                                                                    <span className={s.presNum}>
                                                                        {sp.name || `Forma ${idx + 1}`}
                                                                        {sp.publicId && <span style={{ marginLeft: 6, fontSize: 10, color: "var(--c-text-3)", fontWeight: 400 }}>(guardada)</span>}
                                                                    </span>
                                                                    {canRemove && <button type="button" className={s.presRemoveBtn} onClick={() => removeSalesPres(idx)}>Quitar</button>}
                                                                </div>
                                                            )}
                                                            {idx === 0 && !wizardEditing ? (
                                                                <div style={{ fontSize: 12, color: "var(--c-text-3)", marginBottom: 8 }}>
                                                                    Descuenta <strong style={{ color: "var(--c-text-2)" }}>1 {baseUnitLabelForSales}</strong> por venta
                                                                </div>
                                                            ) : (
                                                                <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: "0 10px" }}>
                                                                    {(idx > 0 || wizardEditing) && (
                                                                        <div className="form-group">
                                                                            <label className="form-label">NOMBRE *</label>
                                                                            <input className={`input${errName ? " input-error" : ""}`}
                                                                                value={sp.name}
                                                                                onChange={e => updateSalesPres(idx, "name", e.target.value)}
                                                                                placeholder="Ej: Caja completa, Blíster 10" />
                                                                            {errName && <p className={s.fieldErr}>{errName}</p>}
                                                                        </div>
                                                                    )}
                                                                    <div className="form-group">
                                                                        <label className="form-label">CONTIENE ({baseUnitLabelForSales.toUpperCase()})</label>
                                                                        <input type="number" min="1" step="1" className="input"
                                                                            value={sp.conversion_factor}
                                                                            onChange={e => { const v = Number(e.target.value); if (v >= 1) updateSalesPres(idx, "conversion_factor", v); }}
                                                                            placeholder="1" />
                                                                    </div>
                                                                </div>
                                                            )}
                                                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0 10px" }}>
                                                                <div className="form-group" style={{ marginBottom: 0 }}>
                                                                    <label className="form-label">PRECIO *</label>
                                                                    <input type="number" step="0.01" min="0.01"
                                                                        className={`input${errPrice ? " input-error" : ""}`}
                                                                        value={sp.sale_price}
                                                                        onChange={e => updateSalesPres(idx, "sale_price", e.target.value)}
                                                                        placeholder="0.00" />
                                                                    {errPrice && <p className={s.fieldErr}>{errPrice}</p>}
                                                                </div>
                                                                <div className="form-group" style={{ marginBottom: 0 }}>
                                                                    <label className="form-label">COSTO <span style={{ fontWeight: 400, color: "var(--c-text-3)" }}>(opc.)</span></label>
                                                                    <input type="number" step="0.01" min="0" className="input"
                                                                        value={sp.purchase_price}
                                                                        onChange={e => updateSalesPres(idx, "purchase_price", e.target.value)}
                                                                        placeholder="0.00" />
                                                                </div>
                                                                <div className="form-group" style={{ marginBottom: 0 }}>
                                                                    <label className="form-label">BARRAS <span style={{ fontWeight: 400, color: "var(--c-text-3)" }}>(opc.)</span></label>
                                                                    <input type="text" className="input"
                                                                        value={sp.barcode}
                                                                        onChange={e => updateSalesPres(idx, "barcode", e.target.value)}
                                                                        placeholder="Escanear o escribir" />
                                                                </div>
                                                            </div>
                                                        </div>
                                                    );
                                                })}

                                                {(wizardMode === "multi" || wizardEditing) && (
                                                    <button type="button" className={s.addPresBtn} style={{ marginTop: salesPres.length > 1 ? "6px" : "0" }}
                                                        data-demo="add-sale-btn"
                                                        onClick={() => addSalesPres(baseUnitLabelForSales)}>
                                                        <Icon.Plus s={12} /> Agregar otra forma de venta
                                                    </button>
                                                )}

                                                <div className={s.alertRow} style={{ marginTop: 16 }}>
                                                    <span className={s.alertRowLabel}>Avisarme cuando queden menos de</span>
                                                    <input type="number" min="0" step="1" className={`input ${s.alertRowInput}`}
                                                        value={wizardProduct.min_stock}
                                                        onChange={e => {
                                                            const v = e.target.value;
                                                            if (v === "") { setWizardProduct(p => ({ ...p, min_stock: "" })); return; }
                                                            const n = Number(v);
                                                            if (Number.isFinite(n) && n >= 0 && n <= 1_000_000) setWizardProduct(p => ({ ...p, min_stock: n }));
                                                        }}
                                                        placeholder="0" />
                                                    <span className={s.alertRowUnit}>{baseUnitLabelForSales} en inventario</span>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>

                            <div className="modal-footer">
                                {showSummary ? (
                                    <>
                                        <button type="button" className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleWizardSave} disabled={saving}>
                                            {saving ? "Guardando..." : "Confirmar y crear"}
                                        </button>
                                        <button type="button" className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => setShowSummary(false)}>
                                            Hacer cambios
                                        </button>
                                    </>
                                ) : (!wizardEditing && wizardMode === null) ? (
                                    <button type="button" className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={requestCloseWizard}>
                                        Cancelar
                                    </button>
                                ) : (
                                    <>
                                        <button type="button" className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleSubmit} disabled={saving}>
                                            {saving ? "Guardando..." : wizardEditing ? "Guardar cambios" : "Crear producto"}
                                        </button>
                                        <button type="button" className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={requestCloseWizard}>
                                            Cancelar
                                        </button>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                );
            })()}

            {/* ── Multi-presentation concept animation ── */}
            {showMultiAnim && (
                <MultiPresentationAnimation
                    onDismiss={() => setShowMultiAnim(false)}
                />
            )}

            {/* ── Interactive demo overlay ── */}
            <ProductCreationTour
                demoActive={tour.demoActive}
                stepIdx={tour.stepIdx}
                currentStep={tour.currentStep}
                isLastStep={tour.isLastStep}
                filling={tour.filling}
                onNext={tour.next}
                onSkip={() => { tour.skip(); closeWizard(); }}
                onFinish={() => { tour.finish(); setTutorialMode(false); }}
            />

            {/* ── Modal: Ajuste de Stock ── */}
            {showAdjustModal && adjustingProduct && (
                <div className="modal-overlay">
                    <div className="modal modal-sm">
                        <div className="modal-header">
                            <div>
                                <h3>Ajustar Stock</h3>
                                <p style={{ fontSize: "12.5px", color: "var(--c-text-2)", marginTop: "2px" }}>
                                    {adjustingProduct.name}
                                </p>
                            </div>
                            <button className="modal-close" onClick={closeAdjustModal}><Icon.X s={16} /></button>
                        </div>
                        <div className="modal-body">
                            {(() => {
                                const adjPres = adjustingProduct.presentation || {};
                                const adjStock = parseFloat(adjustingProduct.stock_quantity ?? adjPres.stock ?? 0) || 0;
                                const adjUnit = adjustingProduct.base_unit || adjPres.base_unit_display || adjPres.base_unit || "";
                                const adjCf = parseFloat(adjPres.conversion_factor ?? 1) || 1;
                                const preview = previewStock();
                                return (
                                    <div style={{
                                        background: "var(--c-subtle)", borderRadius: "var(--r-lg)",
                                        padding: "12px 16px", display: "flex", justifyContent: "space-between",
                                        alignItems: "center", marginBottom: "20px",
                                    }}>
                                        <div>
                                            <div style={{ fontSize: "10.5px", color: "var(--c-text-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>
                                                Stock actual
                                            </div>
                                            <div style={{ fontSize: "26px", fontWeight: "800", color: "var(--c-text)", lineHeight: 1 }}>
                                                {fmt(adjStock)}
                                                <span style={{ fontSize: "13px", fontWeight: "500", color: "var(--c-text-2)", marginLeft: "4px" }}>{adjUnit}</span>
                                            </div>
                                        </div>
                                        {preview !== null && (
                                            <>
                                                <div style={{ fontSize: "22px", color: "var(--c-text-3)" }}>→</div>
                                                <div style={{ textAlign: "right" }}>
                                                    <div style={{ fontSize: "10.5px", color: "var(--c-text-3)", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "3px" }}>
                                                        Resultado
                                                    </div>
                                                    <div style={{ fontSize: "26px", fontWeight: "800", color: "var(--c-primary-dark)", lineHeight: 1 }}>
                                                        {fmt(preview)}
                                                        <span style={{ fontSize: "13px", fontWeight: "500", color: "var(--c-text-2)", marginLeft: "4px" }}>{adjUnit}</span>
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                );
                            })()}

                            <div className="form-group">
                                <label className="form-label">TIPO DE MOVIMIENTO</label>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "7px" }}>
                                    {[
                                        { value: "in", label: "Entrada", icon: "↑", color: "var(--c-success-text)", bg: "var(--c-success-bg)", border: "var(--c-success-border)" },
                                        { value: "out", label: "Salida", icon: "↓", color: "var(--c-danger-text)", bg: "var(--c-danger-bg)", border: "var(--c-danger-border)" },
                                        { value: "adjustment", label: "Ajuste", icon: "⇌", color: "var(--c-warning-text)", bg: "var(--c-warning-bg)", border: "var(--c-warning-border)" },
                                    ].map(opt => {
                                        const active = adjustForm.movement_type === opt.value;
                                        return (
                                            <button
                                                key={opt.value}
                                                type="button"
                                                onClick={() => setAdjustForm({ ...adjustForm, movement_type: opt.value })}
                                                style={{
                                                    padding: "10px 6px",
                                                    border: `1.5px solid ${active ? opt.border : "var(--c-border)"}`,
                                                    borderRadius: "var(--r-lg)",
                                                    background: active ? opt.bg : "var(--c-surface)",
                                                    cursor: "pointer", transition: "all var(--t)",
                                                    display: "flex", flexDirection: "column", alignItems: "center", gap: "3px",
                                                }}
                                            >
                                                <span style={{ fontSize: "20px", color: active ? opt.color : "var(--c-text-3)", lineHeight: 1 }}>{opt.icon}</span>
                                                <span style={{ fontSize: "11.5px", fontWeight: "600", color: active ? opt.color : "var(--c-text-2)" }}>{opt.label}</span>
                                            </button>
                                        );
                                    })}
                                </div>
                                {adjustForm.movement_type === "adjustment" && (
                                    <p style={{ fontSize: "11.5px", color: "var(--c-text-3)", marginTop: "6px" }}>
                                        El ajuste establece el stock directamente al valor indicado.
                                    </p>
                                )}
                            </div>

                            {(() => {
                                const adjPres = adjustingProduct.presentation || {};
                                const adjUnit = adjustingProduct.base_unit || adjPres.base_unit_display || adjPres.base_unit || "";
                                const adjCf = parseFloat(adjPres.conversion_factor ?? 1) || 1;
                                return (
                                    <div className="form-group">
                                        <label className="form-label">
                                            {adjustForm.movement_type === "adjustment"
                                                ? `NUEVO STOCK (en ${adjUnit || "unidades"}) *`
                                                : `CANTIDAD (en ${adjCf > 1 ? `paquetes → ${adjUnit}` : adjUnit || "unidades"}) *`}
                                        </label>
                                        <div style={{ display: "flex", alignItems: "center", gap: "7px" }}>
                                            <button
                                                type="button" className="btn btn-secondary btn-md"
                                                style={{ width: "38px", padding: 0, fontSize: "20px", fontWeight: "400", flexShrink: 0 }}
                                                onClick={() => setAdjustForm(f => ({ ...f, quantity: Math.max(1, parseFloat(f.quantity) - 1) }))}
                                            >−</button>
                                            <input
                                                type="number" step="1" min="1" className="input"
                                                style={{ textAlign: "center", fontWeight: "700", fontSize: "16px" }}
                                                value={adjustForm.quantity}
                                                onChange={e => setAdjustForm({ ...adjustForm, quantity: e.target.value })}
                                            />
                                            <button
                                                type="button" className="btn btn-secondary btn-md"
                                                style={{ width: "38px", padding: 0, fontSize: "20px", fontWeight: "400", flexShrink: 0 }}
                                                onClick={() => setAdjustForm(f => ({ ...f, quantity: parseFloat(f.quantity) + 1 }))}
                                            >+</button>
                                        </div>
                                        {adjCf > 1 && adjustForm.quantity > 0 && (
                                            <p style={{ fontSize: "11.5px", color: "var(--c-text-3)", marginTop: "5px" }}>
                                                {parseFloat(adjustForm.quantity)} paquete{parseFloat(adjustForm.quantity) !== 1 ? "s" : ""} = {parseFloat(adjustForm.quantity) * adjCf} {adjUnit}
                                            </p>
                                        )}
                                    </div>
                                );
                            })()}

                            <div className="form-group" style={{ marginBottom: 0 }}>
                                <label className="form-label">MOTIVO</label>
                                <input
                                    type="text" className="input"
                                    value={adjustForm.reason}
                                    onChange={e => setAdjustForm({ ...adjustForm, reason: e.target.value })}
                                    placeholder="Ej: Compra a proveedor, vencimiento, conteo físico..."
                                />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleAdjust} disabled={saving}>
                                {saving ? "Aplicando..." : "Confirmar ajuste"}
                            </button>
                            <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={closeAdjustModal}>
                                Cancelar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* ── Modal: Entrada rápida de stock ── */}
            {stockEntryOpen && (
                <StockEntryModal
                    products={products}
                    onClose={() => setStockEntryOpen(false)}
                    onSaved={loadAll}
                    onCreateNew={() => openWizardCreate()}
                />
            )}
        </div>
    );
};

export default Inventory;
