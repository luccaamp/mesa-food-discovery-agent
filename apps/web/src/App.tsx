import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  Check,
  ChevronRight,
  Compass,
  Database,
  FlaskConical,
  Leaf,
  LoaderCircle,
  MessageCircle,
  Search as SearchIcon,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UtensilsCrossed,
  X,
  Info,
  Coffee,
  ChartNoAxesColumnIncreasing,
  ExternalLink,
} from "lucide-react";
import {
  api,
  fallbackMessage,
  priceLabel,
  count,
  keyOf,
  type Chat,
  type Context,
  type Discovery,
  type Evaluation,
  type AssistantEvaluation,
  type ConversationEvaluation,
  type AiEvaluation,
  type PublicAssistantEvaluation,
  type RelevanceEvaluation,
  type Item,
  type Meta,
  type System,
} from "./api";

type Page = "discover" | "assistant" | "lab";
type Message = { role: "user" | "assistant"; text: string; response?: Chat };
type Filters = Pick<Context, "cuisine" | "min_price" | "max_price">;
const emptyContext: Context = {
  last_query: null,
  cuisine: null,
  min_price: null,
  max_price: null,
  selected_items: [],
};
const examples = [
  "Arroz com frango",
  "Chá com leite",
  "Pizza de queijo",
  "Café gelado",
];

