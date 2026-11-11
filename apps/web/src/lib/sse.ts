import type { Chat, Context } from "../api";

export type AgentEvent =
  | { type: "plan"; provider: string | null; model: string | null; tools: string[] }
  | {
      type: "tool";
      name: string;
      arguments: Record<string, unknown>;
      result_count: number;
      duration_ms: number;
    }
  | { type: "fallback"; reason: string | null }
  | { type: "result"; response: Chat };

/** Parse one Server-Sent Events block ("event: x\ndata: {...}"). */
export function parseBlock(block: string): AgentEvent | null {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as AgentEvent;
  } catch {
    return null;
  }
}

/**
 * POST to the agent stream and deliver events as they arrive.
 * EventSource only supports GET, so the body is read with fetch streams.
 */
export async function streamAgent(
  message: string,
  context: Context,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<Chat> {
  const response = await fetch("/v1/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, context }),
    signal,
  });
  if (!response.ok || !response.body) {
    if (response.status === 429)
      throw new Error("A demonstração atingiu o limite temporário de consultas. Aguarde um minuto.");
    if (response.status === 503)
      throw new Error("O serviço está ocupado ou iniciando. Tente novamente em instantes.");
    throw new Error("Não consegui falar com o assistente agora. Tente novamente.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: Chat | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parseBlock(block);
      if (!event) continue;
      if (event.type === "result") result = event.response;
      onEvent(event);
    }
    if (done) break;
  }
  if (!result) throw new Error("A resposta do assistente foi interrompida. Tente novamente.");
  return result;
}
