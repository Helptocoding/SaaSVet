// Vitest global setup — jest-dom matchers (toBeInTheDocument, toHaveTextContent, …).
// Cargado vía vite.config.js `test.setupFiles`. No agregar mocks globales aquí:
// los mocks viven por archivo de test para mantener el aislamiento explícito.
import '@testing-library/jest-dom/vitest';
