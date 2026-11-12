# Experimento: o agente de IA ajuda o cliente novo a achar o que ele pediu?

**Pergunta.** É a mesma do [experimento de descoberta](EXPERIMENT_DISCOVERY.md),
agora com uma intenção declarada. Um cliente novo diz o que está com vontade de
comer. As 5 sugestões mostradas incluem o restaurante do pedido real dele?
Conversar com o agente (LLM com ferramentas) ajuda mais que a home ou que uma
busca comum?

## Protocolo, congelado antes de rodar

Configuração: [`configs/agent-discovery-v1.json`](../configs/agent-discovery-v1.json).
Código: [`analysis/agent_experiment.py`](../analysis/agent_experiment.py).
Dados brutos: [`agent-discovery-v1.json`](../evaluations/results/agent-discovery-v1.json).

- **Clientes:** os 36.766 clientes novos do teste oficial do DHRD (sem pedido até
  o dia 75); para cada um, o primeiro pedido.
- **Usuário simulado, gerado por código e sem LLM:** uma mensagem em português
  com a culinária do restaurante do pedido real ("Estou com vontade de comida
  japonesa"), mais ", algo barato" quando todos os itens com preço estavam na
  faixa $. Nunca entra nome de item ou de restaurante.
- **Amostra com o agente:** 120 clientes sorteados (semente 7), pela cota
  gratuita do provedor (Groq, `openai/gpt-oss-120b`). Os braços sem LLM rodam
  em todos os 36.766 e também na amostra, para comparação pareada.
- **Métricas, sobre 5 sugestões:** restaurante real entre elas; item real entre
  elas; fração de itens da culinária pedida; e nenhum resultado.

| Braço | O que é |
| --- | --- |
| Home | Região × horário (o produto); ignora a mensagem |
| Busca em português | A busca do produto com a culinária como uma pessoa digitaria ("comida japonesa"), mais o filtro $ quando barato |
| Busca com a palavra do catálogo | A mesma busca com o termo exato do catálogo ("japanese"): o melhor caso para busca por palavras |
| … reordenada pela região | O mesmo conjunto (50 primeiros por BM25), ordenado pelo quanto cada restaurante é pedido na região e no horário |
| Agente | `/v1/agent` com a mensagem completa e a região no contexto, como o produto mostra |
| Agente reordenado pela região | Os argumentos de busca escolhidos pelo agente, com a mesma reordenação |

## Resultados

### Todos os 36.766 clientes novos (sem LLM)

| Braço | Restaurante real entre 5 | Itens da culinária pedida | Sem resultado |
| --- | ---: | ---: | ---: |
| Home (região × horário) | 3,6% (3,5–3,8) | 4,0% | 0% |
| Busca em português | 1,1% (1,0–1,2) | 31,8% | 39,9% |
| Busca em português, reordenada pela região | 6,1% (5,9–6,4) | 32,1% | 39,9% |
| Busca com a palavra do catálogo | 2,3% (2,2–2,5) | 67,1% | 0,9% |
| **Busca com a palavra do catálogo, reordenada pela região** | **12,1% (11,7–12,4)** | 66,5% | 0,9% |

### Amostra de 120 clientes, com o agente

| Braço | Restaurante real entre 5 | Itens da culinária pedida | Sem resultado |
| --- | ---: | ---: | ---: |
| Home | 4,2% | 3,7% | 0% |
| Busca em português | 2,5% | 26,5% | 53,3% |
| Busca com a palavra do catálogo | 5,0% | 72,5% | 0,8% |
| **Agente** | 4,2% | **47,7%** | **15,0%** |
| Agente, reordenado pela região | 9,2% | 45,3% | 15,0% |
| Busca com a palavra do catálogo, reordenada | **15,0%** | 70,2% | 0,8% |

Diferenças pareadas na amostra (IC 95% por bootstrap):

| Comparação | Métrica | Diferença | IC 95% |
| --- | --- | ---: | ---: |
| Agente − busca em português | Sem resultado | −38,3 pontos | −50,0 a −27,5 |
| Agente − busca em português | Itens da culinária pedida | +21,2 pontos | +12,2 a +30,0 |
| Agente − busca com a palavra do catálogo | Itens da culinária pedida | −24,8 pontos | −32,7 a −17,2 |
| Agente reordenado − agente | Restaurante real | +5,0 pontos | +0,8 a +9,2 |
| Busca reordenada − busca (palavra do catálogo) | Restaurante real | +10,0 pontos | +4,2 a +15,8 |

**Custo:** 184 chamadas ao provedor, 163 mil tokens e 1,1 s de latência mediana
por turno. Em 23 dos 120 casos o agente chamou "recomendar" em vez de
"buscar". Em 39 casos (32%) o provedor recusou por limite de tokens por
minuto da camada gratuita, e o produto respondeu pelo glossário, como projetado.
Esses casos ficam dentro do braço "agente", porque é assim que o produto se
comporta sob cota.

## Rodada v2: sem fallbacks, com o produto atual

A primeira rodada (acima, v1) perdeu 39 dos 120 casos para o limite de tokens
por minuto do provedor gratuito. A v2
([protocolo](../configs/agent-discovery-v2.json),
[dados por caso](../evaluations/results/agent-discovery-v2.json)) repete os
mesmos clientes com pausa de 12 s, uma nova tentativa quando o provedor recusa
por cota e parada (em vez de fallback) se a cota acabar. Ela também mede o
agente **como está hoje no produto**, que já ordena a busca pela demanda da
região (decisão 4, abaixo).

**120 de 120 casos, 0 fallbacks.** A cota diária acabou no caso 102; o
protocolo parou em vez de cair no fallback e retomou do mesmo ponto no dia
seguinte.

| 5 sugestões, 120 clientes | Restaurante real | Itens da culinária pedida | Sem resultado |
| --- | ---: | ---: | ---: |
| Home | 4,2% | 3,7% | 0% |
| Busca em português | 2,5% | 26,5% | 53,3% |
| Busca com a palavra do catálogo | 5,0% | **72,5%** | 0,8% |
| Busca com a palavra do catálogo, reordenada | **15,0%** | 70,2% | 0,8% |
| **Agente (produto atual)** | 11,7% (6,7–17,5) | 53,7% | **0,8%** |

| Comparação pareada (IC 95%) | Restaurante real | Itens da culinária pedida | Sem resultado |
| --- | ---: | ---: | ---: |
| Agente − busca em português | **+9,2 (4,1 a 15,0)** | **+27,2 (19,3 a 36,0)** | **−52,5 (−61,7 a −43,3)** |
| Agente − busca com a palavra do catálogo | +6,7 (1,7 a 12,5) | −18,8 (−27,0 a −10,8) | 0,0 |


**Custo:** 240 chamadas, 216 mil tokens e 1,2 s de latência mediana. Em 29
dos 120 casos o agente chamou "recomendar" em vez de "buscar".

## O que isso significa

1. **O LLM entrega o que promete: entender a pessoa.** Comparado com a busca
   que recebe o português, ele reduz as buscas sem resultado (−38 pontos na v1,
   −53 na v2) e aumenta os itens da culinária pedida (+21 na v1, +27 na v2). É o trabalho de traduzir
   "comida japonesa" para o vocabulário do catálogo.
2. **Ele não substitui saber a palavra certa.** Contra a busca que já recebe o
   termo exato do catálogo, o agente perde 19 pontos em itens da culinária
   pedida, mesmo sem fallbacks (v2). O motivo principal são os 29 casos em que
   ele recomendou em vez de buscar. É o teto a perseguir: mais termos do catálogo no
   contexto do agente e menos recomendação quando há intenção clara.
3. **Achar o restaurante certo é contexto, não linguagem.** Com a ordenação
   regional no produto, o agente vai a 11,7% e supera a busca em português por
   9,2 pontos (IC de 4,1 a 15,0). Nenhum braço que
   ignora a região passa de 5% no restaurante real. Reordenar pela demanda local
   leva a busca de 2,3% para 12,1% nos 36.766 clientes, e o agente de 4,2% para
   9,2% na amostra.
4. **Decisão aplicada no produto.** Quando a região é conhecida, a ferramenta de
   busca do agente agora pega os 50 melhores por BM25 e os ordena pela demanda
   do restaurante na região e no horário
   ([`rank_by_local_demand`](../src/meal_discovery/context_popularity.py)). É o
   braço "agente reordenado pela região". A frase da resposta avisa isso.

## Limites

- **Usuário simulado:** a intenção é gerada por código a partir do pedido real,
  e uma pessoa diria coisas mais vagas ou mais específicas. É um único turno.
- **Amostra pequena:** com 120 casos, os intervalos do agente são largos (±4 a
  ±8 pontos). Os braços sem LLM têm 36.766 casos.
- **Fallbacks na v1:** 32% dos casos da v1 caíram no fallback por cota, o que
  misturava o agente com o glossário. A v2 resolveu isso: os 120 casos foram
  respondidos pelo próprio modelo.
- **Assimetria do produto:** a busca não recebe a região, e a home e o agente
  recebem. É o produto como foi construído, e a reordenação mostra o efeito de
  dar a região a todos.
