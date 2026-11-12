import { useCallback, useEffect, useState } from "react";
import { keyOf, type Item } from "../api";

export type CartLine = { item: Item; quantity: number };

function read<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage can be unavailable (private mode); the session still works */
  }
}

/** The order region the person picked (DHRD geohash); kept only in this browser. */
export function useRegion() {
  const [region, setRegion] = useState<string>(() => read("mesa.region", ""));
  useEffect(() => write("mesa.region", region), [region]);
  return [region, setRegion] as const;
}

/** Session personalization lives only in this browser: no account, no server-side profile. */
export function useCart() {
  const [lines, setLines] = useState<CartLine[]>(() => read("mesa.cart", []));
  const [recent, setRecent] = useState<Item[]>(() => read("mesa.recent", []));
  useEffect(() => write("mesa.cart", lines), [lines]);
  useEffect(() => write("mesa.recent", recent), [recent]);

  const add = useCallback((item: Item) => {
    setLines((current) => {
      const found = current.find((line) => keyOf(line.item) === keyOf(item));
      return found
        ? current.map((line) => (line === found ? { ...line, quantity: Math.min(line.quantity + 1, 20) } : line))
        : [...current, { item, quantity: 1 }];
    });
    setRecent((current) => [item, ...current.filter((value) => keyOf(value) !== keyOf(item))].slice(0, 12));
  }, []);
  const change = useCallback((item: Item, delta: number) => {
    setLines((current) =>
      current
        .map((line) =>
          keyOf(line.item) === keyOf(item) ? { ...line, quantity: Math.min(line.quantity + delta, 20) } : line,
        )
        .filter((line) => line.quantity > 0),
    );
  }, []);
  const clear = useCallback(() => setLines([]), []);
  const has = useCallback((item: Item) => lines.some((line) => keyOf(line.item) === keyOf(item)), [lines]);
  const count = lines.reduce((sum, line) => sum + line.quantity, 0);
  return { lines, recent, add, change, clear, has, count };
}

export type Cart = ReturnType<typeof useCart>;

/** Up to five distinct references for basket-based recommendations. */
export function seedsOf(items: Item[]) {
  return items.slice(0, 5).map(({ vendor_id, product_id }) => ({ vendor_id, product_id }));
}
