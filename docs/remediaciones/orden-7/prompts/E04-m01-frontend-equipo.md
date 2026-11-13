# E04 — M01: capturar la cédula en Equipo

Primero lee y aplica `docs/remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md`. Lee también `docs/modules/frontend.md` (contratos de formularios, errores y permisos).

## Objetivo

La pantalla de Equipo (`/staff`) captura la cédula profesional al dar de alta un miembro (obligatoria para `VET`), la muestra en la tabla y permite editarla, junto con la especialidad, con el PATCH de E02. El botón Editar depende de `can("staff.update")`.

Es el único cambio de frontend del orden.

## Precondición

`git log --oneline -1` muestra el commit de E03 (`feat(medical-records): require signer license to close and prescribe (order 7, M01)`). Si no, `BLOQUEADA`.

## Archivos permitidos

- `frontend/src/api/staff.js`
- `frontend/src/pages/staff.jsx`
- `frontend/src/pages/staff.test.jsx`
- `docs/remediaciones/orden-7/MATRIZ.md` y `docs/remediaciones/orden-7/EVIDENCIA.md`

## Contexto

- La validación del cliente (`licenseError`) repite la del backend solo para avisar antes de enviar: vacía es error para `VET`; con valor, 5 a 10 dígitos. El backend sigue siendo la autoridad.
- `staff.jsx` ya decide sus acciones con `user?.role === "ADMIN"`, contra la regla de `can()`. No se corrige aquí: el botón nuevo usa `can("staff.update")` y el resto queda como estaba.
- La prueba usa el módulo real `api/staff` y sustituye solo el cliente HTTP, como `pets.edit.test.jsx`. El mock de `useAuth` devuelve un `user` **estable**: la página recarga Equipo en un `useEffect` que depende de `user`, y un objeto nuevo en cada render la recargaría sin fin y desmontaría el modal a mitad de la escritura.
- Los campos nuevos llevan `id` y `htmlFor` para poder encontrarlos por su etiqueta.

## Cambios

Aplícalos en este orden.

### Cambio 1 — `frontend/src/pages/staff.test.jsx`

Archivo nuevo. Créalo con este contenido exacto:

```jsx
/**
 * Equipo: cédula profesional (M01, orden 7). Alta de VET con cédula obligatoria
 * y edición por PATCH /staff/<public_id>/ con solo especialidad y cédula. Se usa
 * el módulo real `api/staff`; solo se sustituye el cliente HTTP.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("../api/client", () => ({
    default: { get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a) },
}));
let granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
const can = (code) => granted.has(code);
// Objeto estable: la página recarga Equipo cuando cambia `user` (useEffect).
const ADMIN = { role: "ADMIN" };
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ user: ADMIN, initializing: false, can }),
}));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import { toast } from "sonner";
import Staff from "./staff";

const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET",
    specialty: "Cirugía", license_number: "1234567", is_active: true,
};

beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
    get.mockResolvedValue({ data: [VET] });
    post.mockResolvedValue({ data: VET });
    patch.mockResolvedValue({ data: VET });
});

describe("Equipo: cédula profesional", () => {
    it("muestra la cédula en la tabla", async () => {
        render(<Staff />);
        expect(await screen.findByText("1234567")).toBeInTheDocument();
    });

    it("editar envía PATCH con solo especialidad y cédula sobre el public_id", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        const license = screen.getByLabelText(/cédula profesional/i);
        await user.clear(license);
        await user.type(license, " 7654321 ");
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
            specialty: "Cirugía",
            license_number: "7654321",
        });
    });

    it("no guarda a un veterinario sin cédula", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        await user.clear(screen.getByLabelText(/cédula profesional/i));
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        expect(patch).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith("La cédula profesional es obligatoria para veterinarios");
    });

    it("el alta de un veterinario exige cédula con formato válido", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "diego");
        await user.type(screen.getByPlaceholderText("Juan"), "Diego");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "diego@vet.mx");
        await user.type(screen.getByPlaceholderText("Mínimo 6 caracteres"), "Segura123");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenLastCalledWith("La cédula profesional es obligatoria para veterinarios");

        const license = screen.getByLabelText(/cédula profesional/i);
        await user.type(license, "12a45");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenLastCalledWith("La cédula profesional debe tener solo dígitos, entre 5 y 10");

        await user.clear(license);
        await user.type(license, "2468024");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][0]).toBe("staff/create/");
        expect(post.mock.calls[0][1]).toMatchObject({ role: "VET", license_number: "2468024" });
    });

    it("sin staff.update no ofrece editar", async () => {
        granted.delete("staff.update");
        render(<Staff />);
        await screen.findByText("1234567");
        expect(screen.queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
    });
});
```

### Cambio 2 — `frontend/src/api/staff.js`

Texto actual:

```js
export const deactivateStaff = async (id) => {
```

Texto nuevo:

