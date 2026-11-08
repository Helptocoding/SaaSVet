// entityConfig.js — Configuración por entity_type del wizard de importación.
//
// Un solo wizard (mismo flujo/CSS); este archivo concentra SOLO las diferencias
// de dominio: textos, columnas de tabla, tarjetas de resumen, ayudas por campo
// y CTA final. Defaults = owner_pet ⇒ los componentes sin config explícita se
// comportan exactamente como antes (cero regresión).
//
// Backend: FIELD_CATALOG[entity_type] es la fuente de verdad de los targets;
// estas configs solo presentan. No inventar campos aquí.

export const OWNER_PET_CONFIG = {
    key: "owner_pet",

    // Paso 1 — Upload / encabezado del wizard
    pageTitle: "Importar clientes y mascotas",
    pageSubtitle: "Migra tus clientes y sus mascotas desde un archivo de Excel o CSV.",
    uploadTitle: "Sube tu archivo de clientes y mascotas",
    uploadHint:
        "Acepta Excel (.xlsx) o CSV (.csv). La primera fila debe contener los " +
        "encabezados de cada columna. En el siguiente paso eliges qué columna " +
        "corresponde a cada dato.",
    uploadFooterLead: "clientes y sus mascotas",

    // Sustantivos para pills/confirmaciones
    nouns: { primary: "mascota", primaryPlural: "mascotas", person: "cliente", personPlural: "clientes" },
    createdTotalKey: "created_pets",
    createdSecondaryKeys: ["created_owners", "reused_owners"], // pill "asociadas a N clientes"
    showPersonsPill: true,

    // Tabla "SE CREARÁN"
    previewColumns: [
        { key: "pet_name", label: "Mascota" },
        { key: "owner_name", label: "Cliente" },
        { key: "pet_species", label: "Especie", cellClass: "cellSpecies" },
        { key: "owner_phone", label: "Teléfono", cellClass: "cellMono" },
    ],

    // Tarjetas de conflicto (incoming/existing)
    conflict: {
        incomingPrimaryKey: "pet_name",
        incomingSecondaryKey: "owner_name",
        existingPrimary: (existing) => existing.pet_name,
        existingSecondary: (existing) => existing.owner_name,
        link: (conflict) => `/pets/${conflict.existing?.public_id}`,
        linkText: "Ver paciente",
        highText: "Parece el mismo paciente.",
        cardUncertainText: "El número de expediente ya pertenece a otro paciente.",
        uncertainTitle: (n) => `Mismo expediente con datos diferentes (${n})`,
        uncertainDesc:
            "El número de expediente ya pertenece a otro paciente con datos distintos. " +
            "Puede pasar si importas información de otra clínica o el sistema anterior " +
            "reinició numeraciones.",
    },

    skippedCardFields: [
        { key: "pet_name", label: "Mascota" },
        { key: "owner_name", label: "Cliente" },
    ],

    // Ayudas de errores bloqueantes ("Qué hacer")
    blockingActions: {
        "pet.name": (labels) =>
            `Agrega el nombre en la columna asignada como ${labels["pet.name"] || "Nombre de la mascota"}.`,
        "owner.name": (labels) =>
            `Agrega el nombre en la columna asignada como ${labels["owner.name"] || "Nombre del cliente"}.`,
        "owner.phone": () => "Corrige el teléfono: deben ser 10 dígitos, o deja la celda vacía.",
    },
    csvActions: {
        "pet.name": "Agrega el nombre de la mascota en la columna correspondiente de tu archivo.",
        "owner.name": "Agrega el nombre del cliente en la columna correspondiente de tu archivo.",
        "owner.phone": "Corrige el teléfono: deben ser exactamente 10 dígitos, o deja la celda vacía.",
        "pet.species": "La especie no se reconoció. Puedes completarla después desde la ficha.",
        "pet.birth_date": "La fecha no tiene un formato válido. Puedes corregirla o completarla después.",
    },

    // Resultado (paso 4)
    summaryCards: [
        { valueKey: "created_owners", label: "Clientes creados", tone: "success" },
        { valueKey: "created_pets", label: "Mascotas creadas", tone: "success" },
        { valueKey: "reused_owners", label: "Clientes reutilizados", tone: "" },
        { valueKey: "skipped_duplicates", label: "Duplicados omitidos", tone: "warning" },
        { valueKey: "error_rows", label: "Filas con error", tone: "danger" },
    ],
    incompleteLabels: {
        "pet.species": "mascotas sin especie",
        "pet.birth_date": "mascotas sin fecha de nacimiento",
        "owner.phone": "clientes sin teléfono",
    },
    incompleteOrder: ["pet.species", "pet.birth_date", "owner.phone"],
    doneCta: { path: "/pets", label: "Ver clientes y mascotas" },
};

