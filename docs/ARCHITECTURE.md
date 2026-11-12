# Arquitetura

## Visão geral

Dois processos e uma fila. A **API em Python** (FastAPI) concentra o domínio, o
agente e a interface React empacotada no mesmo container; um **gateway em Go**
recebe os webhooks de mensageria e os entrega por **Redis Streams** a um worker
que roda o mesmo agente. O núcleo de IA segue portas e adaptadores: o agente
depende do contrato `ChatModel`, não de um provedor.

```text
Interface (React)        apps/web                    Telegram / WhatsApp
      │ HTTP + SSE                                         │ webhook
Entrada (FastAPI)        api.py, api_models.py       Gateway Go (services/whatsapp-gateway)
      │                  cloud_limits.py               segredo/HMAC, deduplicação, XADD
      │                                                    │
      │                                              Redis Stream ──► channels/ (worker)
      ▼                                                    │
Aplicação                agent/       grafo LangGraph + grounding  ◄─┘
                         policies.py  regras antes do modelo
                         privacy.py   mascaramento antes do LLM
                         planner.py   modo planejador (saída estruturada)
      │ porta ChatModel              │ ferramentas somente leitura (tools.py, mcp_server.py)
Adaptadores LLM          llm/        Catálogo e recomendação
  gemini.py                            catalog.py   SQLite FTS5/BM25
  openai_compatible.py                 serving.py   coocorrência + popularidade
    (Groq, Qwen local, OpenAI)         discovery.py glossário PT/EN
  resilience.py, registry.py
      │
Transversal              observability.py  métricas Prometheus, traces OpenTelemetry
Dados offline            dataset.py, singapore.py, benchmark.py, deployment.py
```

## Fluxo de uma mensagem

1. **Políticas determinísticas** rodam primeiro: pedidos de garantia alimentar,
   tentativas de injeção, saudações e refinamentos de preço não chegam ao modelo.
2. **Planejamento:** uma chamada com saída estruturada (`PLAN_SCHEMA`) escolhe
   `search_catalog`, `recommend_items` ou `clarify` e palavras-chave em inglês.
   O texto do usuário é tratado como dado, não como instrução.
3. **Ferramentas:** a busca e a recomendação leem o catálogo em modo somente
   leitura. A resposta é montada a partir desses resultados.
4. **Rastro:** a resposta inclui ferramentas chamadas, argumentos, duração,
   provedor que respondeu, tokens e, se houve, o motivo do fallback.

## Agente (LangGraph)

`POST /v1/agent` e `POST /v1/agent/stream` (Server-Sent Events) executam um
agente em que **o modelo escolhe as ferramentas** por tool calling:

```text
guard ──(política respondeu)──────────────────────────► fim
  │
agent ──(chamou ferramenta, orçamento restante)──► tools ──► agent
  ├──(texto final ou orçamento esgotado)──► respond ──► fim
  └──(provedor indisponível)────────────► fallback ─► fim
```

- `guard` aplica as mesmas políticas do modo planejador (`policies.py`) e
  resolve sem modelo os refinamentos explícitos de preço e os pedidos de recomendação.
- `agent` oferece `search_catalog` e `recommend_items`. No máximo três chamadas
  ao modelo e duas execuções de ferramenta por turno; depois disso as
  ferramentas deixam de ser oferecidas.
- `tools` executa as mesmas funções de `tools.py` que o planejador usa. O
  modelo recebe nomes e culinárias, nunca preços, para não repeti-los.
- `respond` aceita a frase final do modelo só se ela passar pela verificação de
  grounding (`agent/grounding.py`): sem moeda, links, alegações de dieta,
  estoque ou entrega, e sem números que não existam nos resultados. Caso
  contrário, usa a resposta montada a partir da ferramenta.
- `fallback` repete o caminho explícito do glossário quando nenhum provedor
  responde. Se uma ferramenta já tinha rodado, o resultado dela é mantido.

O estado da conversa (última busca, filtros, itens escolhidos) viaja no
`context` de cada requisição: o servidor é stateless e escala horizontalmente.
O streaming emite eventos públicos (`plan`, `tool`, `fallback`, `result`),
nunca o raciocínio interno do modelo.

## MCP

`mcp_server.py` expõe as ferramentas somente leitura pelo Model Context
Protocol para clientes externos. [Uso e configuração](MCP.md).

## Camada de LLM

