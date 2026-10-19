/**
 * Reports the engine's own Hermes calls (choosing the next button, drafting a
 * written answer, checking that draft) to Resume Studio's AI activity log, so
 * the AI Engine view shows every AI call the app makes in one place.
 *
 * The sink is a no-op until the service sets it (src/index.ts), so unit tests
 * never write to the real log. Reporting is fire-and-forget: a slow or stopped
 * Studio never delays or fails an application.
 */
export interface AiCall {
  schema: "NavigationAdvice" | "AnswerDraft" | "AnswerAudit";
  job?: string;
  seconds: number;
  status: "ok" | "error";
  error?: string;
  system?: string;
  user?: string;
  response?: string;
  input_tokens?: number;
  output_tokens?: number;
}
type Sink = (call: AiCall) => void;
let sink: Sink = () => {};

export function setAiLogSink(next: Sink) {
  sink = next;
}

/** Studio sink used by the running service. */
export function studioSink(base = "http://127.0.0.1:8088"): Sink {
  return (call) => {
    void fetch(base + "/ai/activity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(call),
      signal: AbortSignal.timeout(5000),
    }).catch(() => {});
  };
}

/**
 * One Hermes chat completion through the bridge, reported to the log.
 * Returns the reply text, or throws after logging the failure.
 */
export async function hermesChat(
  endpoint: string,
  schema: AiCall["schema"],
  messages: { role: string; content: string }[],
  request: typeof fetch = fetch,
  job = "",
): Promise<string> {
  const started = Date.now();
  const system = messages.find((m) => m.role === "system")?.content || "";
  const user = messages.filter((m) => m.role !== "system").map((m) => m.content).join("\n\n");
  try {
    const response = await request(endpoint.replace(/\/$/, "") + "/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(process.env.HERMES_API_KEY ? { Authorization: `Bearer ${process.env.HERMES_API_KEY}` } : {}),
      },
      signal: AbortSignal.timeout(45000),
      body: JSON.stringify({ model: "hermes-agent", temperature: 0, messages }),
    });
    if (!response.ok) throw new Error(`Hermes bridge answered ${response.status}`);
    const data = (await response.json()) as any;
    const text = String(data.choices?.[0]?.message?.content || "").trim();
    sink({
      schema, job, system, user, response: text, status: "ok",
      seconds: (Date.now() - started) / 1000,
      input_tokens: Number(data.usage?.prompt_tokens || 0),
      output_tokens: Number(data.usage?.completion_tokens || 0),
    });
    return text;
  } catch (e) {
    sink({
      schema, job, system, user, status: "error", error: (e as Error).message,
      seconds: (Date.now() - started) / 1000,
    });
    throw e;
  }
}

/** Strip a ```json fence a model may wrap around its JSON reply. */
export const unfence = (text: string) =>
  text.trim().replace(/^```(?:json)?\s*|\s*```$/g, "");
