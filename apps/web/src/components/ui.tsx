import { useEffect, useRef, type ReactNode } from "react";
import {
  Beef,
  Cake,
  Check,
  Coffee,
  CookingPot,
  Croissant,
  CupSoda,
  Drumstick,
  Fish,
  IceCreamCone,
  Pizza,
  Plus,
  Salad,
  Sandwich,
  Soup,
  UtensilsCrossed,
  Wheat,
  X,
  type LucideIcon,
} from "lucide-react";
import { amount, type Item } from "../api";

const PALETTE = [
  ["#c2502f", "#e3864f"],
  ["#17483a", "#3a8a6d"],
  ["#8a4b9c", "#c07ac9"],
  ["#b57a12", "#e3a43b"],
  ["#2f5f9e", "#5f93d6"],
  ["#9e2f4f", "#d4627f"],
  ["#4e6b2f", "#87a95a"],
  ["#5b4636", "#9a7b62"],
];

const ICONS: [RegExp, LucideIcon][] = [
  [/coffee|kopi|cafe/, Coffee],
  [/tea|drink|juice|beverage|bubble|boba/, CupSoda],
  [/pizza|italian/, Pizza],
  [/soup|ramen|pho|laksa|noodle/, Soup],
  [/salad|healthy|vegetarian|vegan/, Salad],
  [/burger|western|steak|grill|bbq|korean/, Beef],
  [/fish|seafood|sushi|japanese/, Fish],
  [/chicken|wings|fried/, Drumstick],
  [/dessert|ice cream|sweet/, IceCreamCone],
  [/cake|bakery|pastr/, Cake],
  [/bread|breakfast|cafe|croissant/, Croissant],
  [/sandwich|sub/, Sandwich],
  [/indian|curry|malay|thai|chinese|asian/, CookingPot],
  [/rice|local|hawker/, Wheat],
];

function hash(text: string) {
  let value = 0;
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0;
  return value;
}

export function cuisineStyle(cuisine: string) {
  const [from, to] = PALETTE[hash(cuisine) % PALETTE.length];
  return { background: `linear-gradient(135deg, ${from}, ${to})` };
}

export function CuisineIcon({ cuisine, size = 28 }: { cuisine: string; size?: number }) {
  const text = cuisine.toLowerCase();
  const Icon = ICONS.find(([pattern]) => pattern.test(text))?.[1] ?? UtensilsCrossed;
  return <Icon size={size} strokeWidth={1.8} aria-hidden="true" />;
}

/** Decorative art by cuisine: the dataset has no photos, so nothing pretends to be one. */
export function ItemArt({ item, size = 40, label = true, className = "" }: {
  item: Pick<Item, "primary_cuisine">;
  size?: number;
  label?: boolean;
  className?: string;
}) {
  return (
    <div className={"item-art " + className} style={cuisineStyle(item.primary_cuisine)} aria-hidden="true">
      <CuisineIcon cuisine={item.primary_cuisine} size={size} />
      {label && <span className="art-label">{item.primary_cuisine}</span>}
    </div>
  );
}

export function Price({ value }: { value: number | null }) {
  if (value === null) return <span className="price muted">Sem preço</span>;
  if (value === 0)
    return (
      <span className="price" title="Zero registrado na fonte; não significa gratuito">
        0 <small>na fonte</small>
      </span>
    );
  return (
    <span className="price" title="Preço normalizado do dataset, sem moeda">
      {amount(value)} <small>u.n.</small>
    </span>
  );
}

export function reasonLabel(reason?: string) {
  return reason === "basket_association" ? "Pedido junto" : reason === "historical_popularity" ? "Popular" : null;
}

export function ItemCard({ item, inCart, onOpen, onAdd, compact = false }: {
  item: Item;
  inCart: boolean;
  onOpen: (item: Item) => void;
  onAdd: (item: Item) => void;
  compact?: boolean;
}) {
  const reason = reasonLabel(item.reason);
  return (
    <article className="item-card">
      <button className="item-open" onClick={() => onOpen(item)} aria-label={`Ver detalhes de ${item.name}`}>
        <div style={{ position: "relative" }}>
          {reason && (
            <span className={"badge item-reason " + (item.reason === "basket_association" ? "badge-accent" : "badge-brand")}>
              {reason}
            </span>
          )}
          <ItemArt item={item} size={compact ? 30 : 40} />
        </div>
      </button>
      <div className="item-body">
        <h3 className="item-name">{item.name}</h3>
        <div className="item-meta">
          <Price value={item.unit_price} />
          <button
            className="add-btn"
            aria-pressed={inCart}
            aria-label={inCart ? `Adicionar mais ${item.name}` : `Adicionar ${item.name} à sacola`}
            onClick={() => onAdd(item)}
          >
            {inCart ? <Check size={17} /> : <Plus size={18} />}
          </button>
        </div>
      </div>
    </article>
  );
}

export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div className="item-card skeleton-card" key={index} aria-hidden="true">
          <div className="skeleton" />
          <div className="skeleton" style={{ height: 14, width: "80%" }} />
          <div className="skeleton" style={{ height: 14, width: "40%" }} />
        </div>
      ))}
    </>
  );
}

/** Modal sheet on native <dialog>, with focus kept inside while open. */
export function Sheet({ open, onClose, labelledBy, children }: {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
      (opener.current as HTMLElement | null)?.focus?.();
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby={labelledBy}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const focusable = event.currentTarget.querySelectorAll<HTMLElement>(
          "button:not(:disabled), a[href], input, select",
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      {open && (
        <>
          <button className="icon-btn sheet-close" onClick={onClose} aria-label="Fechar">
            <X size={20} />
          </button>
          {children}
        </>
      )}
    </dialog>
  );
}
