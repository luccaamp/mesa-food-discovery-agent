# Mesa v2 — roadmap

A v1 entregou dados oficiais auditados, recomendação comparada com
referências, busca lexical com glossário, assistente com planejamento por LLM,
interface web e uma bateria de avaliação automatizada. A v2 transforma o
assistente em um agente com ferramentas, abre um segundo canal (WhatsApp) e
eleva arquitetura, interface e operação ao padrão de um produto em produção.

Regra de execução: uma fase só termina com testes e CI verdes; a seguinte
começa logo depois. Nenhuma fase depende de serviço pago.

## Problema de produto

Pessoas abrem um app de delivery sem saber o que pedir, rolam o feed e
desistem ou repetem o último pedido. O Mesa reduz o tempo até a decisão
combinando histórico, catálogo e conversa com restrições compostas
("algo leve até 15, para dois, sem carne"), sempre mostrando a evidência.

| Métrica | Tipo | Como é medida aqui |
| --- | --- | --- |
| Item adicionado ao carrinho (simulado) | Principal, proxy de conversão | Eventos da interface e episódios simulados |
| Turnos até a primeira sugestão aceita | Principal | Suítes de conversa |
| Itens inexistentes ou dados inventados | Proteção | Verificação por código contra o catálogo |
| Latência p95 e custo por conversa | Proteção | Traces por provedor |

## Fases

| Fase | Entrega | Pronto quando |
| --- | --- | --- |
| 1. Fundação | Arquitetura hexagonal (domínio, portas, adaptadores), camada de provedores LLM (Gemini, Groq, Qwen local), README novo | Suítes atuais verdes sem regressão |
| 2. Agente | Tool calling nativo em várias etapas (LangGraph), estado da conversa, streaming SSE, servidor MCP com as mesmas ferramentas, comparação entre provedores | Suítes de conversa verdes nos provedores gratuitos; tabela de qualidade, latência e custo |
| 3. Produto | Design system próprio, home mobile-first com clientes anonimizados reais, carrosséis personalizados, assistente flutuante, carrinho simulado, frontend dividido por feature | Testes de componente, E2E com Playwright e checagem de acessibilidade |
| 4. Mensageria | Gateway em Go para o webhook do WhatsApp Cloud API (assinatura HMAC, idempotência), fila em Redis Streams, worker que executa o agente | Testes com payloads oficiais; conversa real no número de teste |
| 5. Operação | OpenTelemetry e traces de LLM, mascaramento de dados pessoais e retenção (LGPD), suíte de red-team no CI, deploy e publicação | CI completa, deploy verificado, demo gravada |

Opcionais, somente se as fases anteriores fecharem: embeddings ajustados com
pares de coocorrência e publicados no Hugging Face; enriquecimento de atributos
do catálogo por LLM; Terraform para os serviços do Render; avaliação única no
teste oficial (dias 76–90).

## Fora do escopo, com motivo

- **Kubernetes e Kafka:** o volume do projeto não justifica. Redis Streams
  cumpre o papel de barramento de eventos com a mesma semântica de consumo.
- **Provedores pagos:** os adaptadores seguem a mesma porta, mas só provedores
  com camada gratuita são executados e comparados.
- **Novas rodadas do juiz de relevância:** encerradas com resultado negativo
  documentado na v1.
