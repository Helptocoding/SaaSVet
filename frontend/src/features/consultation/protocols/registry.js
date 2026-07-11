import { generalProtocol } from "./general";
import { vaccineProtocol } from "./vaccine";

/**
 * Registry de protocolos clínicos por `consultation_type`.
 *
 * Devuelve el protocolo que activa una sección clínica especializada, o `null`.
 * Un protocolo nuevo (cirugía, urgencia, desparasitación…) = nueva carpeta en ./
 * + una entrada aquí.
 *
 * No es un motor genérico de plantillas (schema-driven): cada protocolo es un
 * módulo de código con su propia UI, validación y registro de dominio.
 */
const PROTOCOLS = {
  general: generalProtocol,
  vaccine: vaccineProtocol,
};

export const protocolFor = (type) => PROTOCOLS[type] || null;
