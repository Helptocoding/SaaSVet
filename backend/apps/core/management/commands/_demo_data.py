"""
P1-8 — Datasets estáticos para `seed_demo_clinic`.

Solo DATOS (sin lógica). Separado del comando para que el orquestador quede
legible. Todo en es-MX, realista para una clínica veterinaria.

Las claves determinísticas (`legacy_id`, `internal_code`) hacen el seed
idempotente: re-correr usa get_or_create sobre ellas, no duplica.
"""

# --- Organización demo ---------------------------------------------------
DEMO_ORG_NAME = "Clínica Demo SaaSlyVet"
DEMO_TIMEZONE = "America/Mexico_City"
DEMO_TAX_RATE = "0.16"  # IVA 16% visible en cobros

# --- Usuarios demo (3, P1-8 ajustado) ------------------------------------
# password único para beta privada (cumple validators: ≥8, mayúscula, número).
DEMO_PASSWORD = "DemoSaaSlyVet2026"
DEMO_USERS = [
    {
        "username": "demo-admin@saaslyvet.com",
        "email": "demo-admin@saaslyvet.com",
        "first_name": "Laura",
        "last_name": "Hernández",
        "role": "ADMIN",
    },
    {
        "username": "demo-vet@saaslyvet.com",
        "email": "demo-vet@saaslyvet.com",
        "first_name": "Diego",
        "last_name": "Ramírez",
        "role": "VET",
        "specialty": "Medicina general",
    },
    {
        "username": "demo-recepcion@saaslyvet.com",
        "email": "demo-recepcion@saaslyvet.com",
        "first_name": "Sofía",
        "last_name": "Torres",
        "role": "ASSISTANT",
    },
]

# --- Servicios (base_price > 0) ------------------------------------------
DEMO_SERVICES = [
    {"name": "Consulta general", "base_price": "350.00"},
    {"name": "Vacunación", "base_price": "280.00"},
    {"name": "Desparasitación", "base_price": "180.00"},
    {"name": "Baño y estética", "base_price": "320.00"},
    {"name": "Cirugía menor", "base_price": "1500.00"},
    {"name": "Radiografía", "base_price": "650.00"},
    {"name": "Hospitalización (día)", "base_price": "900.00"},
    {"name": "Consulta de urgencia", "base_price": "550.00"},
]

