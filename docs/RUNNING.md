# Rodar, reproduzir e demonstrar

## Instalar

Python 3.11+ e Node 22.15+. Na raiz do repositório:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -c requirements-api.lock -e ".[api,mcp,channels,test]"
npm --prefix apps/web ci
npm --prefix apps/web run build
```

## Dados

Com os ZIPs oficiais do DHRD, o pipeline completo está em [DATA.md](DATA.md).
Sem eles, `python scripts/fetch_deploy_artifact.py` baixa o mesmo catálogo e
artefato de recomendação usados em produção, conferidos por SHA-256.

## Iniciar

| Modo | Comando | LLM |
| --- | --- | --- |
| Padrão | `python scripts/run_local.py` | Gemini → Groq, com as chaves do ambiente (`.env.example`) |
| Sem LLM | `python scripts/run_local.py --no-llm` | Só o glossário; o modo aparece na conversa |
| Stack completa | `docker compose up --build` | App, gateway Go e Redis |
| Telegram local | `python -m meal_discovery.channels.telegram` | Long polling; apaga o webhook de produção |

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). Tudo escuta só em loopback.

## Reproduzir a análise e os experimentos

```powershell
python -m pip install -e ".[analysis]"                 # pandas, matplotlib, LightGBM
python analysis/business_analysis.py                   # números e gráficos de BUSINESS_ANALYSIS.md (~2 min)
python analysis/discovery_experiment.py                # validação do experimento de descoberta (~5 min)
python analysis/discovery_experiment.py --final-test   # teste oficial (já rodado; reproduz os mesmos números)
python analysis/agent_experiment.py --no-llm           # braços sem LLM do experimento do agente
python analysis/agent_experiment.py                    # com o agente (GROQ_API_KEY; ~30 min pela cota)
```

## Testes

| Suíte | Comando |
| --- | --- |
| Backend, agente, canais, avaliação | `python -m unittest discover -s tests` |
| Interface | `npm --prefix apps/web test` |
| Gateway Go | `cd services/whatsapp-gateway && go test -race ./...` |
| E2E com acessibilidade (servidor em 8765) | `npm --prefix apps/web run e2e` |

## Roteiro de demonstração

1. **Home:** escolha uma região em "Você está perto de"; a vitrine mostra o que
   mais se pede ali na faixa horária atual de Singapura.
2. **Assistente:** "estou com vontade de comida japonesa, algo barato", depois
   "agora uma bebida gelada". As etapas do agente aparecem ao vivo.
3. **Item:** a faixa de preço comparada à culinária e o que costuma ser pedido junto.
4. **Limites:** "sem glúten" ou "até R$ 20". As políticas explicam por que o
   catálogo não garante restrições nem converte moeda.
5. **Laboratório:** os dois experimentos, o red team e os resultados negativos.
