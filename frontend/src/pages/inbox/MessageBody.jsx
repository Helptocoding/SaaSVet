import { tokenizeMessageUrls } from "./messageText";
import styles from "./inbox.module.css";

export default function MessageBody({ text }) {
    return tokenizeMessageUrls(text).map((part, index) => part.href ? (
        <a key={index} href={part.href} target="_blank" rel="noopener noreferrer" className={styles.messageLink}>
            {part.text}
        </a>
    ) : part.text);
}
