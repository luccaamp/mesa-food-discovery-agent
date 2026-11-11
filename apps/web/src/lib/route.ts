import { useEffect, useState } from "react";

export type Route = { page: "home" | "search" | "cart" | "lab"; query: string; cuisine: string };

export function parseRoute(hash: string): Route {
  const [path, search = ""] = hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(search);
  const page = path === "buscar" ? "search" : path === "sacola" ? "cart" : path === "lab" ? "lab" : "home";
  return { page, query: params.get("q") ?? "", cuisine: params.get("culinaria") ?? "" };
}

export function href(page: Route["page"], params: Record<string, string> = {}) {
  const path = { home: "", search: "buscar", cart: "sacola", lab: "lab" }[page];
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value)).toString();
  return `#/${path}${query ? "?" + query : ""}`;
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => {
      setRoute(parseRoute(window.location.hash));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
