import { generalProtocol } from "./general";
import { vaccineProtocol } from "./vaccine";
import { surgeryProtocol } from "./surgery";
import { emergencyProtocol } from "./emergency";

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
  surgery: surgeryProtocol,
  emergency: emergencyProtocol,
};

export const protocolFor = (type) => PROTOCOLS[type] || null;
