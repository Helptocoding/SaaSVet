import { createContext, useContext } from "react";

// Context + hook for the confirm-dialog system. Kept in its own module (not in
// ConfirmDialog.jsx) so that file can export ONLY React components and stay
// fast-refresh friendly (react-refresh/only-export-components).
//
// The Provider lives in ConfirmDialog.jsx and imports ConfirmContext from here.
export const ConfirmContext = createContext(null);

// Uso: const confirm = useConfirm();
//      const ok = await confirm({ message: "...", dangerMode: true });
export function useConfirm() {
    return useContext(ConfirmContext);
}