```js
/**
 * Edita especialidad y cédula profesional de un miembro (M01, orden 7).
 * El backend rechaza cualquier otra clave.
 */
export const updateStaff = async (publicId, data) => {
    const res = await api.patch(`staff/${publicId}/`, data);
    return res.data;
};

export const deactivateStaff = async (id) => {
```

### Cambio 3 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
import { getStaff, createStaff, deactivateStaff, resetStaffPassword } from "../api/staff";
```

Texto nuevo:

```jsx
import { getStaff, createStaff, updateStaff, deactivateStaff, resetStaffPassword } from "../api/staff";
```

### Cambio 4 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
    role: "VET",
    specialty: ""
};
```

Texto nuevo:

```jsx
    role: "VET",
    specialty: "",
    license_number: ""
};

// M01 (orden 7): cédula profesional, solo dígitos (5 a 10). Obligatoria para VET.
const LICENSE_RE = /^\d{5,10}$/;
const LICENSE_REQUIRED = "La cédula profesional es obligatoria para veterinarios";
const LICENSE_FORMAT = "La cédula profesional debe tener solo dígitos, entre 5 y 10";

function licenseError(role, value) {
    const license = value.trim();
    if (!license) return role === "VET" ? LICENSE_REQUIRED : null;
    return LICENSE_RE.test(license) ? null : LICENSE_FORMAT;
}
```

### Cambio 5 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
    const { user, initializing } = useAuth();
    const confirm = useConfirm();
    const isAdmin = user?.role === "ADMIN";
```

Texto nuevo:

```jsx
    const { user, initializing, can } = useAuth();
    const confirm = useConfirm();
    const isAdmin = user?.role === "ADMIN";
    const canEdit = can("staff.update");
```

### Cambio 6 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
    const [form, setForm] = useState(EMPTY_FORM);
```

Texto nuevo:

```jsx
    const [form, setForm] = useState(EMPTY_FORM);
    // Edición de especialidad y cédula: { member, specialty, license_number } | null
    const [editing, setEditing] = useState(null);
```

