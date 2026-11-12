# Experimento 004: o que mostrar na home

**Pergunta de negócio.** Quando alguém abre o app, quais 10 restaurantes e quais
10 itens mostrar? A resposta é medida contra o **próximo pedido real** de cada
cliente.

**Hipótese**, vinda da [análise de negócio](BUSINESS_ANALYSIS.md):
- a maioria dos pedidos é exploração (63% vão a um restaurante nunca usado);
- a popularidade é local, e o horário muda o que se pede;
- logo, região e horário deveriam valer muito mais que a popularidade da cidade,
  sobretudo para quem não tem histórico.

## Protocolo, congelado antes de rodar

Configuração: [`configs/discovery-experiment-v1.json`](../configs/discovery-experiment-v1.json).
Código: [`analysis/discovery_experiment.py`](../analysis/discovery_experiment.py).

| Etapa | Histórico usado | Pedidos-alvo | Para quê |
| --- | --- | --- | --- |
| Desenvolvimento | dias 0–47 | 1º pedido de cada cliente nos dias 48–61 | treinar o ranker |
| Validação | dias 0–61 | 1º pedido de cada cliente nos dias 62–75 | comparar e escolher (mesma janela do protocolo v2) |
| Teste final | dias 0–75 | 1º pedido de cada cliente no **arquivo de teste oficial do DHRD** (dias 76–90) | uma única rodada, sem ajuste depois |

- **O que o modelo sabe na hora do pedido:** a região do pedido (geohash), a
  hora e o histórico do cliente até o corte. Nada do pedido-alvo.
- **Segmentos:** cliente novo (sem histórico), recorrente que volta a um
  restaurante já usado, e recorrente que experimenta um restaurante novo.
- **Métricas:** para restaurantes, se o restaurante do pedido real está entre
  os 10 mostrados (Hit@10), e MRR@10. Para itens, Recall@10 sobre os itens do
  pedido real, comparável ao baseline v2.

### Modelos

| Restaurantes | Itens |
| --- | --- |
| Mais pedidos da cidade | Mais pedidos da cidade (baseline v2) |
| Mais pedidos da região | Repetição + cidade (o melhor do v2: 14,44%) |
| Região × faixa horária, com recuo para região e cidade | Região × faixa horária |
| Repetição (restaurantes já usados) + região × horário | Repetição + região × horário |
| **Ranker LightGBM LambdaRank** (16 atributos, abaixo) | Itens dos restaurantes do ranker |
| Ranker 6 + descoberta 4 | Repetição 6 + descoberta 4 |

Os dois modelos "6 + 4" foram acrescentados depois da primeira rodada de
validação, e antes de qualquer contato com o teste. Eles traduzem uma decisão de
produto: reservar 4 das 10 posições para descoberta local.

**Atributos do ranker:**
- **Relação cliente–restaurante:** visitas, dias desde a última visita, fração
  dos pedidos do cliente, visitas a outras unidades da mesma rede.
- **Relação cliente–culinária:** fração dos pedidos do cliente nessa culinária.
- **Popularidade:** na cidade, nos últimos 14 dias, na região, na região naquele
  horário, e a fração dos pedidos da região-horário.
- **Horário e localização:** fração dos pedidos do restaurante nesse horário,
  se o restaurante fica na mesma região e a afinidade culinária–horário.

O ranker foi treinado com 82.917 clientes cujo restaurante real estava entre os
candidatos (histórico, top da região-horário, da região e da cidade).

## Resultados

_Em preenchimento._
