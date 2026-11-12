import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Database, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { api, keyOf, type Item } from "../api";
import { CuisineIcon, ItemCard, SkeletonCards, cuisineStyle } from "../components/ui";
import { href } from "../lib/route";
import { seedsOf, type Cart } from "../lib/store";

const SUGGESTIONS = ["Pizza barata", "Arroz com frango", "Chá com leite gelado", "Me recomende algo"];

type Cuisine = { name: string; products: number };
type Region = { id: string; name: string; orders: number };
type Regions = { regions: Region[]; slot: string; slot_label: string };

function Rail({ title, subtitle, request, cart, onOpen, deps }: {
  title: string;
  subtitle?: string;
  request: () => Promise<Item[]>;
  cart: Cart;
  onOpen: (item: Item) => void;
  deps: unknown[];
}) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setItems(null);
    setFailed(false);
    request()
      .then((value) => active && setItems(value))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  if (failed || (items && !items.length)) return null;
  return (
    <section className="section" aria-label={title}>
      <div className="section-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
      </div>
      <div className="rail">
        {items === null ? (
          <SkeletonCards count={5} />
        ) : (
          items.map((item) => (
            <ItemCard key={keyOf(item)} item={item} inCart={cart.has(item)} onAdd={cart.add} onOpen={onOpen} />
          ))
        )}
      </div>
    </section>
  );
}

/** What people order in the chosen region at this time of day (Experiment 004). */
function PopularHere({ region, onRegion, cart, onOpen }: {
  region: string;
  onRegion: (region: string) => void;
  cart: Cart;
  onOpen: (item: Item) => void;
}) {
  const [regions, setRegions] = useState<Regions | null>(null);
  useEffect(() => {
    api<Regions>("/v1/discovery/regions").then(setRegions).catch(() => undefined);
  }, []);
  const name = regions?.regions.find((value) => value.id === region)?.name;
  const when = regions?.slot_label ?? "agora";
  return (
    <>
      <div className="region-picker">
        <MapPin size={18} aria-hidden="true" />
        <label htmlFor="region">Você está perto de</label>
        <select id="region" className="chip" value={region} onChange={(event) => onRegion(event.target.value)}>
          <option value="">Singapura inteira</option>
          {regions?.regions.map((value) => (
            <option key={value.id} value={value.id}>
              {value.name}
            </option>
          ))}
        </select>
      </div>
      <Rail
        title={name ? `Em alta perto de ${name} ${when}` : `Em alta em Singapura ${when}`}
        subtitle="O que mais se pede nesta região e faixa horária, em pedidos reais."
        request={() => recommend({ region: region || null })}
        deps={[region]}
        cart={cart}
        onOpen={onOpen}
      />
    </>
  );
}

const recommend = (body: Record<string, unknown>) =>
  api<{ items: Item[] }>("/v1/recommendations", { method: "POST", body: JSON.stringify({ limit: 10, ...body }) }).then(
    (result) => result.items,
  );

export function HomePage({ cart, cuisines, onAsk, onOpen, region, onRegion }: {
  cart: Cart;
  cuisines: Cuisine[];
  onAsk: (message: string) => void;
  onOpen: (item: Item) => void;
  region: string;
  onRegion: (region: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const top = [...cuisines].sort((a, b) => b.products - a.products).slice(0, 12);
  const anchor = cart.recent[0];
  const recentKey = cart.recent.map(keyOf).join("|");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) onAsk(draft.trim());
    setDraft("");
  }

  return (
    <div className="page">
      <section className="hero">
        <span className="eyebrow">Singapura · catálogo histórico real</span>
        <h1>O que vamos pedir hoje?</h1>
        <p>
          Conte o que você quer — prato, vontade ou orçamento. O assistente busca entre mais de um milhão de itens reais
          e mostra de onde veio cada sugestão.
        </p>
        <form className="hero-ask" onSubmit={submit} role="search">
          <label htmlFor="hero-ask" className="sr-only">
            Pergunte ao assistente
          </label>
          <input
            id="hero-ask"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ex.: algo picante com noodles"
            autoComplete="off"
          />
          <button className="btn btn-accent" type="submit">
            <Sparkles size={17} /> Perguntar
          </button>
        </form>
        <div className="suggestions">
          {SUGGESTIONS.map((text) => (
            <button key={text} className="chip" onClick={() => onAsk(text)}>
              {text}
            </button>
          ))}
        </div>
      </section>

      <PopularHere region={region} onRegion={onRegion} cart={cart} onOpen={onOpen} />

      {top.length > 0 && (
        <section className="section" aria-label="Culinárias">
          <div className="section-head">
            <h2>Explore por culinária</h2>
            <a href={href("search")} className="muted" style={{ fontSize: 14 }}>
              Buscar tudo <ArrowRight size={14} style={{ verticalAlign: "middle" }} />
            </a>
          </div>
          <div className="cuisine-rail">
            {top.map((cuisine) => (
              <a key={cuisine.name} className="cuisine" href={href("search", { culinaria: cuisine.name })}>
                <span style={cuisineStyle(cuisine.name)}>
                  <CuisineIcon cuisine={cuisine.name} size={26} />
                </span>
                <span>{cuisine.name}</span>
              </a>
            ))}
          </div>
        </section>
      )}

      {anchor && (
        <Rail
          title={`Porque você escolheu ${anchor.name}`}
          subtitle="Itens pedidos junto nas mesmas cestas reais"
          request={() => recommend({ seeds: seedsOf(cart.recent) })}
          deps={[recentKey]}
          cart={cart}
          onOpen={onOpen}
        />
      )}
      {cart.recent.length > 1 && (
        <section className="section" aria-label="Vistos recentemente">
          <div className="section-head">
            <h2>Pedir de novo</h2>
          </div>
          <div className="rail">
            {cart.recent.map((item) => (
              <ItemCard key={keyOf(item)} item={item} inCart={cart.has(item)} onAdd={cart.add} onOpen={onOpen} />
            ))}
          </div>
        </section>
      )}

      {top.slice(0, 2).map((cuisine) => (
        <Rail
          key={cuisine.name}
          title={`Destaques de ${cuisine.name}`}
          request={() => recommend({ cuisine: cuisine.name })}
          deps={[cuisine.name]}
          cart={cart}
          onOpen={onOpen}
        />
      ))}

      <section className="section value-strip" aria-label="Como o Mesa funciona">
        <div>
          <Database size={22} />
          <p>
            <strong>Dados reais, não inventados</strong>
            1.066.840 itens reais de Singapura, do dataset público da Delivery Hero (RecSys 2023).
          </p>
        </div>
        <div>
          <Sparkles size={22} />
          <p>
            <strong>IA que usa ferramentas</strong>
            O assistente consulta o catálogo; nenhum item ou preço sai da imaginação do modelo.
          </p>
        </div>
        <div>
          <ShieldCheck size={22} />
          <p>
            <strong>Personalização sem conta</strong>
            Suas escolhas ficam só neste navegador. Nenhum perfil é enviado ou guardado no servidor.
          </p>
        </div>
      </section>
    </div>
  );
}
