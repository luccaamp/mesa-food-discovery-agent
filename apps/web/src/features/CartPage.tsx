import { useEffect, useState } from "react";
import { Info, Minus, Plus, ShoppingBag, Trash2 } from "lucide-react";
import { amount, api, keyOf, type Item } from "../api";
import { ItemArt, ItemCard, Price, Sheet, SkeletonCards } from "../components/ui";
import { href } from "../lib/route";
import { seedsOf, type Cart } from "../lib/store";

export function CartPage({ cart, onOpen }: { cart: Cart; onOpen: (item: Item) => void }) {
  const [suggestions, setSuggestions] = useState<Item[] | null>(null);
  const [confirm, setConfirm] = useState(false);
  const seedKey = cart.lines.map((line) => keyOf(line.item)).join("|");

  useEffect(() => {
    if (!cart.lines.length) return;
    let active = true;
    setSuggestions(null);
    api<{ items: Item[] }>("/v1/recommendations", {
      method: "POST",
      body: JSON.stringify({ seeds: seedsOf(cart.lines.map((line) => line.item)), limit: 8 }),
    })
      .then((result) => active && setSuggestions(result.items.filter((item) => !cart.has(item))))
      .catch(() => active && setSuggestions([]));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedKey]);

  const priced = cart.lines.filter((line) => line.item.unit_price !== null);
  const subtotal = priced.reduce((sum, line) => sum + (line.item.unit_price ?? 0) * line.quantity, 0);

  if (!cart.lines.length)
    return (
      <div className="page">
        <div className="empty">
          <ShoppingBag size={40} />
          <h1 style={{ fontSize: 24 }}>Sua sacola está vazia</h1>
          <p>Adicione itens pela busca, pela home ou pelo assistente. As sugestões passam a usar o que você escolheu.</p>
          <a className="btn btn-primary" href={href("home")}>
            Explorar o catálogo
          </a>
        </div>
      </div>
    );

  return (
    <div className="page">
      <h1 style={{ fontSize: 28, marginBottom: 16 }}>Sacola</h1>
      <div className="cart-layout">
        <div style={{ display: "grid", gap: 20, minWidth: 0 }}>
          <section className="panel" aria-label="Itens na sacola">
            {cart.lines.map((line) => (
              <div className="cart-line" key={keyOf(line.item)}>
                <ItemArt item={line.item} size={24} label={false} />
                <div style={{ minWidth: 0 }}>
                  <button className="item-open" onClick={() => onOpen(line.item)}>
                    <strong className="item-name" style={{ minHeight: 0 }}>
                      {line.item.name}
                    </strong>
                  </button>
                  <Price value={line.item.unit_price} />
                </div>
                <div className="stepper" role="group" aria-label={`Quantidade de ${line.item.name}`}>
                  <button onClick={() => cart.change(line.item, -1)} aria-label="Diminuir">
                    {line.quantity === 1 ? <Trash2 size={15} /> : <Minus size={15} />}
                  </button>
                  <span aria-live="polite">{line.quantity}</span>
                  <button onClick={() => cart.change(line.item, 1)} aria-label="Aumentar">
                    <Plus size={15} />
                  </button>
                </div>
              </div>
            ))}
          </section>
          <section aria-label="Sugestões para completar">
            <div className="section-head">
              <div>
                <h2>Complete seu pedido</h2>
                <p>Pedido junto com os itens da sua sacola em cestas reais</p>
              </div>
            </div>
            <div className="rail">
              {suggestions === null ? (
                <SkeletonCards count={4} />
              ) : suggestions.length ? (
                suggestions.map((item) => (
                  <ItemCard key={keyOf(item)} item={item} inCart={cart.has(item)} onAdd={cart.add} onOpen={onOpen} />
                ))
              ) : (
                <p className="muted">Sem associações suficientes para estes itens.</p>
              )}
            </div>
          </section>
        </div>
        <aside className="panel" aria-label="Resumo">
          <h2 style={{ marginBottom: 8 }}>Resumo</h2>
          <div className="summary-row">
            <span>Itens</span>
            <span>{cart.count}</span>
          </div>
          <div className="summary-row total">
            <span>Subtotal</span>
            <span>{amount(Number(subtotal.toPrecision(6)))} u.n.</span>
          </div>
          {priced.length < cart.lines.length && <p className="muted" style={{ fontSize: 12 }}>Itens sem preço não entram no subtotal.</p>}
          <p className="notice" style={{ margin: "12px 0" }}>
            <Info size={15} /> Preços normalizados do dataset, sem moeda. Sem entrega ou pagamento.
          </p>
          <button className="btn btn-primary" style={{ width: "100%" }} onClick={() => setConfirm(true)}>
            Finalizar pedido de demonstração
          </button>
          <button className="btn btn-ghost btn-sm" style={{ width: "100%", marginTop: 8 }} onClick={cart.clear}>
            Esvaziar sacola
          </button>
        </aside>
      </div>
      <Sheet open={confirm} onClose={() => setConfirm(false)} labelledBy="demo-title">
        <div className="sheet-body" style={{ paddingTop: 48 }}>
          <h2 id="demo-title">Este é um catálogo histórico</h2>
          <p className="muted">
            O Mesa é uma demonstração de descoberta sobre pedidos históricos reais. Não há restaurantes, pagamento ou entrega
            de verdade. Nenhum dado seu foi enviado: a sacola existe só neste navegador.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => {
              cart.clear();
              setConfirm(false);
            }}
          >
            Entendi, esvaziar a sacola
          </button>
        </div>
      </Sheet>
    </div>
  );
}