### Cambio 7 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
        if (!/[0-9]/.test(form.password)) { toast.error("La contraseña debe contener al menos un número"); return; }

        setSaving(true);
        try {
            await toast.promise(createStaff(form), {
```

Texto nuevo:

```jsx
        if (!/[0-9]/.test(form.password)) { toast.error("La contraseña debe contener al menos un número"); return; }
        const licenseProblem = licenseError(form.role, form.license_number);
        if (licenseProblem) { toast.error(licenseProblem); return; }

        setSaving(true);
        try {
            await toast.promise(createStaff({ ...form, license_number: form.license_number.trim() }), {
```

### Cambio 8 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
    const closeModal = () => {
        setForm(EMPTY_FORM);
        setShowModal(false);
    };
```

Texto nuevo:

```jsx
    const closeModal = () => {
        setForm(EMPTY_FORM);
        setShowModal(false);
    };

    const openEdit = (member) => {
        setEditing({
            member,
            specialty: member.specialty || "",
            license_number: member.license_number || "",
        });
    };

    const handleEditSave = async () => {
        if (!editing) return;
        const licenseProblem = licenseError(editing.member.role, editing.license_number);
        if (licenseProblem) { toast.error(licenseProblem); return; }

        setSaving(true);
        try {
            await toast.promise(
                updateStaff(editing.member.public_id, {
                    specialty: editing.specialty.trim(),
                    license_number: editing.license_number.trim(),
                }),
                {
                    loading: "Guardando...",
                    success: "Miembro actualizado",
                    error: (err) => apiError(err, "Error al guardar"),
                },
            );
            setEditing(null);
            fetchStaff();
        } catch {
            // El modal queda abierto: el toast ya mostró el error.
        } finally {
            setSaving(false);
        }
    };
```

### Cambio 9 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
                                <th>Especialidad</th>
                                {isAdmin && <th></th>}
```

Texto nuevo:

```jsx
                                <th>Especialidad</th>
                                <th>Cédula</th>
                                {isAdmin && <th></th>}
```

### Cambio 10 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
                                    <td style={{ color: "var(--c-text-3)" }}>{member.specialty || "—"}</td>
                                    {isAdmin && (
                                        <td>
                                            <div style={{ display: "flex", gap: "6px" }}>
```

Texto nuevo:

```jsx
                                    <td style={{ color: "var(--c-text-3)" }}>{member.specialty || "—"}</td>
                                    <td style={{ color: "var(--c-text-3)", fontFamily: "var(--font-mono)" }}>{member.license_number || "—"}</td>
                                    {isAdmin && (
                                        <td>
                                            <div style={{ display: "flex", gap: "6px" }}>
                                                {canEdit && member.role !== "ADMIN_SAAS" && (
                                                    <button
                                                        className="btn btn-secondary btn-sm"
                                                        onClick={() => openEdit(member)}
                                                        title="Editar"
                                                    >
                                                        <Icon.Edit s={14} />
                                                    </button>
                                                )}
```

### Cambio 11 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
                                    <div className="form-group" style={{ gridColumn: "1 / -1" }}>
                                        <label className="form-label">ESPECIALIDAD</label>
                                        <input
                                            className="input"
                                            placeholder="Cirugía, Dermatología..."
                                            value={form.specialty}
                                            onChange={e => setForm({ ...form, specialty: e.target.value })}
                                        />
                                    </div>
```

Texto nuevo:

```jsx
                                    <div className="form-group">
                                        <label className="form-label">ESPECIALIDAD</label>
                                        <input
                                            className="input"
                                            placeholder="Cirugía, Dermatología..."
                                            value={form.specialty}
                                            onChange={e => setForm({ ...form, specialty: e.target.value })}
                                        />
                                    </div>
                                    <div className="form-group">
                                        <label className="form-label" htmlFor="create-license">
                                            CÉDULA PROFESIONAL{form.role === "VET" ? " *" : ""}
                                        </label>
                                        <input
                                            id="create-license"
                                            className="input"
                                            inputMode="numeric"
                                            placeholder="Solo dígitos"
                                            value={form.license_number}
                                            onChange={e => setForm({ ...form, license_number: e.target.value })}
                                        />
                                    </div>
```

### Cambio 12 — `frontend/src/pages/staff.jsx`

Texto actual:

```jsx
            {/* Modal Nuevo Miembro */}
```

Texto nuevo:

```jsx
            {/* Modal Editar Miembro — especialidad y cédula (M01, orden 7) */}
            {editing && (
                <div className="modal-overlay">
                    <div className="modal modal-sm">
                        <div className="modal-header">
                            <h3>Editar miembro</h3>
                            <button className="modal-close" onClick={() => setEditing(null)} disabled={saving}><Icon.X s={16} /></button>
                        </div>
                        <div className="modal-body">
                            <p style={{ fontWeight: "600", marginBottom: "12px" }}>
                                {editing.member.first_name} {editing.member.last_name}
                                <span style={{ color: "var(--c-text-3)", fontWeight: "400" }}> · {ROLE_LABELS[editing.member.role] || editing.member.role}</span>
                            </p>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-specialty">ESPECIALIDAD</label>
                                <input
                                    id="edit-specialty"
                                    className="input"
                                    placeholder="Cirugía, Dermatología..."
                                    value={editing.specialty}
                                    onChange={e => setEditing({ ...editing, specialty: e.target.value })}
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label" htmlFor="edit-license">
                                    CÉDULA PROFESIONAL{editing.member.role === "VET" ? " *" : ""}
                                </label>
                                <input
                                    id="edit-license"
                                    className="input"
                                    inputMode="numeric"
                                    placeholder="Solo dígitos"
                                    value={editing.license_number}
                                    onChange={e => setEditing({ ...editing, license_number: e.target.value })}
                                />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-primary btn-md" style={{ flex: 1 }} onClick={handleEditSave} disabled={saving}>
                                {saving ? "Guardando..." : "Guardar"}
                            </button>
                            <button className="btn btn-secondary btn-md" style={{ flex: 1 }} onClick={() => setEditing(null)} disabled={saving}>
                                Cancelar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Modal Nuevo Miembro */}
```


## Verificación

Desde `frontend/`:

```bash
cd /c/Users/LAP/Desktop/VeterinariaSaaS/frontend
VITE_API_URL=http://127.0.0.1:8000/api pnpm exec vitest run src/pages/staff.test.jsx 2>&1 | grep -E "Test Files|Tests  |×"
VITE_API_URL=http://127.0.0.1:8000/api pnpm run test 2>&1 | grep -E "Test Files|Tests  |FAIL" | head -20
pnpm run lint > /dev/null 2>&1; echo "lint exit=$?"
VITE_API_URL=http://127.0.0.1:8000/api pnpm run build > /dev/null 2>&1; echo "build exit=$?"
pnpm run smoke:urls 2>&1 | tail -2
```

Esperado:

- `staff.test.jsx`: `5 passed`.
- Suite completa: **79 archivos y 851 pruebas** pasan.
- `lint exit=0`, `build exit=0` y `url_construction.cjs — OK`.

Si `lint` falla, ejecuta `pnpm run lint 2>&1 | tail -30` para ver el motivo.

## Cierre

- `MATRIZ.md`: M01 pasa a `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, con entregas E02–E04, los tres commits y `EVIDENCIA.md §E02–E04`. Completa la fila E04 del avance.
- `EVIDENCIA.md`: sección E04 con las salidas. Límite: sin prueba manual en navegador; la cubren las pruebas de Vitest con el cliente HTTP sustituido.

Commit: `feat(frontend): capture professional license in staff page (order 7, M01)`.
