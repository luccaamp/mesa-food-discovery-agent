# Avaliação do agente: confiabilidade, segurança e resultados negativos

A pergunta central do projeto (o que mostrar e se o agente ajuda a decidir) está
nos experimentos de [descoberta](EXPERIMENT_DISCOVERY.md) e do
[agente](EXPERIMENT_AGENT.md). Este documento cobre o que garante que o agente
**não erra**: contratos verificados por código, ataques e quedas de provedor.

## Princípio: verificação por código, não por outro modelo

Cada turno é conferido contra o catálogo oficial:
- a ferramenta escolhida e os filtros;
- a continuidade do contexto;
- a identidade de cada item mostrado;
- vazamento de prompt, links e moeda.

Juízes LLM só entrariam depois de passar numa calibração com controles, e não
passaram (veja abaixo). Os casos e protocolos ficam congelados antes de medir, em
[`configs/`](../configs/), e cada relatório guarda os hashes do catálogo, do
prompt e da suíte.

## Resultados

| O que mede | Resultado | Relatório |
| --- | --- | --- |
| Agente e planejador na suíte reservada: 20 conversas congeladas antes de qualquer ajuste, cada item conferido | 20/20 nos quatro pares (agente ou planejador × Gemini ou Groq) | [agent-provider-reserved-v1](../evaluations/results/agent-provider-reserved-v1.json) |
| Red team OWASP Top 10 para LLMs: 24 ataques (injeção direta e pelo catálogo, vazamento de prompt, dados pessoais, ferramentas inexistentes, links, alergênicos) | 24/24 com Gemini e com Groq; 15 respondidos pelo modelo, 9 barrados por política, 0 fallbacks | [gemini](../evaluations/results/red-team-v2-gemini.json) · [groq](../evaluations/results/red-team-v2-groq.json) |
| Provedor fora do ar (timeout, cota, erro) | 52/52 cenários seguem respondendo pelo glossário, com o motivo informado | [40](../evaluations/results/usage-timeout-resilience-v3.json) · [12](../evaluations/results/usage-additional-v3.json) |
| Telegram e WhatsApp de ponta a ponta: gateway Go, Redis Streams, worker e LLM | Aprovado, com o gateway respondendo em cerca de 5 ms | [whatsapp-integration-v1](../evaluations/results/whatsapp-integration-v1.json) |
| Interface: 12 testes E2E com axe, no desktop e no celular | Sem violações sérias de acessibilidade | `npm --prefix apps/web run e2e` |

**Agente e planejador.** O planejador faz uma chamada estruturada, e o código
escolhe a ferramenta. O agente (LangGraph) escolhe as ferramentas sozinho, pode
refazer uma busca vazia e usa o dobro de chamadas (25 contra 13 na suíte). Os
dois passam. Na suíte de desenvolvimento (40 conversas), o agente com Groq
começou em 35/40: traduzia "macarrão" como *pasta*. Passar ao agente os termos
do glossário do próprio catálogo levou a 40/40, e a suíte reservada confirmou a
correção.

## Resultados negativos

**Embeddings não superaram a busca lexical.** O piloto com E5 multilíngue
(10.000 itens, 12 consultas em português e inglês, rótulos por regra nos nomes)
teve NDCG@10 geral de 0,33 para o semântico e 0,44 para o híbrido, contra 0,46
para a busca lexical com glossário. Em português, nenhum método foi bom. O
piloto não foi promovido e o código saiu do produto
([resultado](../evaluations/results/retrieval-development-v1.json)).

**Juízes LLM reprovaram na calibração.** Qwen3-8B local, com saída restringida
por esquema, foi testado como juiz de relevância em quatro versões. A admissão
exigia 32/32 em controles escritos antes da execução. As duas melhores versões
pararam em 7/8:
- um código de inventário recebeu uma nota em vez de "sem informação";
- "Egg-Free Bread" foi julgado seguro para uma alergia a ovo.

Nenhuma nota de juiz aprova o produto. A avaliação segue por regras
determinísticas ([decisão](../evaluations/results/relevance-decision-v2.json)).

## O que não dá para concluir

Não há estudo com pessoas: nada aqui mede satisfação, conversão ou impacto
comercial. Os casos foram escritos com assistência de IA e são contratos de
comportamento, não uma amostra da população de usuários. Os provedores são
camadas gratuitas, e a latência varia com a carga.
