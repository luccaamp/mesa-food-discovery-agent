# Experimento: o que mostrar na home

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
| Mais pedidos da cidade (período todo e últimas 2 semanas\*) e sorteio\* | Mais pedidos da cidade (período todo e últimas 2 semanas\*) |
| Mais pedidos da região | Repetição + cidade (o melhor do v2: 14,44%) |
| Região × faixa horária, com recuo para região e cidade | Região × faixa horária |
| Repetição (restaurantes já usados) + região × horário | Repetição + região × horário |
| **Ranker LightGBM LambdaRank** (16 atributos, abaixo) | Itens dos restaurantes do ranker |
| Ranker 6 + descoberta 4 | Repetição 6 + descoberta 4 |

Os dois modelos "6 + 4" foram acrescentados depois da primeira rodada de
validação, e antes de qualquer contato com o teste. Eles traduzem uma decisão de
produto: reservar 4 das 10 posições para descoberta local. As referências
marcadas com \* foram acrescentadas depois do teste, numa revisão explicada
abaixo, e não mudam nenhum modelo.

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
até 0,7 ponto. Entre parênteses, o intervalo de confiança de 95% por bootstrap
sobre clientes (1.000 reamostragens).

### Restaurantes: o restaurante do pedido real está entre os 10 mostrados? (Hit@10)

| Modelo | Todos | Cliente novo | Recorrente, restaurante novo | Recorrente, volta |
| --- | ---: | ---: | ---: | ---: |
| Mais pedidos da cidade, período todo | 0,01% (0,01–0,02) | 0,01% (0,00–0,03) | 0,01% | 0,01% |
| Sorteio de 10 restaurantes (acaso) | 0,13% (0,11–0,15) | 0,16% (0,12–0,21) | 0,12% | 0,11% |
| Mais pedidos da cidade, últimas 2 semanas | 0,78% (0,73–0,82) | 0,90% (0,79–0,99) | 0,88% | 0,46% |
| Mais pedidos da região | 5,44% (5,34–5,55) | 5,84% (5,59–6,10) | 4,76% | 6,51% |
| **Região × horário** | 10,45% (10,32–10,60) | **10,23% (9,94–10,54)** | **9,54%** | 12,49% |
| Repetição + região × horário | 31,05% (30,84–31,26) | 10,23% (9,92–10,54) | 6,60% | 98,53% |
| **Ranker LightGBM** | **31,64% (31,42–31,86)** | 8,96% (8,67–9,26) | 8,16% | **98,67%** |
| Ranker 6 + descoberta 4 | 31,18% (30,97–31,40) | 9,87% (9,57–10,17) | 8,26% | 95,94% |

No MRR@10, o ranker teve 0,206, contra 0,193 de repetição + região × horário
(+6,6%): ele acerta mais e também põe o restaurante certo mais no alto.

### Itens: fração dos itens do pedido real entre os 10 sugeridos (Recall@10)

| Modelo | Todos | Cliente novo | Recorrente, restaurante novo | Recorrente, volta |
| --- | ---: | ---: | ---: | ---: |
| Mais pedidos da cidade, período todo | 0,21% (0,19–0,23) | 0,21% (0,17–0,25) | 0,20% | 0,22% |
| Mais pedidos da cidade, últimas 2 semanas | 0,24% (0,22–0,26) | 0,27% (0,23–0,32) | 0,24% | 0,20% |
| Repetição + cidade (baseline v2) | 14,52% (14,36–14,68) | 0,21% (0,17–0,26) | 0,09% | 56,01% |
| Região × horário | 2,83% (2,76–2,91) | 2,88% (2,72–3,04) | **2,38%** | 3,70% |
| **Repetição + região × horário** | **15,70% (15,53–15,86)** | **2,88% (2,72–3,04)** | 1,19% | 56,14% |
| Repetição 6 + descoberta 4 | 14,45% (14,30–14,61) | 2,88% (2,72–3,03) | 1,57% | 50,52% |
| Itens dos restaurantes do ranker | 15,32% (15,17–15,48) | 1,41% (1,31–1,52) | 0,83% | **56,64%** |

### Diferenças que sustentam as conclusões (pareadas, mesmos clientes)

