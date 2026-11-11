import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FlaskConical, House, MapPin, Search, ShoppingBag, Sparkles } from "lucide-react";
import { api, type Item, type Meta } from "./api";
import { AssistantPanel } from "./features/AssistantPanel";
import { CartPage } from "./features/CartPage";
import { HomePage } from "./features/HomePage";
import { ItemSheet } from "./features/ItemSheet";
import { LabPage } from "./features/LabPage";
import { SearchPage } from "./features/SearchPage";
import { href, useRoute, type Route } from "./lib/route";
import { useCart } from "./lib/store";

type Cuisine = { name: string; products: number };

const NAV: { page: Route["page"]; label: string; icon: typeof House }[] = [
  { page: "home", label: "Início", icon: House },
  { page: "search", label: "Buscar", icon: Search },
  { page: "cart", label: "Sacola", icon: ShoppingBag },
  { page: "lab", label: "Lab", icon: FlaskConical },
];

export default function App() {
  const route = useRoute();
  const baseCart = useCart();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [cuisines, setCuisines] = useState<Cuisine[]>([]);
  const [detail, setDetail] = useState<Item | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const toastTimer = useRef<number>(undefined);

  useEffect(() => {
    api<Meta>("/v1/catalog/meta").then(setMeta).catch(() => undefined);
    api<{ cuisines: Cuisine[] }>("/v1/catalog/cuisines")
      .then((value) => setCuisines(value.cuisines))
      .catch(() => undefined);
  }, []);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 1800);
  }, []);

  // Adding to the bag always confirms with a toast, from any surface.
  const cart = useMemo(
    () => ({
      ...baseCart,
      add: (item: Item) => {
        baseCart.add(item);
        notify(`${item.name} na sacola`);
      },
    }),
    [baseCart, notify],
  );

  const ask = useCallback((message: string) => {
    setPending(message);
    setAssistantOpen(true);
  }, []);

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Pular para o conteúdo
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="logo" href={href("home")} aria-label="Mesa, página inicial" style={{ textDecoration: "none" }}>
            mesa<span>.</span>
          </a>
          <span className="location">
            <MapPin size={14} /> Singapura · catálogo histórico
          </span>
          <nav className="topnav" aria-label="Principal">
            {NAV.filter((entry) => entry.page !== "cart").map((entry) => (
              <a key={entry.page} href={href(entry.page)} aria-current={route.page === entry.page ? "page" : undefined}>
                {entry.label}
              </a>
            ))}
          </nav>
          <div className="topbar-actions">
            <a className="icon-btn" href={href("search")} aria-label="Buscar">
              <Search size={20} />
            </a>
            <a className="icon-btn" href={href("cart")} aria-label={`Sacola, ${cart.count} itens`}>
              <ShoppingBag size={20} />
              {cart.count > 0 && <span className="count-badge">{cart.count}</span>}
            </a>
          </div>
        </div>
      </header>

      <main id="main" tabIndex={-1}>
        {route.page === "home" && <HomePage cart={cart} cuisines={cuisines} onAsk={ask} onOpen={setDetail} />}
        {route.page === "search" && (
          <SearchPage
            initialQuery={route.query}
            initialCuisine={route.cuisine}
            cuisines={cuisines}
            cart={cart}
            onOpen={setDetail}
            onAsk={ask}
          />
        )}
        {route.page === "cart" && <CartPage cart={cart} onOpen={setDetail} />}
        {route.page === "lab" && <LabPage meta={meta} />}
      </main>

      <footer className="footer">
        mesa. Projeto independente sobre o dataset público DHRD (Delivery Hero, RecSys 2023), sem vínculo com a empresa.
        Preços normalizados, sem moeda. Nomes não comprovam ingredientes ou alérgenos.
      </footer>

      {!assistantOpen && (
        <button className="ask-fab" onClick={() => setAssistantOpen(true)}>
          <Sparkles size={18} /> Pergunte à Mesa
        </button>
      )}
      <AssistantPanel
        open={assistantOpen}
        onClose={() => setAssistantOpen(false)}
        pending={pending}
        onPendingHandled={() => setPending(null)}
        cart={cart}
        onOpen={setDetail}
      />
      <ItemSheet item={detail} cart={cart} onClose={() => setDetail(null)} onOpen={setDetail} />

      <nav className="bottomnav" aria-label="Principal">
        {NAV.map(({ page, label, icon: Icon }) => (
          <a key={page} href={href(page)} aria-current={route.page === page ? "page" : undefined}>
            <Icon size={22} />
            {label}
            {page === "cart" && cart.count > 0 && <span className="count-badge">{cart.count}</span>}
          </a>
        ))}
      </nav>
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
