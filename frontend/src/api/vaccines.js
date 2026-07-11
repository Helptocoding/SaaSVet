import api from "./client";

// Solo lectura: el VaccineRecord se crea server-side al finalizar la consulta
// (apply_consultation_draft_on_close), no desde el frontend. `pet` = public_id.
export const getVaccines = ({ pet }) =>
  api.get("vaccines/", { params: { pet } }).then((r) => r.data);
