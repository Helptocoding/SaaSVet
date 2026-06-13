export const DEMO_KEY = "inventory_demo_seen";

export const DEMO_PRODUCT = {
    name: "Jeringa 5ml",
    category: "accessory",
    internal_code: "",
    description: "",
    requires_prescription: false,
    min_stock: 0,
};

export const DEMO_STOCK = {
    qty: "50",
    countUnit: "caja",
    dividesCount: "100",
    dividesUnit: "piece",
};

export const DEMO_SALES = [
    { sale_price: "5", purchase_price: "2.50" },
    { sale_price: "400", purchase_price: "250" },
];

export const TOUR_STEPS = [
    {
        target: "[data-demo='mode-selector']",
        title: "¿Cómo se vende este producto?",
        body: "La mayoría de productos usan Producto normal:\n  Shampoo, collar, alimento cerrado, medicamento\n\nUsa Varias formas de venta solo cuando el mismo\nproducto puede venderse en diferentes cantidades.\n  Ej: Caja de jeringas → vender jeringa suelta\n       o caja completa (mismo inventario)\n\n→ Para este ejemplo: Varias formas de venta",
    },
    {
        target: "[data-demo='product-name']",
        title: "¿Qué producto es?",
        body: "Escribe el nombre tal como lo conoces.\n\nNo importa si lo compras en cajas o suelto.\nAhora solo decimos qué producto es.\n\n→ Autollenando: \"Jeringa 5ml\"",
    },
    {
        target: "[data-demo='stock-section']",
        title: "¿Cuánto tienes y cómo se divide?",
        body: "Indica cuánto tienes, en qué unidad lo cuentas\ny cuántas sub-unidades tiene cada contenedor.\n\nEjemplo:\n50 cajas, cada caja contiene 100 piezas\n→ 5000 piezas disponibles\n\n→ Autollenando: 50 Cajas, 100 piezas/caja",
    },
    {
        target: "[data-demo='sale-0']",
        title: "Primera forma de venta (unidad suelta)",
        body: "La primera forma vende la unidad más pequeña.\nCada venta descuenta 1 pieza del inventario.\n\nEjemplo: 1 jeringa a $5.\n\n→ Autollenando: $5",
    },
    {
        target: "[data-demo='sale-1']",
        title: "Segunda forma de venta (caja completa)",
        body: "El nombre y la cantidad ya se llenaron\nautomáticamente desde lo que indicaste arriba.\n\nSolo agrega el precio.\n\nEjemplo: Caja completa (100 piezas) a $400.\n\n→ Autollenando: $400",
    },
    {
        target: null,
        title: "¡Listo!",
        body: "Jeringa 5ml\n\nInventario: 5000 piezas disponibles\n  (50 cajas × 100 piezas)\n\nFormas de venta:\n  ✓ Pieza → descuenta 1 pieza → $5\n  ✓ Caja → descuenta 100 piezas → $400\n\nCada venta actualiza el inventario automáticamente.",
    },
];
