# Executar o Mesa localmente

## Instalar

Python 3.11+ e Node 22.15+ (Node 24 só para o n8n). Na raiz do repositório:

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

1. **Busca:** "chá com leite" ou "arroz com frango". A consulta é traduzida para
   os termos do catálogo e os nomes originais aparecem.
2. **Item:** a evidência (chave, culinária, preço normalizado) e o que costuma
   ser pedido junto. Preço 0 significa preço não registrado na fonte, não gratuidade.
3. **Assistente:** "algo picante até 0,005", depois "agora uma bebida gelada".
   As etapas do agente aparecem ao vivo, com provedor, latência e tokens.
4. **Limites:** "sem glúten" ou "em reais". As políticas explicam por que o
   catálogo não garante restrições nem converte moeda.
5. **Laboratório:** comparação de provedores, red team OWASP e o resultado
   negativo do piloto semântico.
6. **MCP:** as mesmas ferramentas em um cliente MCP ([MCP.md](MCP.md)).

## Garantias

- Itens, preços e culinárias vêm só das ferramentas; a frase do modelo passa
  pela verificação de grounding antes de aparecer.
- O servidor não guarda histórico na web: o contexto viaja em cada requisição.
  Nos canais de mensagem, o contexto expira em 24 h e pode ser apagado pelo usuário.
- Logs não registram mensagens, corpos de requisição, query strings ou chaves.
- Não há estudo com pessoas nem medição de impacto comercial; as avaliações são
  automatizadas e estão em [evaluations/](../evaluations/README.md).
