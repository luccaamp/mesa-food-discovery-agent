/** Position of the price within the item's cuisine; the dataset publishes no currency. */
export type PriceBand = {
  level: 1 | 2 | 3 | null;
  symbol: "$" | "$$" | "$$$" | null;
  label: string;
  pricier_share: number | null;
  reference: string | null;
};
export type Item = {
  vendor_id: string;
  product_id: string;
  name: string;
  unit_price: number | null;
  primary_cuisine: string;
  price_band?: PriceBand | null;
  reason?: string;
  training_baskets?: number;
  context_orders?: number | null;
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
  region?: string | null;
  cuisine: string | null;
  min_price: number | null;
  max_price: number | null;
  price_level?: number | null;
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
  value === null || value === 0 ? "Não registrado na fonte" : `${amount(value)} (unidade do dataset, sem moeda)`;
/** "Mais barato que 72% dos itens de pizza", or null when the price is unknown. */
export const priceComparison = (band?: PriceBand | null) => {
  if (!band || band.level === null || band.pricier_share === null) return null;
  const share = band.pricier_share;
  return share >= 0.5
    ? `Mais barato que ${Math.round(share * 100)}% dos itens de ${band.reference}`
    : `Mais caro que ${Math.round((1 - share) * 100)}% dos itens de ${band.reference}`;
};
export const count = (value: number) =>
  new Intl.NumberFormat("pt-BR").format(value);
