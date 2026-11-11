import { createContext, useContext } from "react";

// Contexto y hook de activación. El Provider vive en ActivationProvider.jsx.
export const ActivationContext = createContext({
  activation: null,
  loading: true,
  refetch: () => {},
});

export function useActivationContext() {
  return useContext(ActivationContext);
}
