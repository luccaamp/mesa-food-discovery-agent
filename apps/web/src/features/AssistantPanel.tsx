import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Check, LoaderCircle, RotateCcw, Search, Send, Sparkles, Wand2, X } from "lucide-react";
import { fallbackMessage, keyOf, type Chat, type Context, type Item } from "../api";
import { ItemCard } from "../components/ui";
import { streamAgent, type AgentEvent } from "../lib/sse";
import { seedsOf, type Cart } from "../lib/store";

type Turn =
  | { role: "user"; text: string }
  | { role: "bot"; text: string; steps: AgentEvent[]; response?: Chat; pending: boolean; error?: boolean };

const EMPTY: Context = { last_query: null, cuisine: null, min_price: null, max_price: null, price_level: null, selected_items: [] };
const QUICK = ["Me recomende algo", "Algo com frango", "Bebida gelada", "Mais barato"];

const PROVIDERS: Record<string, string> = { gemini: "Gemini", groq: "Groq", local: "Qwen local", openai: "OpenAI" };

function describeStep(step: AgentEvent) {
  if (step.type === "plan")
    return step.tools.length
      ? `${PROVIDERS[step.provider ?? ""] ?? "Modelo"} decidiu usar ${step.tools.map((t) => (t === "search_catalog" ? "a busca" : "as recomendações")).join(" e ")}`
      : `${PROVIDERS[step.provider ?? ""] ?? "Modelo"} escreveu a resposta`;
  if (step.type === "tool") {
    const query = step.arguments.query as string | undefined;
    const name = step.name === "search_catalog" ? `Buscou “${query}”` : "Calculou recomendações por cestas";
    return `${name} · ${step.result_count} itens · ${Math.round(step.duration_ms)} ms`;
  }
  if (step.type === "fallback") return "IA indisponível: usando o glossário, sem inferência";
  return "";
}

export function AssistantPanel({ open, onClose, pending, onPendingHandled, cart, onOpen }: {
  open: boolean;
  onClose: () => void;
  pending: string | null;
  onPendingHandled: () => void;
  cart: Cart;
  onOpen: (item: Item) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [context, setContext] = useState<Context>(EMPTY);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const sending = useRef(false); // synchronous guard: state updates are async

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);
  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 50);
  }, [open]);
  useEffect(() => {
    if (open && pending && !busy) {
      send(pending);
      onPendingHandled();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pending]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && open && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function updateLast(change: (turn: Extract<Turn, { role: "bot" }>) => Partial<Extract<Turn, { role: "bot" }>>) {
    setTurns((current) => {
      const copy = [...current];
      const last = copy[copy.length - 1];
      if (last?.role === "bot") copy[copy.length - 1] = { ...last, ...change(last) };
      return copy;
    });
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending.current) return;
    sending.current = true;
    setDraft("");
    setBusy(true);
    setTurns((current) => [...current, { role: "user", text: message }, { role: "bot", text: "", steps: [], pending: true }]);
    controller.current = new AbortController();
    try {
      const response = await streamAgent(
        message,
        { ...context, selected_items: seedsOf(cart.lines.map((line) => line.item)) },
        (event) => {
          if (event.type !== "result") updateLast((turn) => ({ steps: [...turn.steps, event] }));
        },
        controller.current.signal,
      );
      setContext(response.context);
      updateLast(() => ({ text: response.answer, response, pending: false }));
    } catch (error) {
      updateLast(() => ({
        text: error instanceof Error ? error.message : "Não consegui concluir. Tente novamente.",
        pending: false,
        error: true,
      }));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  function reset() {
    controller.current?.abort();
    setTurns([]);
    setContext(EMPTY);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }

  if (!open) return null;
  return (
    <aside className="assistant" role="dialog" aria-modal="true" aria-labelledby="assistant-title">
      <header className="assistant-head">
        <span className="avatar">
          <Sparkles size={18} />
        </span>
        <div>
          <strong id="assistant-title">Assistente Mesa</strong>
          <small>Busca no catálogo real · cada item com evidência</small>
        </div>
        {turns.length > 0 && (
          <button className="icon-btn" onClick={reset} aria-label="Nova conversa" title="Nova conversa">
            <RotateCcw size={18} />
          </button>
        )}
        <button className="icon-btn" onClick={onClose} aria-label="Fechar assistente">
          <X size={20} />
        </button>
      </header>

      <div className="thread" aria-live="polite">
        {turns.length === 0 && (
          <div className="empty">
            <Wand2 size={32} />
            <h2>Não sabe o que pedir?</h2>
            <p>
              Diga um prato, uma vontade ou um limite de preço. Se houver itens na sacola, as sugestões usam o que
              costuma ser pedido junto com eles.
            </p>
          </div>
        )}
        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <p key={index} className="bubble bubble-user">
              {turn.text}
            </p>
          ) : (
            <div key={index} className="turn">
              {turn.steps.length > 0 && (
                <ul className="steps" aria-label="Etapas do assistente">
                  {turn.steps.map((step, stepIndex) => (
                    <li key={stepIndex}>
                      {step.type === "fallback" ? <AlertTriangle size={13} /> : step.type === "tool" ? <Search size={13} /> : <Check size={13} />}
                      {describeStep(step)}
                    </li>
                  ))}
                </ul>
              )}
              {turn.pending ? (
                <p className="bubble bubble-bot muted">
                  <LoaderCircle size={15} className="spin" style={{ verticalAlign: "-2px" }} /> Consultando o catálogo…
                </p>
              ) : (
                <p className={"bubble bubble-bot" + (turn.error ? " notice-warning" : "")}>{turn.text}</p>
              )}
              {turn.response?.fallback_reason && (
                <p className="notice notice-warning">
                  <AlertTriangle size={15} /> {fallbackMessage(turn.response)}
                </p>
              )}
              {turn.response && turn.response.items.length > 0 && (
                <div className="mini-rail">
                  {turn.response.items.map((item) => (
                    <ItemCard key={keyOf(item)} item={item} compact inCart={cart.has(item)} onAdd={cart.add} onOpen={onOpen} />
                  ))}
                </div>
              )}
              {turn.response && (
                <p className="trace">
                  {turn.response.planner === "glossary_fallback"
                    ? "Glossário explícito"
                    : turn.response.planner.endsWith("_agent")
                      ? `Agente · ${turn.response.model}`
                      : "Regra explícita, sem modelo"}
                  {" · "}
                  {Math.round(turn.response.elapsed_ms)} ms
                  {turn.response.usage?.total_tokens ? ` · ${turn.response.usage.total_tokens} tokens` : ""}
                </p>
              )}
            </div>
          ),
        )}
        <div ref={end} />
      </div>

      <div className="composer">
        <div className="quick">
          {QUICK.map((text) => (
            <button key={text} className="chip" onClick={() => send(text)} disabled={busy}>
              {text}
            </button>
          ))}
        </div>
        <form onSubmit={submit}>
          <label className="field">
            <span className="sr-only">Mensagem</span>
            <input
              ref={input}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ex.: quero sopa de peixe"
              maxLength={500}
              autoComplete="off"
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy || !draft.trim()} aria-label="Enviar">
            {busy ? <LoaderCircle size={18} className="spin" /> : <Send size={18} />}
          </button>
        </form>
      </div>
    </aside>
  );
}
