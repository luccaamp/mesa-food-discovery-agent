export type Item = {
  vendor_id: string;
  product_id: string;
  name: string;
  unit_price: number | null;
  primary_cuisine: string;
  reason?: string;
  training_baskets?: number;
  supporting_co_baskets?: number;
};
export type Meta = {
  products: number;
  cuisines: number;
  city: string;
  source_hashes: Record<string, string>;
  source_database_sha256: string;
  historical_catalog: boolean;
  limitations: string[];
};
export type Search = {
  query: string;
  total_matches: number;
  items: Item[];
  provenance: Meta;
};
export type Discovery = {
  status: string;
  message: string;
  query: string;
  resolved_query: string | null;
  result: Search | null;
};
export type Context = {
  last_query: string | null;
  cuisine: string | null;
  min_price: number | null;
  max_price: number | null;
  selected_items: { vendor_id: string; product_id: string }[];
};
export type Chat = {
  fallback_reason?: "provider_timeout" | "provider_cooldown" | "quota" | "invalid_response" | "provider_unavailable" | null;
  retry_after_seconds?: number | null;
  status: string;
  answer: string;
  items: Item[];
  context: Context;
  tools: {
    name: string;
    duration_ms: number;
    result_count: number;
    arguments: Record<string, unknown>;
  }[];
  planner: string;
  model: string | null;
  usage: Record<string, number>;
  elapsed_ms: number;
  warnings: string[];
};
export type System = {
  assistant: {
    provider: string;
    model: string;
    available: boolean;
    configured?: boolean;
    status?: string;
  };
  recommendations_ready: boolean;
  semantic_status: string;
};
export type Evaluation = {
  id: string;
  kind: string;
  users?: number;
  queries?: number;
  products?: number;
  models: Record<string, any>;
  limitations: string[];
};
export type AssistantEvaluation = {
  passed: number;
  total: number;
  catalog_items_checked: number;
  llm_calls: number;
  tokens: { total_tokens: number };
  latency_ms: { median: number; maximum: number };
  model: string;
  report_version: string;
  live_gemini_tested: boolean;
};
export type ConversationEvaluation = {
  scenarios: number;
  profiles: number;
  episodes: number;
  passed: number;
  turns: number;
  catalog_items_checked: number;
  llm_calls: number;
  pass_power_3: number | null;
  baseline_passed: number;
  baseline_episodes: number;
};
export type AiEvaluation = {
  simulator_requested: number;
  simulator_accepted: number;
  wording_changed_turns: number;
  generated_episodes_passed: number;
  generated_episodes: number;
  judge_controls_passed: number;
  judge_judgments: number;
  advisory_reviews: number;
  advisory_valid: number;
};
export type PublicAssistantEvaluation = {
  complete?: boolean;
  cases_executed?: number;
  deployment_commit?: string;
  limitations?: string;
  passed: number;
  total: number;
  model: string;
  verified_at: string;
  gemini_inferences_completed: number;
  provider_attempts: number;
  successful_response_tokens: number;
  catalog_items_checked: number;
  http_latency_ms_median: number;
};
export type RelevanceEvaluation = {
  controls_correct: number;
  controls_total: number;
  controls_required?: number;
  queries: number;
  decision: string;
  judge_admitted?: boolean;
  judged_top1_pilot_complete?: boolean;
  top1_summary?: Record<string, {
    queries: number;
    scored_queries: number;
    full_match_rate_at_1: number | null;
    abstentions: number;
    empty_results: number;
  }>;
};
export function fallbackMessage(response: Pick<Chat, "fallback_reason" | "retry_after_seconds">): string {
  switch (response.fallback_reason) {
    case "provider_timeout":
      return "A IA demorou além do limite. Usei o glossário para continuar a busca, sem inferência de IA.";
    case "provider_cooldown":
      return "A IA está em uma pausa temporária após falhas. Usei o glossário para você continuar; não é necessário reenviar a mensagem agora.";
    case "quota":
      return "O limite temporário de uso da IA foi atingido. Esta resposta usa somente o glossário.";
    case "invalid_response":
      return "A resposta da IA não pôde ser validada. Esta busca usa somente o glossário.";
    default:
      return "Nesta resposta, usei o glossário porque a IA não estava disponível.";
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 75_000);
  try {
    const response = await fetch(path, {
      ...options,
      signal: options?.signal
        ? AbortSignal.any([options.signal, controller.signal])
        : controller.signal,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
    const text = await response.text();
    let result;
    try {
      result = JSON.parse(text);
    } catch {
      throw new Error(
        "O serviço ainda não retornou os dados. A hospedagem gratuita pode estar iniciando; tente novamente em instantes.",
      );
    }
    if (!response.ok) {
      if (response.status === 429)
        throw new Error(
          "A demonstração atingiu o limite temporário de consultas. Aguarde um minuto e tente novamente.",
        );
      throw new Error(
        result.error?.message ??
          "O serviço está temporariamente indisponível. Tente novamente em instantes.",
      );
    }
    return result;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw new Error(
        "A consulta demorou além do esperado. O serviço pode estar acordando; tente novamente.",
      );
    if (error instanceof TypeError)
      throw new Error(
        "Não consegui conectar ao serviço. Confira sua conexão e tente novamente.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
export const keyOf = (item: Item) => `${item.vendor_id}:${item.product_id}`;
export const amount = (value: number) =>
  new Intl.NumberFormat("pt-BR", {
    maximumSignificantDigits: 6,
  }).format(value);
export const priceLabel = (value: number | null) =>
  value === null
    ? "Não informado"
    : value === 0
      ? "Zero na fonte"
      : `${amount(value)} u.n.`;
export const count = (value: number) =>
  new Intl.NumberFormat("pt-BR").format(value);
