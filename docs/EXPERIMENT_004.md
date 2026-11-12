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

## Resultados no teste oficial

Rodada única no arquivo de teste do DHRD, com **171.515 clientes**: 36.766
novos, 44.167 que voltaram a um restaurante já usado e 90.582 que
experimentaram um restaurante novo. Os dados brutos estão em
[`discovery-test-v1.json`](../evaluations/results/discovery-test-v1.json). A
validação ([`discovery-validation-v1.json`](../evaluations/results/discovery-validation-v1.json),
175.358 clientes) teve o mesmo ordenamento entre os modelos, com diferenças de
até 0,7 ponto.

### Restaurantes: o restaurante do pedido real está entre os 10 mostrados? (Hit@10)

| Modelo | Todos | Cliente novo | Recorrente, restaurante novo | Recorrente, volta |
| --- | ---: | ---: | ---: | ---: |
| Mais pedidos da cidade | 0,01% | 0,01% | 0,01% | 0,01% |
| Mais pedidos da região | 5,44% | 5,84% | 4,76% | 6,51% |
| Região × horário | 10,45% | **10,23%** | **9,54%** | 12,49% |
| Repetição + região × horário | 31,05% | 10,23% | 6,60% | 98,53% |
| **Ranker LightGBM** | **31,64%** | 8,96% | 8,16% | **98,67%** |
| Ranker 6 + descoberta 4 | 31,18% | 9,87% | 8,26% | 95,94% |

No MRR@10, o ranker teve 0,206, contra 0,193 de repetição + região × horário
(+6,6%): ele acerta mais e também põe o restaurante certo mais no alto.

### Itens: fração dos itens do pedido real entre os 10 sugeridos (Recall@10)

| Modelo | Todos | Cliente novo | Recorrente, restaurante novo | Recorrente, volta |
| --- | ---: | ---: | ---: | ---: |
| Mais pedidos da cidade | 0,21% | 0,21% | 0,20% | 0,22% |
| Repetição + cidade (baseline v2) | 14,52% | 0,21% | 0,09% | 56,01% |
| Região × horário | 2,83% | 2,88% | **2,38%** | 3,70% |
| **Repetição + região × horário** | **15,70%** | **2,88%** | 1,19% | 56,14% |
| Repetição 6 + descoberta 4 | 14,45% | 2,88% | 1,57% | 50,52% |
| Itens dos restaurantes do ranker | 15,32% | 1,41% | 0,83% | **56,64%** |

## O que isso significa

1. **O contexto é o maior ganho.** Trocar "mais pedidos da cidade" por "mais
   pedidos nesta região e horário" leva o acerto de restaurante de 0,01% para
   10,2% entre clientes novos. Nos itens, o ganho é de 0,21% para 2,88%, cerca
   de 14 vezes. Esses são os clientes sobre quem o app não sabe nada, e 58%
   deles não voltam em 30 dias.
2. **O melhor modelo de itens é simples.** Repetição completada por região ×
   horário supera o baseline v2 de 14,52% para 15,70% (+8% relativo), sem
   treino, e é auditável.
3. **O ranker ganha no total, mas não em tudo.** Ele é o melhor para ordenar
   restaurantes no geral e para quem volta. Para clientes novos, a popularidade
   regional sem aprendizado é melhor (10,2% contra 9,0%), porque o ranker
   aprende a confiar no histórico, que essa pessoa não tem. A conclusão de
   produto é **segmentar**: ranker para quem tem histórico, região × horário
   para quem não tem.
4. **Reservar posições para descoberta é um trade-off medido.** Com 4 das 10
   posições dedicadas à região, o ranker perde 0,46 ponto no total e 2,7 pontos
   em quem volta, e ganha 0,9 ponto em clientes novos. A escolha depende do
   objetivo (retenção de novos ou conversão de recorrentes), e o número está aqui
   para essa conversa.
5. **Teto da abordagem.** Só 48% dos restaurantes reais estavam entre os
   candidatos do ranker; o restante foi pedido fora do histórico e dos tops
   regionais. Esse é o próximo alvo: candidatos por culinária preferida e por
   similaridade entre restaurantes.

## No produto

A web e o Telegram não identificam clientes, então todo visitante é um "cliente
novo". O produto usa o modelo que venceu nesse segmento: **região × horário**
([`context_popularity.py`](../src/meal_discovery/context_popularity.py)).
- **Home:** escolhendo a região em "Você está perto de", a vitrine mostra o que
  mais se pede ali na faixa horária atual de Singapura.
- **Assistente:** "me recomende algo" usa o mesmo sinal.
- **Telegram:** sem região, o bot usa a lista da cidade para o horário.

Com uma pessoa identificada, o passo seguinte seria servir o ranker para quem
tem histórico.

## Limites

É um replay offline de escolhas históricas: mede se o pedido real teria
aparecido, não conversão, receita ou satisfação. Não há dados de impressões, e
um restaurante "não mostrado" pode ter sido encontrado por outro caminho do app.
As regiões são células geohash de cerca de 5 km; os nomes de bairro no produto
são uma aproximação pelo centro da célula.
