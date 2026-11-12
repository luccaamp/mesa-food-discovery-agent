# Executar o Mesa localmente

## Instalar

Python 3.11+ e Node 22.15+. Na raiz do repositório:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -c requirements-api.lock -e ".[api,mcp,channels,test]"
npm --prefix apps/web ci
npm --prefix apps/web run build
```

## Preparar os dados

Com os ZIPs oficiais verificados e extraídos ([dados](../data/README.md)):

```powershell
python -m meal_discovery prepare-official-singapore --output data/processed/singapore-official-v1.sqlite
python -m meal_discovery build-catalog --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-catalog-v1.sqlite
python scripts/build_serving_model.py --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-serving-v1.sqlite
python scripts/fetch_local_llm.py     # opcional: Qwen local, ~1,12 GB
```

Os dois artefatos pequenos que o produto usa já estão versionados em
`src/meal_discovery/data/` e podem ser refeitos a partir dos dados oficiais:

```powershell
python scripts/build_price_bands.py          # faixas de preço por culinária
python scripts/build_context_popularity.py   # mais pedidos por região e horário
```

## Análise e experimento

```powershell
python -m pip install -e ".[analysis]"       # pandas, matplotlib, LightGBM
python analysis/business_analysis.py         # números e gráficos de docs/BUSINESS_ANALYSIS.md
python analysis/discovery_experiment.py      # validação do Experimento 004 (~5 min)
python analysis/discovery_experiment.py --final-test   # teste oficial, rodado uma vez
```

As ferramentas recusam sobrescrever saídas existentes. Downloads são fixados por
revisão, tamanho e SHA-256. Sem os ZIPs, `scripts/fetch_deploy_artifact.py`
baixa o mesmo catálogo e modelo de serving usados em produção.

## Iniciar

| Modo | Comando | LLM |
| --- | --- | --- |
| Nuvem | `python scripts/run_local.py --cloud` | Gemini → Groq (chaves do ambiente) |
| Local | `python scripts/run_local.py` | Qwen 2.5 1,5B via llama.cpp em 8081 |
| Sem LLM | `python scripts/run_local.py --no-llm` | Só glossário; o modo aparece na conversa |
| Stack completa | `docker compose up --build` | App, gateway Go e Redis |
| Telegram local | `python -m meal_discovery.channels.telegram` | Long polling; apaga o webhook de produção |

Abrir [http://127.0.0.1:8000](http://127.0.0.1:8000). Tudo escuta só em
loopback; Ctrl+C encerra os processos iniciados. O launcher do Qwen foi testado
no Windows; em outro sistema, suba um servidor compatível com a API da OpenAI
em 8081.

## O que mostrar

1. **Home:** escolha uma região em "Você está perto de". A vitrine muda para o
   que mais se pede ali na faixa horária atual de Singapura.
2. **Busca:** "chá com leite" ou "arroz com frango". A consulta é traduzida para
   os termos do catálogo, e o filtro de preço é por faixa ($, $$).
3. **Item:** a faixa de preço comparada à culinária ("mais barato que 72% dos
   itens de pizza") e o que costuma ser pedido junto.
4. **Assistente:** "pizza barata", depois "agora uma bebida gelada", depois
   "me recomende algo". As etapas do agente aparecem ao vivo.
5. **Limites:** "sem glúten" ou "até R$ 20". As políticas explicam por que o
   catálogo não garante restrições nem converte moeda.
6. **Laboratório:** o experimento de descoberta, comparação de provedores, red
   team OWASP e os resultados negativos.
7. **MCP:** as mesmas ferramentas em um cliente MCP ([MCP.md](MCP.md)).

## Garantias

- Itens, preços e culinárias vêm só das ferramentas; a frase do modelo passa
  pela verificação de grounding antes de aparecer.
- O servidor não guarda histórico na web: o contexto viaja em cada requisição.
  Nos canais de mensagem, o contexto expira em 24 h e pode ser apagado pelo usuário.
- Logs não registram mensagens, corpos de requisição, query strings ou chaves.
- Não há estudo com pessoas nem medição de impacto comercial; as avaliações são
  automatizadas e estão em [evaluations/](../evaluations/README.md).
