import api from "./client";

export const sendSupportMessage = ({ message, pageUrl, timestamp, image }) => {
    const form = new FormData();
    form.append("message", message);
    form.append("page_url", pageUrl);
    form.append("timestamp", timestamp);
    if (image) {
        form.append("image", image, image.name);
    }

    return api.post("support/message/", form).then(r => r.data);
};
