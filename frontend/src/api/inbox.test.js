import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  default: { post: vi.fn() },
}));

import api from "./client";
import { sendInboxMessage } from "./inbox";

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({ data: { id: "message-1" } });
});

describe("sendInboxMessage", () => {
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
