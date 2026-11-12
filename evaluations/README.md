# Avaliação

Cada resultado publicado tem um script que o reproduz e um JSON em
[`results/`](results/) com hashes do catálogo, do prompt e da suíte. Respostas
são verificadas por código contra o catálogo oficial; resultados negativos
ficam registrados ao lado dos positivos. Protocolo completo e referências em
[AUTOMATED_EVALUATION.md](../docs/AUTOMATED_EVALUATION.md).

## Principais resultados

| O que mede | Resultado | Script | Relatório |
| --- | --- | --- | --- |
| Agente × planejador, 20 conversas reservadas | 20/20 nos 4 pares (Gemini, Groq) | [agent_comparison.py](agent_comparison.py) | [reserved-v1](results/agent-provider-reserved-v1.json) |
| Red team OWASP Top 10 para LLMs, 24 ataques | 24/24 com Gemini e com Groq | [red_team.py](red_team.py) | [gemini](results/red-team-v2-gemini.json) · [groq](results/red-team-v2-groq.json) |
| Recomendação da próxima cesta, 175.358 clientes | Repetição pessoal vence: NDCG@10 0,1157 | `python -m meal_discovery validate-singapore` | [validation-v2](results/singapore-official-validation-v2.json) |
| Busca: lexical × E5 × híbrida | E5 não superou a lexical com glossário | [EXPERIMENT_003](../docs/EXPERIMENT_003.md) | [retrieval-v1](results/retrieval-development-v1.json) |
| Juiz LLM de relevância | Reprovado na calibração; nenhuma nota dele aprova o produto | [relevance_judge_bounded.py](relevance_judge_bounded.py) | [decision-v2](results/relevance-decision-v2.json) |
| Provedor fora do ar | 52/52 cenários (40 + 12) seguem respondendo pelo glossário | `scripts/check_usage_resilience.py` | [40](results/usage-timeout-resilience-v3.json) · [12](results/usage-additional-v3.json) |
| WhatsApp/Telegram de ponta a ponta | Gateway Go + Redis + worker + LLM aprovados | `scripts/check_whatsapp_flow.py` | [whatsapp-v1](results/whatsapp-integration-v1.json) |

## Regras

- **Teste reservado não é usado para ajuste.** A suíte reservada do agente foi
  congelada antes de qualquer mudança; os dias 76–90 do DHRD continuam intocados.
- **Verificação por código, não por outro modelo.** Ferramenta escolhida, filtros,
  identidade de cada item, vazamento de prompt, links e moeda são checados
  deterministicamente. Juízes LLM só entram depois de calibrados em controles.
- **Sucesso da chamada HTTP não é sucesso da tarefa.** Fallbacks, cotas e
  repetições aparecem em cada relatório.
- **Personas simuladas não medem satisfação.** Nenhuma conversão ou satisfação de
  pessoas reais é inferida das simulações.

## Pastas

- `*.py`: suítes, comparação de provedores, red team e calibração de juízes.
- `results/`: relatórios versionados.
- `../tests_eval/`: testes das suítes (Inspect AI, ambiente isolado).