# --- Productos + presentación inicial -------------------------------------
# category: medication|food|accessory|other
# base_unit: tablet|capsule|ml|vial|piece|bag|bottle|tube|kg|g|unit
# initial_stock_base: existencia inicial EN UNIDADES BASE (apply_stock_movement).
# min_stock_base: bajo este valor el producto sale como "stock crítico".
DEMO_PRODUCTS = [
    # --- Medicamentos (algunos requires_prescription) ---
    {"name": "Amoxicilina 500mg", "category": "medication", "requires_prescription": True,
     "base_unit": "tablet", "min_stock_base": "20", "initial_stock_base": "120",
     "presentation": {"name": "Tableta", "sale_price": "18.00", "conversion_factor": "1"}},
    {"name": "Meloxicam 1.5mg/ml", "category": "medication", "requires_prescription": True,
     "base_unit": "ml", "min_stock_base": "50", "initial_stock_base": "200",
     "presentation": {"name": "Frasco 10ml", "sale_price": "240.00", "conversion_factor": "10"}},
    {"name": "Antiparasitario interno", "category": "medication", "requires_prescription": False,
     "base_unit": "tablet", "min_stock_base": "30", "initial_stock_base": "150",
     "presentation": {"name": "Tableta", "sale_price": "45.00", "conversion_factor": "1"}},
    {"name": "Antipulgas pipeta", "category": "medication", "requires_prescription": False,
     "base_unit": "piece", "min_stock_base": "15", "initial_stock_base": "60",
     "presentation": {"name": "Pipeta", "sale_price": "180.00", "conversion_factor": "1"}},
    {"name": "Vacuna múltiple canina", "category": "medication", "requires_prescription": True,
     "base_unit": "vial", "min_stock_base": "10", "initial_stock_base": "30",
     "presentation": {"name": "Vial", "sale_price": "260.00", "conversion_factor": "1"}},
    {"name": "Vacuna triple felina", "category": "medication", "requires_prescription": True,
     "base_unit": "vial", "min_stock_base": "10", "initial_stock_base": "25",
     "presentation": {"name": "Vial", "sale_price": "280.00", "conversion_factor": "1"}},
    {"name": "Suero fisiológico 250ml", "category": "medication", "requires_prescription": False,
     "base_unit": "bottle", "min_stock_base": "8", "initial_stock_base": "30",
     "presentation": {"name": "Frasco 250ml", "sale_price": "75.00", "conversion_factor": "1"}},
    {"name": "Analgésico inyectable", "category": "medication", "requires_prescription": True,
     "base_unit": "ml", "min_stock_base": "40", "initial_stock_base": "400",
     "presentation": {"name": "Frasco 20ml", "sale_price": "320.00", "conversion_factor": "20"}},
    # --- Alimento ---
    {"name": "Alimento perro adulto 15kg", "category": "food", "requires_prescription": False,
     "base_unit": "bag", "min_stock_base": "5", "initial_stock_base": "18",
     "presentation": {"name": "Bulto 15kg", "sale_price": "780.00", "conversion_factor": "1"}},
    {"name": "Alimento gato adulto 3kg", "category": "food", "requires_prescription": False,
     "base_unit": "bag", "min_stock_base": "6", "initial_stock_base": "22",
     "presentation": {"name": "Bolsa 3kg", "sale_price": "410.00", "conversion_factor": "1"}},
    {"name": "Alimento cachorro 4kg", "category": "food", "requires_prescription": False,
     "base_unit": "bag", "min_stock_base": "5", "initial_stock_base": "0",  # agotado (badge crítico)
     "presentation": {"name": "Bolsa 4kg", "sale_price": "520.00", "conversion_factor": "1"}},
    {"name": "Lata alimento húmedo", "category": "food", "requires_prescription": False,
     "base_unit": "piece", "min_stock_base": "24", "initial_stock_base": "96",
     "presentation": {"name": "Lata 156g", "sale_price": "32.00", "conversion_factor": "1"}},
    # --- Accesorios ---
    {"name": "Shampoo medicado", "category": "accessory", "requires_prescription": False,
     "base_unit": "bottle", "min_stock_base": "6", "initial_stock_base": "20",
     "presentation": {"name": "Frasco 350ml", "sale_price": "150.00", "conversion_factor": "1"}},
    {"name": "Collar antipulgas", "category": "accessory", "requires_prescription": False,
     "base_unit": "piece", "min_stock_base": "10", "initial_stock_base": "40",
     "presentation": {"name": "Pieza", "sale_price": "220.00", "conversion_factor": "1"}},
    {"name": "Juguete mordedera", "category": "accessory", "requires_prescription": False,
     "base_unit": "piece", "min_stock_base": "8", "initial_stock_base": "35",
     "presentation": {"name": "Pieza", "sale_price": "95.00", "conversion_factor": "1"}},
    {"name": "Correa retráctil", "category": "accessory", "requires_prescription": False,
     "base_unit": "piece", "min_stock_base": "5", "initial_stock_base": "2",  # bajo min → crítico
     "presentation": {"name": "Pieza", "sale_price": "260.00", "conversion_factor": "1"}},
    {"name": "Arena sanitaria 5kg", "category": "other", "requires_prescription": False,
     "base_unit": "bag", "min_stock_base": "10", "initial_stock_base": "44",
     "presentation": {"name": "Bolsa 5kg", "sale_price": "130.00", "conversion_factor": "1"}},
    {"name": "Jeringa estéril 5ml", "category": "other", "requires_prescription": False,
     "base_unit": "piece", "min_stock_base": "50", "initial_stock_base": "300",
     "presentation": {"name": "Pieza", "sale_price": "12.00", "conversion_factor": "1"}},
]

