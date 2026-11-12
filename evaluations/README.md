# evaluations/

Suítes do agente e relatórios versionados. Cada JSON em [`results/`](results/)
guarda os hashes do catálogo, do protocolo e do código que o produziram.

| Resultado | Gerado por | Relatório |
| --- | --- | --- |
| Análise de negócio, 1,7 milhão de pedidos | [`analysis/business_analysis.py`](../analysis/business_analysis.py) | [business-analysis-v1](results/business-analysis-v1.json) |
| O que mostrar na home: validação e teste oficial | [`analysis/discovery_experiment.py`](../analysis/discovery_experiment.py) | [validation](results/discovery-validation-v1.json) · [test](results/discovery-test-v1.json) |
| O agente ajuda o cliente novo a achar o pedido real? | [`analysis/agent_experiment.py`](../analysis/agent_experiment.py) | [agent-discovery-v1](results/agent-discovery-v1.json) |
| Agente × planejador, 20 conversas reservadas | [`agent_comparison.py`](agent_comparison.py) | [reserved-v1](results/agent-provider-reserved-v1.json) |
| Red team OWASP Top 10 para LLMs, 24 ataques | [`red_team.py`](red_team.py) | [gemini](results/red-team-v2-gemini.json) · [groq](results/red-team-v2-groq.json) |
| Provedor fora do ar, 52 cenários | `scripts/check_usage_resilience.py` | [40](results/usage-timeout-resilience-v3.json) · [12](results/usage-additional-v3.json) |
| Telegram e WhatsApp de ponta a ponta | `scripts/check_whatsapp_flow.py` | [whatsapp-integration-v1](results/whatsapp-integration-v1.json) |
| Embeddings × busca lexical (negativo) | código arquivado; [EVALUATION.md](../docs/EVALUATION.md) | [retrieval-development-v1](results/retrieval-development-v1.json) |
| Juízes LLM (negativo) | código arquivado; [EVALUATION.md](../docs/EVALUATION.md) | [relevance-decision-v2](results/relevance-decision-v2.json) |
| Procedência dos dados | `scripts/verify_official_archives.py`, `scripts/audit_official_data.py` | [manifest](results/official-archives-manifest-v1.json) · [audit](results/official-data-audit-v1.json) · [preparation](results/singapore-official-preparation-v1.json) |

Regras:
- protocolos congelados em [`configs/`](../configs/) antes de medir;
- teste oficial usado uma única vez;
- verificação por código, não por outro modelo;
- fallbacks e cotas aparecem em cada relatório.

Os testes das suítes estão em [`tests/test_conversation_suite.py`](../tests/test_conversation_suite.py).