- `types.py` define a porta `ChatModel` e o formato neutro de mensagens,
  `ToolSpec` e `ToolCall`. Tool calling e saída estruturada usam o mesmo contrato
  em todos os provedores.
- `gemini.py` traduz para a API do Gemini, incluindo as *thought signatures*
  que o Gemini 3 exige devolver entre turnos com ferramentas.
- `openai_compatible.py` atende Groq, o servidor llama.cpp local (Qwen) e a
  OpenAI pela API Chat Completions. O endpoint local só aceita loopback.
- `resilience.py` aplica, por provedor: no máximo duas tentativas dentro de 45
  segundos, retry só para HTTP transitório e um timeout, cota local por minuto
  e por dia, e pausa de 60 segundos após duas falhas seguidas (com uma única
  sonda de recuperação). Cada tentativa conta na cota, porque uma tentativa
  interrompida pode ter sido cobrada.
- `registry.py` monta o provedor principal e os fallbacks a partir do ambiente
  (`LLM_PROVIDER`, `LLM_FALLBACK_PROVIDERS`). Se todos falharem, o assistente
  usa o glossário explícito e informa o motivo sanitizado.

Nenhum log contém corpo de resposta do provedor, URL com parâmetros ou chave.

## Dados

ZIPs oficiais do DHRD conferidos por SHA-256 → normalização com quarentena
por pedido → SQLite somente leitura → perfis de treino (dias 0–61) → índices de
serviço. O teste oficial (dias 76–90) fica fisicamente separado e não foi usado
para ajustar modelos. Os artefatos públicos contêm só catálogo, popularidade e
vizinhança entre itens: nenhuma tabela individual de pedido ou cliente.

## Canais: Telegram e WhatsApp

```text
Telegram/Meta ──► Gateway Go ──XADD──► Redis Stream ──XREADGROUP──► worker ──► agente ──► API do canal
                     │ 200 em ms                                       │
                     └── GET /ready (acorda o app no plano gratuito) ──┘
```

- O **gateway** (Go, ~15 MB) valida o segredo do Telegram ou a assinatura HMAC
  da Meta, descarta duplicatas com `SET NX` por 24 h e responde em milissegundos;
  nunca chama o modelo.
- O **worker** consome o stream com consumer group, mantém o contexto da conversa
  no Redis por 24 h (chave com hash e sal, nunca o telefone) e responde no canal
  de origem. Falhas vão para uma fila de erros sem dado pessoal.
- No plano gratuito os serviços hibernam: depois de enfileirar, o gateway faz
  um `GET` no app para acordar o worker (`wake.go`).

Detalhes em [WHATSAPP.md](WHATSAPP.md).

## Privacidade e observabilidade

- `privacy.py` mascara telefone, e-mail, CPF e cartões antes de qualquer
  chamada ao LLM; o red team verifica isso no texto efetivamente enviado.
- `/metrics` expõe turnos por canal, planejador, status, latência, tokens e
  fallbacks em formato Prometheus; o gateway tem as próprias métricas.
- Traces OpenTelemetry seguem as convenções de GenAI (`gen_ai.*`) para cada
  chamada de modelo e ferramenta.

Modelo de ameaças e controles em [SECURITY.md](SECURITY.md).

## Decisões

| Decisão | Motivo |
| --- | --- |
| O modelo escolhe ferramentas, mas não é fonte de fatos | Itens e preços vêm só das ferramentas; a frase final passa por verificação de grounding |
| Agente e planejador lado a lado | O planejador (uma chamada estruturada) é mais barato e rápido; o agente é mais flexível. Os dois passam na suíte reservada, e a tabela mostra o custo de cada um |
| SQLite FTS5 em vez de banco vetorial | A busca lexical com glossário venceu o piloto E5 no mesmo protocolo |
| Gateway em Go separado da API | Webhooks precisam de resposta rápida e idempotente, independente da latência do LLM |
| Redis Streams em vez de Kafka | Mesma semântica de consumer group e ack, sem operar um cluster para este volume |
| Fallback entre provedores gratuitos | Cotas e quedas são normais na camada gratuita; Gemini → Groq → glossário mantém o serviço |
| Avaliação por código, não por juiz LLM | Os juízes testados reprovaram na calibração; regras determinísticas são reprodutíveis |
| Monólito modular na API | Um container cabe na camada gratuita; as portas permitem extrair serviços depois |
