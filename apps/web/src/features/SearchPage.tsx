import { useEffect, useRef, useState, type FormEvent } from "react";
import { Search, SearchX, Sparkles } from "lucide-react";
import { api, count, keyOf, type Discovery, type Item } from "../api";

type Result = { items: Item[]; total: number; label: string; translatedFrom: string | null; message: string };
import { ItemCard, SkeletonCards } from "../components/ui";
import { href } from "../lib/route";
import type { Cart } from "../lib/store";

type Cuisine = { name: string; products: number };

export function SearchPage({ initialQuery, initialCuisine, cuisines, cart, onOpen, onAsk }: {
  initialQuery: string;
  initialCuisine: string;
  cuisines: Cuisine[];
  cart: Cart;
  onOpen: (item: Item) => void;
  onAsk: (message: string) => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [cuisine, setCuisine] = useState(initialCuisine);
  const [level, setLevel] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);

  useEffect(() => {
    setQuery(initialQuery);
    setCuisine(initialCuisine);
  }, [initialQuery, initialCuisine]);

  useEffect(() => {
    if (initialQuery || initialCuisine) run(initialQuery || "", initialCuisine, level);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery, initialCuisine]);

  async function run(text: string, selectedCuisine: string, band: string) {
    const value = text.trim();
    if (!value && !selectedCuisine) return;
    const priceLevel = band === "" ? null : Number(band);
    const seq = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      let next: Result;
      if (!value) {
        // Browsing a cuisine: show what people actually ordered most, not a keyword match.
        const data = await api<{ items: Item[] }>("/v1/recommendations", {
          method: "POST",
          body: JSON.stringify({ cuisine: selectedCuisine, price_level: priceLevel, limit: 24 }),
        });
        next = { items: data.items, total: data.items.length, label: `Mais pedidos de ${selectedCuisine}`,
                 translatedFrom: null, message: "" };
      } else {
        const params = new URLSearchParams({ query: value, limit: "24" });
        if (selectedCuisine) params.set("cuisine", selectedCuisine);
        if (priceLevel !== null) params.set("price_level", String(priceLevel));
        const data = await api<Discovery>("/v1/discovery/search?" + params);
        const resolved = data.resolved_query ?? value;
        next = { items: data.result?.items ?? [], total: data.result?.total_matches ?? 0,
                 label: `resultados para “${resolved}”`,
                 translatedFrom: data.resolved_query && data.resolved_query !== data.query ? data.query : null,
                 message: data.message };
      }
      if (seq === sequence.current) setResult(next);
    } catch (reason) {
      if (seq === sequence.current) setError(reason instanceof Error ? reason.message : "Falha ao buscar.");
    } finally {
      if (seq === sequence.current) setLoading(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    window.location.hash = href("search", { q: query.trim(), culinaria: cuisine });
    run(query, cuisine, level);
  }

  const items = result?.items ?? [];
  return (
    <div className="page">
      <div className="search-head">
        <form className="field" role="search" onSubmit={submit}>
          <Search size={20} />
          <label htmlFor="search-input" className="sr-only">
            Buscar pratos e bebidas
          </label>
          <input
            id="search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Busque pratos ou bebidas (português ou inglês)"
            autoComplete="off"
            enterKeyHint="search"
          />
          <button className="btn btn-primary btn-sm" type="submit">
            Buscar
          </button>
        </form>
        <div className="filters" aria-label="Filtros">
          <label className="chip">
            <span className="sr-only">Culinária</span>
            <select
              value={cuisine}
              onChange={(event) => {
                setCuisine(event.target.value);
                run(query, event.target.value, level);
              }}
            >
              <option value="">Todas as culinárias</option>
              {cuisines.map((value) => (
                <option key={value.name} value={value.name}>
                  {value.name}
                </option>
              ))}
            </select>
          </label>
          <label className="chip">
            <span className="sr-only">Faixa de preço</span>
            <select
              value={level}
              onChange={(event) => {
                setLevel(event.target.value);
                run(query, cuisine, event.target.value);
              }}
            >
              <option value="">Qualquer preço</option>
              <option value="1">$ · Barato</option>
              <option value="2">Até $$ · Médio</option>
            </select>
          </label>
          {(cuisine || level) && (
            <button
              className="chip"
              onClick={() => {
                setCuisine("");
                setLevel("");
                run(query, "", "");
              }}
            >
              Limpar filtros
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="notice notice-warning" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <div className="grid" aria-busy="true">
          <SkeletonCards count={8} />
        </div>
      ) : result === null ? (
        <div className="empty">
          <Search size={36} />
          <h2>Busque como você falaria</h2>
          <p>"arroz com frango", "chá com leite", "spicy noodles". O glossário traduz o principal para o catálogo.</p>
        </div>
      ) : items.length ? (
        <>
          <div className="result-summary" role="status">
            <span>
              <strong>{count(result.total)}</strong> {result.label}
            </span>
            {result.translatedFrom && <span className="badge">traduzido de “{result.translatedFrom}”</span>}
          </div>
          <div className="grid">
            {items.map((item) => (
              <ItemCard key={keyOf(item)} item={item} inCart={cart.has(item)} onAdd={cart.add} onOpen={onOpen} />
            ))}
          </div>
        </>
      ) : (
        <div className="empty" role="status">
          <SearchX size={36} />
          <h2>Nada encontrado com esses termos</h2>
          <p>{result.message || "Tente um nome mais simples ou amplie o preço."}</p>
          <button className="btn btn-accent" onClick={() => onAsk(query || "me recomende algo")}>
            <Sparkles size={17} /> Pedir ajuda ao assistente
          </button>
        </div>
      )}
    </div>
  );
}
