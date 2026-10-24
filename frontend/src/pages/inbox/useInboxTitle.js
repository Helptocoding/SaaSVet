import { useEffect } from "react";

export default function useInboxTitle(conversations) {
    const pendingCount = conversations.filter((thread) => thread.has_unanswered).length;
    useEffect(() => {
        const originalTitle = document.title;
        const updateTitle = () => {
            const background = document.hidden || !document.hasFocus();
            document.title = background && pendingCount > 0
                ? `(${pendingCount}) ${originalTitle}` : originalTitle;
        };
        updateTitle();
        document.addEventListener("visibilitychange", updateTitle);
        window.addEventListener("focus", updateTitle);
        window.addEventListener("blur", updateTitle);
        return () => {
            document.removeEventListener("visibilitychange", updateTitle);
            window.removeEventListener("focus", updateTitle);
            window.removeEventListener("blur", updateTitle);
            document.title = originalTitle;
        };
    }, [pendingCount]);
}