export const INVENTORY_CONFIG = {
    key: "inventory",

    pageTitle: "Importar inventario",
    pageSubtitle: "Migra tu catálogo de productos desde un archivo de Excel o CSV.",
    uploadTitle: "Sube tu archivo de productos",
    uploadHint:
        "Acepta Excel (.xlsx) o CSV (.csv). La primera fila debe contener los " +
        "encabezados de cada columna. En el siguiente paso eliges qué columna " +
        "corresponde a cada dato.",
    uploadFooterLead: "tu catálogo de productos",

    nouns: { primary: "producto", primaryPlural: "productos", person: null, personPlural: null },
    createdTotalKey: "created_products",
    createdSecondaryKeys: [],
    showPersonsPill: false,

    previewColumns: [
        { key: "name", label: "Producto" },
        { key: "internal_code", label: "Código", cellClass: "cellMono" },
        { key: "category", label: "Categoría" },
        { key: "base_unit", label: "Unidad" },
        { key: "stock", label: "Existencia", cellClass: "cellMono" },
        { key: "sale_price", label: "Precio", cellClass: "cellMono" },
    ],

    conflict: {
        incomingPrimaryKey: "name",
        incomingSecondaryKey: "internal_code",
        existingPrimary: (existing) => existing.name || existing.product_name,
        existingSecondary: () => "",
        link: null, // el detalle de producto no tiene ruta pública por public_id hoy
        linkText: "",
        highText: "Parece el mismo producto.",
        // Sin texto fijo: un producto por revisar coincide por código o por nombre, y la
        // tarjeta muestra el motivo concreto que envía el servidor.
        cardUncertainText: null,
        uncertainTitle: (n) => `Posibles duplicados por revisar (${n})`,
        uncertainDesc:
            "Coinciden con un producto registrado por código interno o por nombre, pero los datos " +
            "no confirman que sea el mismo. Revisa cada fila en el detalle completo: corrige el " +
            "código o el nombre en tu archivo y vuelve a mapear para importarlas, o confirma " +
            "sabiendo que se omitirán.",
    },

    skippedCardFields: [
        { key: "name", label: "Producto" },
        { key: "internal_code", label: "Código" },
    ],

    blockingActions: {
        "product.name": (labels) =>
            `Agrega el nombre en la columna asignada como ${labels["product.name"] || "Nombre del producto"}.`,
        "presentation.sale_price": () =>
            "Corrige el precio de venta: debe ser un número mayor a 0 (acepta $ y coma decimal).",
        "product.stock": () => "La existencia debe ser un número mayor o igual a 0.",
        "presentation.conversion_factor": () => "El factor de conversión debe ser mayor a 0.",
        "product.requires_prescription": () => 'Usa Sí o No en la columna de receta.',
    },
    csvActions: {
        "product.name": "Agrega el nombre del producto en la columna correspondiente de tu archivo.",
        "presentation.sale_price": "Escribe un número mayor a 0 (ej. 250.50). Sin precio no se puede importar.",
        "product.stock": "Escribe un número mayor o igual a 0, o deja la celda vacía.",
        "presentation.conversion_factor": "Escribe cuántas unidades base trae la presentación (ej. 3).",
        "product.requires_prescription": 'Usa Sí o No.',
    },

    summaryCards: [
        { valueKey: "created_products", label: "Productos creados", tone: "success" },
        { valueKey: "created_presentations", label: "Presentaciones creadas", tone: "success" },
        { valueKey: "initial_stock_movements", label: "Con stock inicial", tone: "" },
        // El importador de inventario no tiene duplicados exactos: todo choque con un
        // producto registrado (código, nombre o código de barras) se omite como conflicto.
        { valueKey: "skipped_conflicts", label: "Posibles duplicados omitidos", tone: "warning" },
        { valueKey: "error_rows", label: "Filas con error", tone: "danger" },
    ],
    incompleteLabels: {
        "product.category": "productos con categoría genérica (“Otro”)",
        "product.base_unit": "productos con unidad genérica (“Unidad”)",
    },
    incompleteOrder: ["product.category", "product.base_unit"],
    doneCta: { path: "/inventory", label: "Ver inventario" },
};

export const ENTITY_CONFIGS = {
    owner_pet: OWNER_PET_CONFIG,
    inventory: INVENTORY_CONFIG,
};

export const getEntityConfig = (entityType) =>
    ENTITY_CONFIGS[entityType] || OWNER_PET_CONFIG;