# --- Clientes (40) --------------------------------------------------------
OWNER_NAMES = [
    "Ana Martínez", "Carlos Rodríguez", "María López", "José García", "Laura Sánchez",
    "Miguel Hernández", "Patricia Ramírez", "Jorge Flores", "Gabriela Torres", "Luis Gómez",
    "Verónica Díaz", "Roberto Cruz", "Adriana Morales", "Fernando Reyes", "Claudia Ortiz",
    "Ricardo Jiménez", "Mónica Vargas", "Eduardo Mendoza", "Alejandra Castillo", "Héctor Ruiz",
    "Daniela Romero", "Pablo Aguilar", "Sandra Guerrero", "Andrés Medina", "Karla Rojas",
    "Sergio Domínguez", "Lucía Núñez", "Raúl Herrera", "Diana Salazar", "Óscar Campos",
    "Brenda Vega", "Iván Fuentes", "Paola Ríos", "Manuel Cabrera", "Rosa Estrada",
    "Arturo León", "Cecilia Pacheco", "Emilio Cárdenas", "Natalia Soto", "Guillermo Ramos",
]

# --- Mascotas: nombres + razas por especie -------------------------------
PET_NAMES = [
    "Max", "Luna", "Rocky", "Bella", "Toby", "Nina", "Thor", "Kira", "Simba", "Maya",
    "Coco", "Lola", "Bruno", "Frida", "Zeus", "Canela", "Duque", "Mia", "Boby", "Pelusa",
    "Chester", "Manchas", "Negro", "Pulga", "Firulais", "Michi", "Garfield", "Copito",
    "Rambo", "Estrella", "Capitán", "Galleta", "Oso", "Princesa", "Pancho", "Nube",
    "Tomás", "Roma", "Lucas", "Donna", "Bingo", "Kiara", "Hachi", "Olivia", "Sol",
]

BREEDS = {
    "canino": ["Labrador", "Chihuahua", "Pastor Alemán", "Pug", "Schnauzer", "Poodle",
               "Golden Retriever", "Bulldog Francés", "Criollo", "Beagle"],
    "felino": ["Doméstico pelo corto", "Siamés", "Persa", "Maine Coon", "Angora", "Criollo"],
    "ave": ["Periquito", "Canario", "Agapornis"],
    "exótico": ["Conejo", "Hámster", "Tortuga"],
}
# distribución de especies (índice → especie) para ~65 mascotas
SPECIES_WEIGHTS = (["canino"] * 7) + (["felino"] * 3) + ["ave"] + ["exótico"]

# --- Plantillas clínicas (consultation_type, dx, treatment, servicio) -----
# servicio = nombre de DEMO_SERVICES; producto = nombre de DEMO_PRODUCTS|None
CONSULTATION_TEMPLATES = [
    {"type": "vaccine", "service": "Vacunación", "product": "Vacuna múltiple canina",
     "reason": "Vacunación anual",
     "diagnosis": "Paciente sano, esquema de vacunación al día.",
     "treatment": "", "vaccine": "Vacuna múltiple canina"},
    {"type": "general", "service": "Consulta general", "product": "Amoxicilina 500mg",
     "reason": "Gastroenteritis",
     "diagnosis": "Gastroenteritis aguda, probable causa alimentaria.",
     "treatment": "Amoxicilina 10 días, dieta blanda, hidratación.", "vaccine": None},
    {"type": "general", "service": "Consulta general", "product": "Antiparasitario interno",
     "reason": "Revisión anual",
     "diagnosis": "Examen físico sin alteraciones. Desparasitación de rutina.",
     "treatment": "Desparasitante oral dosis única.", "vaccine": None},
    {"type": "surgery", "service": "Cirugía menor", "product": "Analgésico inyectable",
     "reason": "Control post-cirugía",
     "diagnosis": "Evolución post-quirúrgica favorable, herida limpia.",
     "treatment": "Analgesia 5 días, curación y reposo.", "vaccine": None},
    {"type": "emergency", "service": "Consulta de urgencia", "product": "Suero fisiológico 250ml",
     "reason": "Cuadro de deshidratación",
     "diagnosis": "Deshidratación moderada secundaria a vómito.",
     "treatment": "Fluidoterapia, antiemético, observación.", "vaccine": None},
    {"type": "vaccine", "service": "Vacunación", "product": "Vacuna triple felina",
     "reason": "Vacunación felina",
     "diagnosis": "Felino sano, refuerzo aplicado.",
     "treatment": "", "vaccine": "Vacuna triple felina"},
    {"type": "general", "service": "Desparasitación", "product": "Antipulgas pipeta",
     "reason": "Control de pulgas",
     "diagnosis": "Infestación leve por pulgas.",
     "treatment": "Pipeta antipulgas, repetir en 30 días.", "vaccine": None},
]
