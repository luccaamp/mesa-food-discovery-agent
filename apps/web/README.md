# Mesa — interface web

React 19 + TypeScript estrito + Vite, servida pela própria API em produção
([demo](https://mesa-meal-discovery.onrender.com)). Sem chaves no navegador e
sem dados de exemplo: tudo vem do catálogo real.

## Áreas

| Área | Arquivo | O que mostra |
| --- | --- | --- |
| Início | `features/HomePage.tsx` | Culinárias e itens mais pedidos em Singapura |
| Busca | `features/SearchPage.tsx` | Busca em PT/EN com filtros de preço e culinária |
| Item | `features/ItemSheet.tsx` | Evidência do item e o que costuma ser pedido junto |
| Sacola | `features/CartPage.tsx` | Complementos sugeridos; checkout simulado |
| Assistente | `features/AssistantPanel.tsx` | Etapas do agente ao vivo (SSE), itens verificados, provedor, latência e tokens |
| Laboratório | `features/LabPage.tsx` | Comparação de provedores, red team OWASP, recomendação e busca |

Componentes e tokens do design system ficam em `components/` e `styles.css`.

## Rodar

```sh
npm --prefix apps/web ci
npm --prefix apps/web run build          # a API serve dist/
python scripts/run_local.py --cloud      # Gemini -> Groq; ou --no-llm
npm --prefix apps/web run dev            # desenvolvimento; /v1 vai para a API em 8000
```

## Testes

```sh
npm --prefix apps/web test               # componentes e utilitários
npm --prefix apps/web run e2e            # Playwright + axe, com a API em 127.0.0.1:8765
```

Os 12 testes E2E rodam em desktop e celular (Pixel 7) contra o catálogo real e
falham em qualquer violação séria ou crítica de acessibilidade (WCAG 2 A/AA).
Capturas ficam em `e2e/screenshots/` (fora do Git).