| Comparação | Segmento | Diferença | IC 95% |
| --- | --- | ---: | ---: |
| Região × horário − cidade, últimas 2 semanas (restaurantes) | Cliente novo | +9,34 pontos | 9,00 a 9,70 |
| Região × horário − ranker (restaurantes) | Cliente novo | +1,27 ponto | 0,96 a 1,58 |
| Ranker − repetição + região × horário (restaurantes) | Todos | +0,58 ponto | 0,46 a 0,70 |
| Ranker 6 + descoberta 4 − ranker (restaurantes) | Cliente novo | +0,91 ponto | 0,67 a 1,13 |
| Repetição + região × horário − baseline v2 (itens) | Todos | +1,19 ponto | 1,14 a 1,23 |
| Região × horário − cidade, últimas 2 semanas (itens) | Cliente novo | +2,60 pontos | 2,45 a 2,76 |

Nenhum intervalo cruza zero.

### Uma referência que precisou ser corrigida

A primeira versão deste experimento comparava região × horário só com "mais
pedidos da cidade no período todo", que acerta 0,01%, menos que um sorteio
(0,13%). Uma revisão externa apontou o número. A verificação direta nos arquivos
descartou um bug: 99% dos restaurantes do teste existem no treino. A causa é o
comportamento descrito na [análise](BUSINESS_ANALYSIS.md#2-a-demanda-é-local-e-não-tem-campeões):
a demanda é plana e os 10 restaurantes mais pedidos de todo o período perderam
a demanda antes do teste.

Para comparar de forma justa, foram acrescentadas duas referências: os mais
pedidos das últimas duas semanas e o acaso. Também entraram os intervalos de
confiança. Nenhum modelo, atributo ou parâmetro mudou, e a nova rodada
reproduziu exatamente todos os números anteriores, na validação e no teste.
**O ganho de região × horário para clientes novos é de 11×** (10,2% contra
0,9%), não de "0,01% para 10,2%".

## O que isso significa

1. **O contexto é o maior ganho.** Para clientes novos, região × horário acerta
   o restaurante 11 vezes mais que a popularidade recente da cidade, e os itens
   também (2,88% contra 0,27%). Esses são os clientes sobre quem o app não sabe
   nada, e 58% deles não voltam em 30 dias.
2. **O melhor modelo de itens é simples.** Repetição completada por região ×
   horário supera o baseline v2 em 1,19 ponto (de 14,52% para 15,70%), sem
   treino, e é auditável.
3. **O ranker ganha no total, mas não em tudo.** É o melhor para ordenar
   restaurantes no geral e para quem volta. Para clientes novos, a regra simples
   vence por 1,27 ponto (IC de 0,96 a 1,58), porque o ranker aprende a confiar no
   histórico, que essa pessoa não tem. A conclusão de produto é **segmentar**:
   ranker para quem tem histórico, região × horário para quem não tem.
4. **Reservar posições para descoberta é um trade-off medido.** Com 4 das 10
   posições dedicadas à região, o ranker perde 0,46 ponto no total e 2,7 pontos
   em quem volta, e ganha 0,9 ponto em clientes novos.
5. **Teto da abordagem.** Só 48% dos restaurantes reais estavam entre os
   candidatos do ranker. O restante foi pedido fora do histórico e dos tops
   regionais. Esse é o próximo alvo: candidatos por culinária preferida e por
   similaridade entre restaurantes. A intenção declarada também ajuda; o
   [experimento do agente](EXPERIMENT_AGENT.md) mede isso.

## No produto

A web e o Telegram não identificam clientes, então todo visitante é um "cliente
novo". O produto usa o modelo que venceu nesse segmento: **região × horário**
([`context_popularity.py`](../src/meal_discovery/context_popularity.py)).
- **Home:** escolhendo a região em "Você está perto de", a vitrine mostra o que
  mais se pede ali na faixa horária atual de Singapura.
- **Assistente:** "me recomende algo" usa o mesmo sinal.
- **Telegram:** a pessoa diz onde está ("estou em Tampines", "perto de
  Bedok"), e o bot passa a usar a região na vitrine e na ordem da busca, até ela
  citar outro lugar. Sem região, usa a lista da cidade para o horário.

Com uma pessoa identificada, o passo seguinte seria servir o ranker para quem
tem histórico.

## Limites

É um replay offline de escolhas históricas: mede se o pedido real teria
aparecido, não conversão, receita ou satisfação. Não há dados de impressões, e
um restaurante "não mostrado" pode ter sido encontrado por outro caminho do app.
As regiões são células geohash de cerca de 5 km; os nomes de bairro no produto
são uma aproximação pelo centro da célula.
