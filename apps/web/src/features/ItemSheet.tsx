import { useEffect, useState } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import { api, count, keyOf, priceLabel, type Item } from "../api";
import { ItemArt, ItemCard, Sheet, SkeletonCards } from "../components/ui";
import type { Cart } from "../lib/store";

export function ItemSheet({ item, cart, onClose, onOpen }: {
  item: Item | null;
  cart: Cart;
  onClose: () => void;
  onOpen: (item: Item) => void;
}) {
  const [pairs, setPairs] = useState<Item[] | null>(null);
  useEffect(() => {
    if (!item) return;
    let active = true;
    setPairs(null);
    api<{ items: Item[] }>("/v1/recommendations", {
      method: "POST",
      body: JSON.stringify({ seeds: [{ vendor_id: item.vendor_id, product_id: item.product_id }], limit: 4 }),
    })
      .then((result) => active && setPairs(result.items.filter((value) => keyOf(value) !== keyOf(item))))
      .catch(() => active && setPairs([]));
    return () => {
      active = false;
    };
  }, [item]);

  return (
    <Sheet open={item !== null} onClose={onClose} labelledBy="item-title">
      {item && (
        <>
          <ItemArt item={item} size={56} className="sheet-art" />
          <div className="sheet-body">
            <div style={{ display: "grid", gap: 6, paddingTop: 16 }}>
              <span className="badge badge-brand" style={{ justifySelf: "start", textTransform: "capitalize" }}>
                {item.primary_cuisine}
              </span>
              <h2 id="item-title">{item.name}</h2>
            </div>
            <dl className="facts">
              <div>
                <dt>Preço normalizado</dt>
                <dd>{priceLabel(item.unit_price)}</dd>
              </div>
              <div>
                <dt>Origem</dt>
                <dd>Delivery Hero · Singapura</dd>
              </div>
              {item.reason && (
                <div className="wide">
                  <dt>Por que apareceu</dt>
                  <dd>
                    {item.reason === "basket_association"
                      ? `Pedido junto com o que você escolheu em ${count(item.supporting_co_baskets ?? 0)} cestas reais`
                      : `Popular: presente em ${count(item.training_baskets ?? 0)} cestas de treino`}
                  </dd>
                </div>
              )}
              <div className="wide">
                <dt>Identificadores anonimizados</dt>
                <dd className="mono">
                  {item.vendor_id} · {item.product_id}
                </dd>
              </div>
            </dl>
            <button className="btn btn-primary" onClick={() => cart.add(item)}>
              <Plus size={18} /> {cart.has(item) ? "Adicionar mais um" : "Adicionar à sacola"}
            </button>
            <section aria-labelledby="pairs-title" style={{ display: "grid", gap: 10 }}>
              <h3 id="pairs-title">Costuma ser pedido junto</h3>
              <div className="mini-rail">
                {pairs === null ? (
                  <SkeletonCards count={3} />
                ) : pairs.length ? (
                  pairs.map((pair) => (
                    <ItemCard key={keyOf(pair)} item={pair} compact inCart={cart.has(pair)} onAdd={cart.add} onOpen={onOpen} />
                  ))
                ) : (
                  <p className="muted">Sem associações suficientes para este item.</p>
                )}
              </div>
            </section>
            <p className="notice">
              <ShieldCheck size={16} />
              Nome, culinária e preço vêm do catálogo histórico real. Não há confirmação de ingredientes, alérgenos,
              estoque ou entrega. A arte é ilustrativa, não uma foto do prato.
            </p>
          </div>
        </>
      )}
    </Sheet>
  );
}
