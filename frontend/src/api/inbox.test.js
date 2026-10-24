import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  default: { post: vi.fn(), get: vi.fn() },
}));

import api from "./client";
import { getInboxMedia, getThreadContext, getThreadMessages, markThreadRead, retryInboxMessage, sendInboxMessage } from "./inbox";

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({ data: { id: "message-1" } });
});

describe("MED-04 — authenticated media transport", () => {
  it("uses the existing authenticated client with a blob response and cancellation", async () => {
    const blob = new Blob(["synthetic media"]);
    api.get.mockResolvedValueOnce({ data: blob });
    const controller = new AbortController();
    await expect(getInboxMedia("public-media", { signal: controller.signal })).resolves.toBe(blob);
    expect(api.get).toHaveBeenLastCalledWith("inbox/media/public-media/", { responseType: "blob", signal: controller.signal });
  });
});

describe("WA-CTX-01 — getThreadContext", () => {
  it("usa ambos UUIDs del hilo y permite cancelar la petición", async () => {
    api.get.mockResolvedValueOnce({ data: { owner: null, pets: [], last_appointment: null } });
    const controller = new AbortController();
    await expect(getThreadContext("contact-public", "account-public", { signal: controller.signal }))
      .resolves.toEqual({ owner: null, pets: [], last_appointment: null });
    expect(api.get).toHaveBeenLastCalledWith("inbox/threads/contact-public/account-public/context/", { signal: controller.signal });
  });
  it("es una lectura sin cuerpo editable ni necesidad de signal", async () => {
    api.get.mockResolvedValueOnce({ data: {} });
    await getThreadContext("contact-public", "account-public");
    expect(api.get).toHaveBeenLastCalledWith("inbox/threads/contact-public/account-public/context/", {});
  });
});

describe("WA-UNR-02 — markThreadRead", () => {
  it("usa los UUIDs del hilo y transmite solo el id de mensaje", async () => {
    await markThreadRead("contact-public", "account-public", 19);
    expect(api.post).toHaveBeenCalledWith("inbox/threads/contact-public/account-public/read/",
      { last_read_message_id: 19 }, {});
  });
  it("permite cancelar la lectura al cambiar de hilo o perder atención", async () => {
    const controller = new AbortController();
    await markThreadRead("contact-public", "account-public", 19, { signal: controller.signal });
    expect(api.post).toHaveBeenCalledWith("inbox/threads/contact-public/account-public/read/",
      { last_read_message_id: 19 }, { signal: controller.signal });
  });
});

describe("WA-RETRY-01 — retryInboxMessage", () => {
  it("reutiliza UUID, id original y key sin transmitir un cuerpo editable", async () => {
    const controller = new AbortController();
    await retryInboxMessage("session-public", 19, "original-key", { signal: controller.signal });
    expect(api.post).toHaveBeenCalledWith("inbox/conversations/session-public/messages/19/retry/",
      {}, { headers: { "X-Idempotency-Key": "original-key" }, signal: controller.signal });
  });
  it("conserva la misma fila cuando el mensaje no tiene key", async () => {
    await retryInboxMessage("session-public", 19, null);
    expect(api.post).toHaveBeenCalledWith("inbox/conversations/session-public/messages/19/retry/", {}, {});
  });
});

describe("sendInboxMessage", () => {
  it("envía reply_to_id junto con cuerpo, key y señal sin cambiar el contrato previo", async () => {
    const controller = new AbortController();
    await sendInboxMessage("session-public", "Respuesta citada", "reply-key", {
      replyToId: 37, signal: controller.signal,
    });
    expect(api.post).toHaveBeenCalledWith("inbox/conversations/session-public/send/",
      { body: "Respuesta citada", reply_to_id: 37 },
      { headers: { "X-Idempotency-Key": "reply-key" }, signal: controller.signal });
  });

  it.each([null, undefined])("omite la cita ausente %s en lugar de enviar null", async (replyToId) => {
    await sendInboxMessage("session-public", "Sin cita", undefined, { replyToId });
    expect(api.post).toHaveBeenCalledWith("inbox/conversations/session-public/send/", { body: "Sin cita" });
  });

  it("envía la key en X-Idempotency-Key cuando se proporciona", async () => {
    await sendInboxMessage("session-beto", "Respuesta", "idem-123");

    expect(api.post).toHaveBeenCalledWith(
      "inbox/conversations/session-beto/send/",
      { body: "Respuesta" },
      { headers: { "X-Idempotency-Key": "idem-123" } }
    );
  });

  it("mantiene compatible la llamada sin key durante la integración", async () => {
    await sendInboxMessage("session-beto", "Respuesta");

    expect(api.post).toHaveBeenCalledWith(
      "inbox/conversations/session-beto/send/",
      { body: "Respuesta" }
    );
  });

  it("propaga AbortSignal sin perder la key de idempotencia", async () => {
    const controller = new AbortController();

    await sendInboxMessage("session-beto", "Respuesta", "idem-123", {
      signal: controller.signal,
    });

    expect(api.post).toHaveBeenCalledWith(
      "inbox/conversations/session-beto/send/",
      { body: "Respuesta" },
      {
        headers: { "X-Idempotency-Key": "idem-123" },
        signal: controller.signal,
      }
    );
  });
});

describe("getThreadMessages — WA-HIST-01", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockResolvedValue({ data: { messages: [], next_before: null } });
  });
  it("transporta el cursor y permite cancelar la página anterior", async () => {
    const controller = new AbortController();
    await getThreadMessages("contact-public", "account-public", { before: 51 }, { signal: controller.signal });
    expect(api.get).toHaveBeenCalledWith("inbox/threads/contact-public/account-public/messages/",
      { params: { before: 51 }, signal: controller.signal });
  });
  it("conserva la llamada de carga inicial sin opciones adicionales", async () => {
    await expect(getThreadMessages("contact-public", "account-public")).resolves.toEqual({ messages: [], next_before: null });
    expect(api.get).toHaveBeenCalledWith("inbox/threads/contact-public/account-public/messages/", { params: {} });
  });
});