function CategoryIcon({
  category,
  size = 22,
}: {
  category: string;
  size?: number;
}) {
  return /coffee|tea|drink|juice/.test(category) ? (
    <Coffee size={size} />
  ) : /salad|veget/.test(category) ? (
    <Leaf size={size} />
  ) : (
    <UtensilsCrossed size={size} />
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("discover");
  useEffect(() => {
    window.scrollTo(0, 0);
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [page]);
  const [meta, setMeta] = useState<Meta | null>(null),
    [system, setSystem] = useState<System | null>(null);
  const [cuisines, setCuisines] = useState<
    { name: string; products: number }[]
  >([]);
  const [reports, setReports] = useState<Evaluation[]>([]);
  const [assistantEvaluation, setAssistantEvaluation] =
    useState<AssistantEvaluation | null>(null);
  const [conversationEvaluation, setConversationEvaluation] = useState<ConversationEvaluation | null>(null);
  const [aiEvaluation, setAiEvaluation] = useState<AiEvaluation | null>(null);
  const [publicAssistantEvaluation, setPublicAssistantEvaluation] = useState<PublicAssistantEvaluation | null>(null);
  const [relevanceEvaluation, setRelevanceEvaluation] = useState<RelevanceEvaluation | null>(null);
  const [bootLoading, setBootLoading] = useState(true);
  const [bootErrors, setBootErrors] = useState<string[]>([]);
  const [query, setQuery] = useState("arroz com frango"),
    [cuisine, setCuisine] = useState("");
  const [min, setMin] = useState(""),
    [max, setMax] = useState("");
  const [discovery, setDiscovery] = useState<Discovery | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const [selected, setSelected] = useState<Item[]>([]),
    [detail, setDetail] = useState<Item | null>(null);
  const [recommendations, setRecommendations] = useState<Item[]>([]),
    [recLoading, setRecLoading] = useState(false),
    [recError, setRecError] = useState("");
  const [recRequested, setRecRequested] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]),
    [draft, setDraft] = useState(""),
    [chatLoading, setChatLoading] = useState(false);
  const [context, setContext] = useState<Context>(emptyContext);
  const dialog = useRef<HTMLDialogElement>(null),
    chatEnd = useRef<HTMLDivElement>(null),
    searchSequence = useRef(0),
    recSequence = useRef(0),
    overviewSequence = useRef(0);
  useEffect(() => {
    loadOverview();
    search("arroz com frango");
  }, []);
  async function loadOverview() {
    const seq = ++overviewSequence.current;
    setBootLoading(true);
    setBootErrors([]);
    const failures: string[] = [];
    async function load<T>(
      path: string,
      label: string,
      apply: (value: T) => void,
    ) {
      try {
        const value = await api<T>(path);
        if (seq === overviewSequence.current) apply(value);
      } catch {
        failures.push(label);
      }
    }
    await Promise.all([
      load<Meta>("/v1/catalog/meta", "Resumo do catálogo", setMeta),
      load<{ cuisines: { name: string; products: number }[] }>(
        "/v1/catalog/cuisines",
        "Filtro de culinárias",
        (c) => setCuisines(c.cuisines),
      ),
      load<System>("/v1/system", "Estado do assistente", setSystem),
      load<{
        reports: Evaluation[];
        assistant_evaluation?: AssistantEvaluation | null;
        conversation_evaluation?: ConversationEvaluation | null;
        ai_evaluation?: AiEvaluation | null;
        public_assistant_evaluation?: PublicAssistantEvaluation | null;
        relevance_evaluation?: RelevanceEvaluation | null;
      }>("/v1/evaluations", "Relatórios do laboratório", (e) => {
        setReports(e.reports);
        setAssistantEvaluation(e.assistant_evaluation ?? null);
        setConversationEvaluation(e.conversation_evaluation ?? null);
        setAiEvaluation(e.ai_evaluation ?? null);
        setPublicAssistantEvaluation(e.public_assistant_evaluation ?? null);
        setRelevanceEvaluation(e.relevance_evaluation ?? null);
      }),
    ]);
    if (seq === overviewSequence.current) {
      setBootErrors(failures);
      setBootLoading(false);
    }
  }
  useEffect(() => {
    ++recSequence.current;
    setRecommendations([]);
    setRecError("");
    setRecLoading(false);
    setRecRequested(false);
  }, [selected, cuisine, min, max]);
  useEffect(() => {
    if (detail) dialog.current?.showModal();
    else dialog.current?.close();
  }, [detail]);
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, chatLoading]);
  function filters() {
    if (
      [min, max].some(
        (value) =>
          value !== "" &&
          (!Number.isFinite(Number(value)) || Number(value) < 0),
      )
    )
      throw new Error(
        "Use valores normalizados finitos e maiores ou iguais a zero.",
      );
    if (min !== "" && max !== "" && Number(min) > Number(max))
      throw new Error("O preço mínimo deve ser menor ou igual ao máximo.");
    return {
      cuisine: cuisine || null,
      min_price: min === "" ? null : Number(min),
      max_price: max === "" ? null : Number(max),
    };
  }
  async function search(value = query, override?: Filters) {
    const seq = ++searchSequence.current;
    setLoading(true);
    setError("");
    setDiscovery(null);
    try {
      const f = override ?? filters();
      const params = new URLSearchParams({ query: value, limit: "12" });
      Object.entries(f).forEach(([key, v]) => {
        if (v !== null) params.set(key, String(v));
      });
      const data = await api<Discovery>("/v1/discovery/search?" + params);
      if (seq === searchSequence.current) {
        setDiscovery(data);
        setQuery(value);
      }
    } catch (e) {
      if (seq === searchSequence.current)
        setError(e instanceof Error ? e.message : "Falha ao buscar.");
    } finally {
      if (seq === searchSequence.current) setLoading(false);
    }
  }
  function toggle(item: Item) {
    setSelected((current) =>
      current.some((value) => keyOf(value) === keyOf(item))
        ? current.filter((value) => keyOf(value) !== keyOf(item))
        : current.length < 5
          ? [...current, item]
          : current,
    );
  }
  async function recommend() {
    const seq = ++recSequence.current;
    setRecLoading(true);
    setRecError("");
    setRecRequested(true);
    try {
      const result = await api<{ items: Item[] }>("/v1/recommendations", {
        method: "POST",
        body: JSON.stringify({
          seeds: selected.map(({ vendor_id, product_id }) => ({
            vendor_id,
            product_id,
          })),
          ...filters(),
          limit: 6,
        }),
      });
      if (seq === recSequence.current) setRecommendations(result.items);
    } catch (e) {
      if (seq === recSequence.current)
        setRecError(e instanceof Error ? e.message : "Falha ao recomendar.");
    } finally {
      if (seq === recSequence.current) setRecLoading(false);
    }
  }
  async function chat(value = draft) {
    if (!value.trim() || chatLoading) return;
    setDraft("");
    setMessages((current) => [...current, { role: "user", text: value }]);
    setChatLoading(true);
    try {
      const result = await api<Chat>("/v1/assistant", {
        method: "POST",
        body: JSON.stringify({
          message: value,
          context: {
            ...context,
            ...filters(),
            selected_items: selected.map(({ vendor_id, product_id }) => ({
              vendor_id,
              product_id,
            })),
          },
        }),
      });
      setContext(result.context);
      if (result.context.max_price !== null)
        setMax(String(result.context.max_price));
      setMessages((current) => [
        ...current,
        { role: "assistant", text: result.answer, response: result },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text:
            error instanceof Error
              ? error.message
              : "Não consegui concluir esta consulta. Tente novamente ou use a busca.",
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  }
  function card(item: Item, index: number, compact = false) {
    const saved = selected.some((value) => keyOf(value) === keyOf(item));
    return (
      <article
        className={"food-card " + (compact ? "compact" : "")}
        key={keyOf(item)}
      >
        <div className={"card-art art-" + (index % 4)} aria-hidden="true">
          <span className="art-rings" />
          <CategoryIcon
            category={item.primary_cuisine}
            size={compact ? 28 : 42}
          />
          <span className="art-caption">{item.primary_cuisine}</span>
        </div>
        <div className="card-body">
          <div className="card-category">{item.primary_cuisine}</div>
          <h3>{item.name}</h3>
          <p className="price">{priceLabel(item.unit_price)}</p>
          <p className="price-caption">
            {item.unit_price === 0
              ? "Valor normalizado registrado como zero; não significa gratuito."
              : "Valor normalizado da base · sem moeda"}
          </p>
          {item.reason && (
            <p className="reason">
              {item.reason === "basket_association"
                ? "Associação em cestas reais"
                : "Popularidade histórica"}
            </p>
          )}
          <div className="card-bottom">
            <button className="text-button" onClick={() => setDetail(item)}>
              Ver evidências <ArrowUpRight size={15} />
            </button>
            <button
              className={"save-button " + (saved ? "saved" : "")}
              title={
                saved
                  ? "Remover da seleção"
                  : selected.length >= 5
                    ? "Limite de cinco itens selecionados"
                    : "Selecionar como referência"
              }
              aria-label={
                saved ? `Remover ${item.name}` : `Selecionar ${item.name}`
              }
              aria-pressed={saved}
              disabled={!saved && selected.length >= 5}
              onClick={() => toggle(item)}
            >
              {saved ? <Check size={17} /> : <Bookmark size={17} />}
            </button>
          </div>
        </div>
      </article>
    );
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Pular para o conteúdo
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("discover");
          }}
          aria-label="Mesa, início"
        >
          <span className="brand-symbol">
            <UtensilsCrossed size={23} />
          </span>
          mesa<span className="brand-dot">.</span>
        </a>
        <span className="brand-subtitle">DESCUBRA COM CONTEXTO</span>
        <nav aria-label="Navegação principal">
          {(
            [
              { id: "discover", label: "Explorar", icon: Compass },
              { id: "assistant", label: "Assistente", icon: Sparkles },
              { id: "lab", label: "Laboratório", icon: FlaskConical },
            ] as const
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={page === id ? "nav-active" : ""}
              aria-label={label}
              aria-current={page === id ? "page" : undefined}
              onClick={() => setPage(id)}
            >
              <Icon size={19} />
              <span>{label}</span>
              {page === id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-selection">
          <div>
            <Bookmark size={16} /> SUA SELEÇÃO <span>{selected.length}/5</span>
          </div>
          {selected.length ? (
            <>
              <ul>
                {selected.map((item) => (
                  <li key={keyOf(item)}>
                    <span>{item.name}</span>
                    <button
                      onClick={() => toggle(item)}
                      aria-label={`Remover ${item.name}`}
                    >
                      <X size={13} />
                    </button>
                  </li>
                ))}
              </ul>
              <p>Itens escolhidos por você para orientar sugestões.</p>
            </>
          ) : (
            <p>
              Marque itens do catálogo para descobrir combinações relacionadas.
            </p>
          )}
        </div>
        <div className="sidebar-bottom">
          <span className="dataset-dot" /> Dados reais, escolhas informadas
          <p>Um projeto independente de IA.</p>
          <a
            href="https://github.com/luccaamp/mesa-food-discovery-agent"
            target="_blank"
            rel="noreferrer"
          >
            Código & metodologia <ExternalLink size={13} />
          </a>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="breadcrumb">
            Mesa <ChevronRight size={13} />
            {page === "discover"
              ? "Explorar o catálogo"
              : page === "assistant"
                ? "Conversa com contexto"
                : "Métodos & resultados"}
          </span>
          <div className="historical-pill">
            <span /> Singapura <span className="pill-divider">/</span> Catálogo
            histórico
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {bootLoading && (
            <div className="service-status" role="status">
              <LoaderCircle className="spin" size={16} /> Carregando o catálogo
              e os relatórios. A primeira abertura da hospedagem gratuita pode
              levar cerca de um minuto.
            </div>
          )}
          {bootErrors.length > 0 && (
            <div className="service-status service-warning" role="alert">
              <Info size={17} />
              <span>
                Não foi possível carregar: {bootErrors.join(", ")}. Você pode
                tentar novamente sem recarregar a página.
              </span>
              <button
                className="text-button"
                disabled={bootLoading}
                onClick={loadOverview}
              >
                Tentar novamente
              </button>
            </div>
          )}
          {page === "discover" && (
            <>
              <section className="hero">
                <div className="eyebrow">
                  <span /> EXPLORAÇÃO COM EVIDÊNCIAS
                </div>
                <h1>
                  Uma boa escolha
                  <br />
                  começa <em>aqui.</em>
                </h1>
                <p>
                  Explore um catálogo real de Singapura.
                  <br className="desktop-break" /> Explore, refine e descubra o
                  contexto de cada sugestão histórica.
                </p>
                <div className="hero-illustration" aria-hidden="true">
                  <div className="plate">
                    <div className="plate-inner">
                      <Leaf size={76} strokeWidth={1} />
                    </div>
                  </div>
                  <span className="floating-label">
                    <Sparkles size={14} /> Curiosidade à mesa
                  </span>
                  <span className="small-orbit" />
                </div>
              </section>
              <section className="how-it-works" aria-label="Como usar o Mesa">
                <div>
                  <span>01</span>
                  <p>
                    <strong>Busque um prato</strong>Use nomes em português ou
                    inglês.
                  </p>
                </div>
                <div>
                  <span>02</span>
                  <p>
                    <strong>Marque suas referências</strong>Selecione até cinco
                    itens nos cards.
                  </p>
                </div>
                <div>
                  <span>03</span>
                  <p>
                    <strong>Descubra associações</strong>Veja sugestões e a
                    evidência dos pedidos.
                  </p>
                </div>
              </section>
              <section className="search-section" aria-label="Busca e filtros">
                <form
                  className="search-box"
                  onSubmit={(e: FormEvent) => {
                    e.preventDefault();
                    search();
                  }}
                >
                  <SearchIcon size={23} />
                  <label className="sr-only" htmlFor="query">
                    O que você quer encontrar?
                  </label>
                  <input
                    id="query"
                    maxLength={200}
                    required
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Um prato, uma bebida, uma vontade…"
                  />
                  <button
                    className="primary"
                    aria-label="Explorar catálogo"
                    disabled={loading}
                  >
                    {loading ? (
                      <LoaderCircle className="spin" size={19} />
                    ) : (
                      <>
                        Explorar <ArrowRight size={18} />
                      </>
                    )}
                  </button>
                </form>
                <div className="query-chips">
                  <span>Experimente</span>
                  {examples.map((example) => (
                    <button key={example} onClick={() => search(example)}>
                      {example}
                      <ArrowUpRight size={12} />
                    </button>
                  ))}
                </div>
                <div className="filter-row">
                  <span className="filter-label">
                    <SlidersHorizontal size={16} /> Refine sua busca
                  </span>
                  <label>
                    <span className="sr-only">Culinária</span>
                    <select
                      value={cuisine}
                      disabled={bootLoading && !cuisines.length}
                      onChange={(e) => setCuisine(e.target.value)}
                    >
                      <option value="">Todas as culinárias</option>
                      {cuisines.map((value) => (
                        <option key={value.name} value={value.name}>
                          {value.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="price-filter">
                    Mín.{" "}
                    <input
                      type="number"
                      step="any"
                      min="0"
                      value={min}
                      onChange={(e) => setMin(e.target.value)}
                      placeholder="—"
                      aria-label="Preço mínimo normalizado"
                    />
                  </label>
                  <label className="price-filter">
                    Máx.{" "}
                    <input
                      type="number"
                      step="any"
                      min="0"
                      value={max}
                      onChange={(e) => setMax(e.target.value)}
                      placeholder="—"
                      aria-label="Preço máximo normalizado"
                    />
                  </label>
                  <button className="apply-filter" onClick={() => search()}>
                    Aplicar
                  </button>
                  {(cuisine || min || max) && (
                    <button
                      className="clear-filter"
                      onClick={() => {
                        setCuisine("");
                        setMin("");
                        setMax("");
                        search(query, {
                          cuisine: null,
                          min_price: null,
                          max_price: null,
                        });
                      }}
                    >
                      Limpar filtros
                    </button>
                  )}
                </div>
                <p className="filter-note">
                  <Info size={12} /> Preços em unidades normalizadas (u.n.), sem
                  moeda ou conversão para reais. Ex.: 0,002 é um valor positivo;
                  zero na fonte não significa que o produto é gratuito.
                </p>
              </section>
              <section aria-labelledby="results-title">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">DO CATÁLOGO PARA VOCÊ</span>
                    <h2 id="results-title">
                      Explore possibilidades
                      <span className="count-label">
                        {discovery?.result
                          ? count(discovery.result.total_matches) +
                            " resultados"
                          : "Catálogo real"}
                      </span>
                    </h2>
                  </div>
                  <span className="ranking-label">
                    Ordenação por relevância textual
                  </span>
                </div>
                {error && (
                  <div role="alert" className="notice error">
                    <Info size={18} />
                    {error}
                    <button className="text-button" onClick={() => search()}>
                      Tentar busca novamente
                    </button>
                  </div>
                )}
                {loading ? (
                  <div className="loading-state" role="status">
                    <LoaderCircle size={24} className="spin" />
                    <span>Consultando o catálogo real…</span>
                  </div>
                ) : discovery?.status === "needs_clarification" ? (
                  <div className="empty-state">
                    <ShieldCheck size={32} />
                    <h3>Vamos esclarecer essa preferência</h3>
                    <p>{discovery.message}</p>
                  </div>
                ) : discovery?.result?.items.length ? (
                  <>
                    <div className="resolved-query">
                      Busca realizada por{" "}
                      <strong>{discovery.resolved_query}</strong>
                      <span>Vocabulário PT → EN explícito</span>
                    </div>
                    <div className="results-grid">
                      {discovery.result.items.map((item, index) =>
                        card(item, index),
                      )}
                    </div>
                  </>
                ) : (
                  !error && (
                    <div className="empty-state">
                      <SearchIcon size={32} />
                      <h3>Nenhuma correspondência por aqui</h3>
                      <p>
                        Tente outro nome ou amplie os filtros. Não preenchemos
                        resultados com itens inventados.
                      </p>
                    </div>
                  )
                )}
              </section>
              <section className="recommend-section">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">CONTEXTO QUE APROXIMA</span>
                    <h2>
                      {selected.length
                        ? "A partir da sua seleção"
                        : "O que aparece nas cestas"}
                    </h2>
                    <p>
                      {selected.length
                        ? recommendations.length &&
                          recommendations.every(
                            (item) => item.reason === "historical_popularity",
                          )
                          ? "Sem associações para a seleção atual; estas opções seguem popularidade histórica."
                          : "Associações observadas em pedidos reais, sem histórico pessoal inventado."
                        : "Explore itens pela popularidade nos pedidos históricos de treino."}
                    </p>
                  </div>
                  <button
                    className="secondary"
                    onClick={recommend}
                    disabled={recLoading}
                  >
                    {recLoading ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      <Sparkles size={16} />
                    )}{" "}
                    Descobrir sugestões
                  </button>
                </div>
                {recError && (
                  <div role="alert" className="notice error">
                    {recError}
                  </div>
                )}
                {recLoading && (
                  <div className="loading-state" role="status">
                    <LoaderCircle className="spin" size={22} />
                    <span>Buscando associações nos pedidos de treino…</span>
                  </div>
                )}
                {!recLoading && !recError && !recommendations.length && (
                  <div className="recommend-hint">
                    {recRequested
                      ? "Não há sugestões com estes filtros. Amplie os limites ou escolha outra culinária."
                      : selected.length
                        ? `${selected.length} referência(s) selecionada(s). Clique em “Descobrir sugestões” para calcular as opções desta seleção.`
                        : "Clique em “Descobrir sugestões” para ver os mais frequentes nos pedidos de treino, ou marque itens acima para orientar as associações."}
                  </div>
                )}
                {recommendations.length > 0 && (
                  <div className="results-grid">
                    {recommendations.map((item, index) => card(item, index))}
                  </div>
                )}
              </section>
              <section className="assistant-banner">
                <div className="banner-icon">
                  <MessageCircle size={25} />
                </div>
                <div>
                  <h3>Uma vontade difícil de descrever?</h3>
                  <p>
                    Converse para explorar pratos e ajustar suas preferências.
                  </p>
                </div>
                <button onClick={() => setPage("assistant")}>
                  Vamos conversar <ArrowUpRight size={18} />
                </button>
              </section>
            </>
          )}
          {page === "assistant" && (
            <section className="assistant-page">
              <div className="eyebrow">
                <Sparkles size={13} /> CONVERSA COM CONTEXTO
              </div>
              <h1>
                Conte sua <em>vontade.</em>
              </h1>
              <p className="page-intro">
                Busque pratos e refine suas preferências por conversa.
                <br />
                Cada resultado vem do catálogo real, com evidências à vista.
              </p>
              <div className="assistant-status">
                <span
                  className={
                    system?.assistant.available ? "online-dot" : "offline-dot"
                  }
                />
                {!system
                  ? bootLoading
                    ? "Verificando o assistente…"
                    : "Não foi possível verificar o modelo"
                  : system.assistant.status === "temporarily_unavailable"
                    ? "IA temporariamente indisponível · busca essencial disponível"
                    : system.assistant.provider === "gemini" &&
                      system.assistant.configured
                    ? "Gemini configurado · disponibilidade sujeita à cota"
                    : system?.assistant.available
                      ? "Qwen local conectado"
                      : "Modo essencial · glossário disponível"}
                <span>Sem memória pessoal persistida</span>
              </div>
              {system &&
                !system.assistant.available &&
                !system.assistant.configured && (
                  <div className="notice assistant-explanation">
                    <Info size={18} />
                    <p>
                      <strong>Você está no modo essencial.</strong> Pedidos de
                      pratos usam um glossário PT → EN, e “Recomende algo”
                      consulta o recomendador diretamente. A interpretação livre
                      por IA ainda não está ativa neste ambiente.
                    </p>
                  </div>
                )}
              <div className="conversation" aria-live="polite">
                {!messages.length && (
                  <div className="chat-welcome">
                    <div className="chat-mark">
                      <Sparkles size={28} />
                    </div>
                    <h2>Por onde começamos?</h2>
                    <p>
                      Peça um prato ou explore sugestões. Depois refine o preço
                      em unidades normalizadas.
                    </p>
                    <div className="chat-examples">
                      {[
                        "Quero arroz com frango",
                        "Quero chá com leite",
                        "Recomende algo",
                      ].map((value) => (
                        <button key={value} onClick={() => chat(value)}>
                          {value}
                          <ArrowUpRight size={15} />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {messages.map((message, index) => (
                  <div
                    key={index}
                    className={"message message-" + message.role}
                  >
                    <div className="message-label">
                      {message.role === "user" ? "VOCÊ" : "MESA · ASSISTENTE"}
                    </div>
                    <p>{message.text}</p>
                    {message.response && (
                      <>
                        {message.response.planner === "glossary_fallback" && (
                          <p className="notice">
                            {fallbackMessage(message.response)}
                          </p>
                        )}
                        <div className="chat-results">
                          {message.response.items.map((item, i) =>
                            card(item, i, true),
                          )}
                        </div>
                        <details className="tool-details">
                          <summary>
                            <ShieldCheck size={14} /> Como encontrei estas
                            opções <ChevronRight size={14} />
                          </summary>
                          <p>
                            Planejador: {message.response.planner}{" "}
                            {message.response.model &&
                              "· " + message.response.model}
                          </p>
                          {message.response.tools.map((tool, i) => (
                            <p key={i}>
                              {tool.name === "search_catalog"
                                ? "Busca no catálogo"
                                : "Recomendação por cestas"}{" "}
                              · {tool.result_count} itens ·{" "}
                              {Math.round(tool.duration_ms)} ms
                            </p>
                          ))}
                          <p>
                            Resposta em{" "}
                            {Math.round(message.response.elapsed_ms)} ms. Fatos
                            dos produtos vêm das ferramentas; o modelo não cria
                            itens.
                          </p>
                          <p>
                            Tokens informados:{" "}
                            {message.response.usage.total_tokens ??
                              "não informado"}
                            .
                            {message.response.planner === "local_llm" &&
                              " Inferência local, sem cobrança de API. Custo de hardware não medido."}
                          </p>
                        </details>
                      </>
                    )}
                  </div>
                ))}
                {chatLoading && (
                  <div className="chat-thinking" role="status">
                    <LoaderCircle size={18} className="spin" /> Interpretando e
                    consultando as evidências…
                  </div>
                )}
                <div ref={chatEnd} />
              </div>
              <form
                className="chat-composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  chat();
                }}
              >
                <label htmlFor="chat-input" className="sr-only">
                  Mensagem para o assistente
                </label>
                <input
                  id="chat-input"
                  required
                  maxLength={1000}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Ex.: quero uma bebida de chá com leite"
                />
                <button
                  className="primary"
                  aria-label="Enviar mensagem"
                  disabled={chatLoading || !draft.trim()}
                >
                  <Send size={19} />
                </button>
              </form>
              <p className="chat-footnote">
                <ShieldCheck size={13} /> O catálogo não comprova ingredientes,
                alérgenos ou disponibilidade atual.
              </p>
            </section>
          )}
          {page === "lab" && (
            <section className="lab-page">
              <div className="eyebrow">
                <FlaskConical size={14} /> LABORATÓRIO ABERTO
              </div>
              <h1>
                Mais evidência.
                <br />
                <em>Menos suposição.</em>
              </h1>
              <p className="page-intro">
                Resultados reais, métodos explícitos e espaço para os erros.
                <br />
                Nenhuma métrica abaixo comprova impacto comercial.
              </p>
              <div className="metric-grid">
                <div>
                  <Database size={20} />
                  <strong>
                    {meta
                      ? count(meta.products)
                      : bootLoading
                        ? "Carregando…"
                        : "Indisponível"}
                  </strong>
                  <span>produtos no catálogo lexical</span>
                </div>
                <div>
                  <CategoryIcon category="salad" />
                  <strong>
                    {meta?.cuisines ?? (bootLoading ? "…" : "Indisponível")}
                  </strong>
                  <span>culinárias cadastradas</span>
                </div>
                <div>
                  <ShieldCheck size={20} />
                  <strong>Separado</strong>
                  <span>teste oficial, ainda sem avaliação</span>
                </div>
              </div>
              <div className="notice lab-explanation">
                <Info size={18} />
                <p>
                  <strong>O que está sendo comparado?</strong> O experimento
                  prevê a próxima cesta de clientes históricos. A melhor
                  referência usa repetição pessoal, mas esta demonstração
                  pública não identifica clientes: serve associações entre os
                  itens selecionados e popularidade. Os números abaixo são
                  resultados offline, não pedidos recebidos pelo site.
                </p>
              </div>
              {publicAssistantEvaluation && (
                <article className="experiment assistant-evidence">
                  <span className="eyebrow">GEMINI · TESTE NO SITE PUBLICADO</span>
                  <h2>Resultado mais recente do teste público</h2>
                  {publicAssistantEvaluation.complete === false && (
                    <p role="status">Validação incompleta: o teste foi interrompido após falhas do provedor. A busca por glossário continua disponível, mas não equivale a uma resposta de IA.</p>
                  )}
                  <p>{publicAssistantEvaluation.model} · registro de {new Date(publicAssistantEvaluation.verified_at).toLocaleDateString("pt-BR")}. Busca, refinamento de preço, troca de prato, esclarecimentos e recomendação por referência.</p>
                  <div className="assistant-evidence-grid">
                    <div><strong>{publicAssistantEvaluation.passed}/{publicAssistantEvaluation.total}</strong><span>tarefas de aceitação atendidas</span></div>
                    <div><strong>{publicAssistantEvaluation.gemini_inferences_completed}</strong><span>inferências Gemini concluídas</span></div>
                    <div><strong>{publicAssistantEvaluation.catalog_items_checked}</strong><span>ocorrências de itens conferidas</span></div>
                    <div><strong>{count(publicAssistantEvaluation.successful_response_tokens)}</strong><span>tokens nas respostas concluídas</span></div>
                  </div>
                  <p className="chart-caption">São {publicAssistantEvaluation.provider_attempts} tentativas de modelo registradas; as outras tarefas usam regras e ferramentas. Itens confrontados com a base oficial local. Mediana HTTP de {Math.round(publicAssistantEvaluation.http_latency_ms_median)} ms, incluindo a rede do cliente de teste. Este registro não mede satisfação, qualidade geral ou disponibilidade contínua do provedor.</p>
                </article>
              )}
              {relevanceEvaluation && (
                <article className="experiment assistant-evidence">
                  <span className="eyebrow">RELEVÂNCIA · DECISÃO DO EXPERIMENTO</span>
                  <h2>{relevanceEvaluation.judge_admitted ? "Juiz calibrado para um piloto limitado" : "Uma avaliação também pode reprovar o avaliador"}</h2>
                  <p>O avaliador acertou {relevanceEvaluation.controls_correct}/{relevanceEvaluation.controls_total} controles executados na última calibração. {relevanceEvaluation.judge_admitted ? "Foi admitido para estimar a relevância dos nomes, sem certificar ingredientes ou preferências humanas." : "Não foi aprovado para atribuir notas aos resultados do catálogo."}</p>
                  {relevanceEvaluation.controls_required && relevanceEvaluation.controls_total < relevanceEvaluation.controls_required && (
                    <p>A rodada foi interrompida antes dos {relevanceEvaluation.controls_required} julgamentos previstos; não é uma aprovação parcial.</p>
                  )}
                  {relevanceEvaluation.judged_top1_pilot_complete && relevanceEvaluation.top1_summary && (
                    <>
                      <p>Piloto concluído sobre o primeiro resultado de cada consulta. A taxa abaixo mede correspondência completa do nome; abstenções ficam fora do denominador e buscas vazias contam como ausência de correspondência.</p>
                      <ul>
                        {Object.entries(relevanceEvaluation.top1_summary).map(([mode, result]) => (
                          <li key={mode}>
                            {{lexical: "Lexical", glossary_lexical: "Lexical com glossário", semantic: "Semântica", hybrid: "Híbrida"}[mode] ?? mode}: {result.full_match_rate_at_1 === null ? "sem notas" : `${(result.full_match_rate_at_1 * 100).toFixed(1)}%`} · {result.scored_queries}/{result.queries} consultas pontuadas · {result.abstentions} abstenções · {result.empty_results} buscas vazias
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  <p>A comparação adicional usou {relevanceEvaluation.queries} consultas em português e inglês, com regras sobre os nomes dos produtos. Mantivemos a busca lexical com glossário; o piloto semântico não foi promovido.</p>
                  <p className="chart-caption">Essas regras são aproximações de relevância, não preferências humanas. As consultas bilíngues formam pares; os resultados não medem generalização nem ingredientes.</p>
                  <a href="https://github.com/luccaamp/mesa-food-discovery-agent/blob/main/docs/RELEVANCE_REASONING_2026-11-10.md" target="_blank" rel="noreferrer">Ler a decisão e as evidências <ExternalLink size={14} /></a>
                </article>
              )}
              {conversationEvaluation && (
                <article className="experiment assistant-evidence">
                  <span className="eyebrow">CONVERSAS · VERIFICAÇÃO AUTOMÁTICA</span>
                  <h2>Pedidos que mudam, evidências que permanecem</h2>
                  <p>{conversationEvaluation.scenarios} cenários de desenvolvimento em {conversationEvaluation.profiles} perfis roteirizados, com três repetições no Qwen local. Cada item devolvido foi conferido no catálogo oficial.</p>
                  <div className="assistant-evidence-grid">
                    <div><strong>{conversationEvaluation.passed}/{conversationEvaluation.episodes}</strong><span>episódios aprovados</span></div>
                    <div><strong>{conversationEvaluation.turns}</strong><span>turnos executados por HTTP</span></div>
                    <div><strong>{count(conversationEvaluation.catalog_items_checked)}</strong><span>ocorrências de itens conferidas</span></div>
                    <div><strong>{conversationEvaluation.llm_calls}</strong><span>chamadas ao modelo local</span></div>
                  </div>
                  <p className="chart-caption">A primeira execução passou em {conversationEvaluation.baseline_passed}/{conversationEvaluation.baseline_episodes}; foram corrigidas a interpretação de saudações e a troca de prato junto com preço. Perfis roteirizados não representam pessoas reais. Repetições com temperatura zero não provam robustez geral; este registro não mede o Gemini público. A análise qualitativa por IA é consultiva e separada da verificação dos fatos.</p>
                  <a href="https://github.com/luccaamp/mesa-food-discovery-agent/blob/main/docs/AUTOMATED_EVALUATION.md" target="_blank" rel="noreferrer">Consultar protocolo e limitações <ExternalLink size={14} /></a>
                </article>
              )}
              {aiEvaluation && (
                <article className="experiment assistant-evidence">
                  <span className="eyebrow">OUTRA IA · SIMULAÇÃO E CALIBRAÇÃO</span>
                  <h2>Quem avalia também precisa ser testado</h2>
                  <p>O Qwen3-8B propõe mensagens a partir de objetivos. Regras conferem se o simulador preservou o prato, orçamento e ação antes de testar o Mesa. Em outro papel, o modelo passou por controles de juiz em português e inglês.</p>
                  <div className="assistant-evidence-grid">
                    <div><strong>{aiEvaluation.simulator_accepted}/{aiEvaluation.simulator_requested}</strong><span>simulações aceitas</span></div>
                    <div><strong>{aiEvaluation.wording_changed_turns}</strong><span>mensagens com texto alterado</span></div>
                    <div><strong>{aiEvaluation.judge_controls_passed}/{aiEvaluation.judge_judgments}</strong><span>controles do juiz corretos</span></div>
                    <div><strong>{aiEvaluation.advisory_valid}/{aiEvaluation.advisory_reviews}</strong><span>análises no formato esperado</span></div>
                  </div>
                  <p className="chart-caption">O Mesa passou em {aiEvaluation.generated_episodes_passed}/{aiEvaluation.generated_episodes} episódios aceitos do simulador. Rejeições do simulador não são falhas do produto. O piloto revelou erros de interpretação do juiz; notas não aprovam o produto. Os modelos compartilham família e podem compartilhar vieses. Não há medida de satisfação humana.</p>
                </article>
              )}
              {assistantEvaluation && (
                <article className="experiment assistant-evidence">
                  <span className="eyebrow">
                    ASSISTENTE · EXECUÇÃO LOCAL REGISTRADA
                  </span>
                  <h2>Planejamento com ferramentas, fatos do catálogo</h2>
                  <p>
                    {assistantEvaluation.model} · registro{" "}
                    {assistantEvaluation.report_version}. Estes são contratos de
                    desenvolvimento, não uma avaliação humana de qualidade.
                  </p>
                  <div className="assistant-evidence-grid">
                    <div>
                      <strong>
                        {assistantEvaluation.passed}/{assistantEvaluation.total}
                      </strong>
                      <span>contratos atendidos</span>
                    </div>
                    <div>
                      <strong>
                        {assistantEvaluation.catalog_items_checked}
                      </strong>
                      <span>itens conferidos na base</span>
                    </div>
                    <div>
                      <strong>
                        {Math.round(assistantEvaluation.latency_ms.median)} ms
                      </strong>
                      <span>mediana HTTP local</span>
                    </div>
                    <div>
                      <strong>
                        {count(assistantEvaluation.tokens.total_tokens)}
                      </strong>
                      <span>
                        tokens em {assistantEvaluation.llm_calls} chamadas
                        locais
                      </span>
                    </div>
                  </div>
                  <p className="chart-caption">
                    Registro histórico do Qwen local. Não comprova
                    disponibilidade do Gemini, desempenho na hospedagem ou
                    generalização. Nenhum pedido de teste oficial foi usado.
                  </p>
                </article>
              )}
              {reports.map((report) => (
                <article className="experiment" key={report.id}>
                  <div className="experiment-header">
                    <span className="experiment-number">
                      {report.id === "recommendation" ? "01" : "02"}
                    </span>
                    <div>
                      <span className="eyebrow">
                        {report.id === "recommendation"
                          ? "PREVISÃO DA PRÓXIMA CESTA"
                          : "RECUPERAÇÃO · PILOTO EXPERIMENTAL"}
                      </span>
                      <h2>
                        {report.id === "recommendation"
                          ? "Recomendação com referências"
                          : "Quando o significado ainda não basta"}
                      </h2>
                    </div>
                    <ChartNoAxesColumnIncreasing size={26} />
                  </div>
                  <p>
                    {report.id === "recommendation"
                      ? `Validação temporal interna com ${count(report.users ?? 0)} clientes. Treino até o dia 61; validação nos dias 62–75.`
                      : `${count(report.products ?? 0)} produtos, ${report.queries} consultas de desenvolvimento. Rótulos automáticos por regras de nomes, sem revisão humana.`}
                  </p>
                  <div className="model-bars">
                    {Object.entries(report.models).map(([name, values]) => {
                      const value =
                        report.id === "recommendation"
                          ? values.ndcg
                          : values.all.ndcg;
                      const labels: Record<string, string> = {
                        popularity: "Popularidade",
                        repeat: "Repetição pessoal",
                        basket_cosine: "Similaridade por cesta",
                        lexical: "Busca lexical",
                        semantic: "Embeddings E5",
                        hybrid: "Busca híbrida",
                      };
                      return (
                        <div className="model-row" key={name}>
                          <span>{labels[name] ?? name}</span>
                          <div className="bar-track">
                            <span
                              style={{
                                width:
                                  (Math.max(value, 0) /
                                    Math.max(
                                      Number.EPSILON,
                                      ...Object.values(report.models).map(
                                        (model) =>
                                          report.id === "recommendation"
                                            ? model.ndcg
                                            : model.all.ndcg,
                                      ),
                                    )) *
                                    100 +
                                  "%",
                              }}
                            />
                          </div>
                          <strong>
                            {value.toLocaleString("pt-BR", {
                              minimumFractionDigits: 4,
                              maximumFractionDigits: 4,
                            })}
                          </strong>
                        </div>
                      );
                    })}
                  </div>
                  <p className="chart-caption">
                    NDCG@10 ·{" "}
                    {report.id === "recommendation"
                      ? "média por cliente"
                      : "proxy com rótulos fracos, não relevância julgada"}
                    . Valores de 0 a 1; quanto maior, melhor a posição dos itens
                    relevantes. Barras proporcionais ao maior resultado deste
                    experimento.
                  </p>
                  <div className="experiment-note">
                    <Info size={17} />
                    <p>
                      {report.id === "recommendation"
                        ? "Repetição foi a melhor referência medida. Clientes sem histórico usam popularidade como alternativa."
                        : "O piloto semântico não superou a busca lexical na média deste proxy e ainda erra em português. Não foi promovido para a busca do produto."}
                    </p>
                  </div>
                  <details>
                    <summary>Limitações e método</summary>
                    <ul>
                      {report.limitations.map((text, index) => (
                        <li key={index}>{text}</li>
                      ))}
                    </ul>
                  </details>
                </article>
              ))}
              {!reports.length && (
                <div className="empty-state">
                  {bootLoading
                    ? "Carregando os relatórios…"
                    : "Os relatórios não puderam ser carregados neste ambiente. Use “Tentar novamente” no aviso acima ou consulte a metodologia no GitHub."}
                </div>
              )}
              <div className="method-footer">
                <Database size={21} />
                <div>
                  <h3>Procedência faz parte da experiência</h3>
                  <p>
                    Delivery Hero · Singapura · catálogo histórico. Arquivos
                    verificados por SHA-256. Preços normalizados e
                    estabelecimentos anonimizados.
                  </p>
                  <a
                    href="https://github.com/luccaamp/mesa-food-discovery-agent/tree/main/docs"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Ler metodologia no GitHub <ArrowUpRight size={14} />
                  </a>
                </div>
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>
              mesa. <span>Dados reais. Contexto à vista.</span>
            </span>
            <p>
              Projeto independente · dados públicos DHRD, sem vínculo com
              Delivery Hero
            </p>
          </footer>
        </main>
      </div>
      <dialog
        aria-labelledby="detail-title"
        aria-describedby="detail-limitations"
        ref={dialog}
        onCancel={() => setDetail(null)}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
          const first = controls[0], last = controls[controls.length - 1];
          if (!first || !last) return;
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        onClick={(e) => {
          if (e.target === dialog.current) setDetail(null);
        }}
      >
        <div className="detail-content">
          {detail && (
            <>
              <button
                className="dialog-close"
                onClick={() => setDetail(null)}
                aria-label="Fechar detalhes"
              >
                <X size={20} />
              </button>
              <span className="eyebrow">EVIDÊNCIA DO CATÁLOGO</span>
              <h2 id="detail-title">{detail.name}</h2>
              <p className="detail-category">
                <CategoryIcon category={detail.primary_cuisine} />
                {detail.primary_cuisine}
              </p>
              <dl>
                <div>
                  <dt>Preço normalizado</dt>
                  <dd>{priceLabel(detail.unit_price)}</dd>
                </div>
                {detail.unit_price !== null && (
                  <div>
                    <dt>Como interpretar</dt>
                    <dd>
                      {detail.unit_price === 0
                        ? "Zero registrado na fonte; não comprova gratuidade nem preço atual."
                        : "Número sem moeda, na escala da base. Não representa reais ou dólares."}
                    </dd>
                  </div>
                )}
                <div>
                  <dt>Origem</dt>
                  <dd>Delivery Hero · Singapura</dd>
                </div>
                <div>
                  <dt>Estado dos dados</dt>
                  <dd>Catálogo histórico</dd>
                </div>
                <div>
                  <dt>Vendedor anonimizado</dt>
                  <dd className="mono">{detail.vendor_id}</dd>
                </div>
                <div>
                  <dt>Produto</dt>
                  <dd className="mono">{detail.product_id}</dd>
                </div>
                {detail.training_baskets !== undefined && (
                  <div>
                    <dt>Presença em cestas de treino</dt>
                    <dd>{count(detail.training_baskets)}</dd>
                  </div>
                )}
                {detail.reason && (
                  <div>
                    <dt>Por que foi sugerido</dt>
                    <dd>
                      {detail.reason === "basket_association"
                        ? "Associação com os itens selecionados em pedidos de treino"
                        : "Popularidade histórica nos pedidos de treino"}
                    </dd>
                  </div>
                )}
                {detail.reason === "basket_association" && (
                  <div>
                    <dt>Coocorrências com suas referências</dt>
                    <dd>
                      {count(detail.supporting_co_baskets ?? 0)} · soma por
                      referência; uma cesta pode contribuir para mais de uma
                      delas.
                    </dd>
                  </div>
                )}
              </dl>
              <div className="notice">
                <ShieldCheck size={19} />
                <p id="detail-limitations">
                  Nome, culinária e preço foram preservados da base real. Não há
                  confirmação de ingredientes, alérgenos, estoque ou entrega. O
                  desenho dos cards é gráfico, não uma foto do prato.
                </p>
              </div>
              <button
                className="primary detail-select"
                disabled={
                  !selected.some((item) => keyOf(item) === keyOf(detail)) &&
                  selected.length >= 5
                }
                onClick={() => toggle(detail)}
              >
                {selected.some((item) => keyOf(item) === keyOf(detail)) ? (
                  <>
                    <Check size={16} /> Item selecionado
                  </>
                ) : (
                  <>
                    <Bookmark size={16} /> Usar como referência
                  </>
                )}
              </button>
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
