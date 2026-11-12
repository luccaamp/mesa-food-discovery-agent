# Experimento 001 — primeira validação real de recomendação

Nota de procedência adicionada em 7/11/2026: os arquivos oficiais foram recebidos. A comparação confirmou igualdade linha a linha dos campos originais de pedidos de treino, produtos e vendedores de Singapura com a cópia usada nesta execução. Resultados e hashes abaixo permanecem históricos, sem mudança de rótulo para execução oficial. [Verificação](OFFICIAL_DATA_MIGRATION.md).

Executado em 6/11/2026. Resultado de validação offline, não de operação com usuários reais. Não há LLM neste experimento. O objetivo foi preparar os dados e estabelecer referências que os próximos modelos precisarão superar.

## Procedência e preparação

Fonte: três CSVs reais de Singapura publicados pelo espelho NearBite, com origem DHRD declarada pelo autor. [Procedência e hashes](DATA_ACCESS.md). Não se verificou equivalência byte a byte com o pacote original, cujo acesso ainda está pendente.

O adaptador `singapore-v1` confere os três SHA-256 fixados, reconhece explicitamente o índice de exportação e o dia relativo textual, valida produtos e vendedores, preserva metadados de contexto e cria SQLite. Dados brutos permanecem intactos. Latitude/longitude derivadas pelo espelho são ignoradas; geohash é preservado como aproximação, sem inferir cobertura de entrega.

As 41 linhas sem produto no catálogo pertenciam a 35 pedidos. Foram excluídos esses pedidos por inteiro (77 linhas), preservando a integridade das cestas. Isso corresponde a aproximadamente 0,00205% dos pedidos de origem; não implica ausência de viés por segmento. Os IDs e motivos de quarentena ficam apenas no banco local.

Das linhas restantes, 84.974 repetições de um mesmo produto no mesmo pedido foram consolidadas. A tarefa usa presença binária de item na cesta, não quantidade comprada. Resultado:

| Entidade | Contagem |
| --- | ---: |
| Pedidos preparados | 1.709.379 |
| Presenças únicas de itens em pedidos | 3.346.819 |
| Produtos do catálogo completo | 1.066.840 |
| Estabelecimentos do catálogo | 7.411 |

O [manifesto agregado de preparação](../evaluations/results/singapore-preparation-v1.json) contém contagens por dia e a transformação aplicada, sem registros individuais.

## Protocolo registrado antes da execução

[Configuração versionada](../configs/singapore-experiment-v1.json):

- Treino: dias relativos 0–61, inclusive.
- Validação: dias 62–68, inclusive.
- Teste reservado: dias 69–75; **não avaliado**.
- Uma previsão por cliente: a primeira cesta na janela de validação.
- Mesmo histórico congelado e mesmos alvos para os três modelos.
- Catálogo candidato: 228.822 itens presentes no treino; sem amostragem de negativos.
- Recompras permitidas. Itens-alvo ausentes do treino permanecem no denominador como falhas.
- Todos os 109.842 usuários da validação avaliados; sem amostragem de usuários.
- Sem restrição geográfica ou confirmação de disponibilidade do catálogo.

Treino: 1.410.654 pedidos de 435.376 clientes. Validação: 221.519 itens relevantes em 109.842 primeiras cestas. Destes itens, 6.278 não estavam no catálogo de treino, resultando em cobertura dos alvos de 97,17%.

Este é nosso corte temporal dentro dos 76 dias do arquivo público de treino, não o teste oficial original. A configuração e o comando de validação evitam avaliar os dias reservados por esse caminho, mas não são um mecanismo de controle de acesso ao banco. Nenhum hiperparâmetro foi escolhido por teste nesta etapa.

## Referências comparadas

1. **Popularidade global:** frequência do item em cestas de treino.
2. **Repetição pessoal:** frequência do item no histórico do cliente; completar posições vazias com popularidade global.
3. **Cosseno por cesta:** co-presença de pares de itens no mesmo pedido, normalizada por cosseno e reduzida para poucos exemplos em comum. Até 100 vizinhos por item e 20 itens-semente mais frequentes do perfil; completar posições vagas com popularidade.

Para um par de itens com frequência conjunta `c`, o peso é `c / sqrt(freq_a * freq_b) * c / (c + 10)`. Somar os pesos a partir das sementes. Nenhum termo usa compras da validação ou do teste. O grafo tem 2.165.544 relações direcionadas de pares de treino.

Esse candidato é distinto do `item_cosine` legado, que usa compradores em comum. O legado permanece no código para experimentos pequenos, mas não participou desta execução. Os parâmetros do novo candidato foram fixados antes desta primeira validação, sem varredura de valores.

## Resultados observados

Recall@10 e Hit@10 abaixo estão em porcentagem. NDCG@10 está na escala 0–1. Todas as métricas são médias por cliente.

| Modelo | Recall@10 | NDCG@10 | Hit@10 |
| --- | ---: | ---: | ---: |
| Popularidade global | 0,2504% | 0,001166 | 0,2941% |
| Repetição pessoal | **16,0427%** | **0,127100** | **19,8886%** |
| Cosseno por cesta | 6,7272% | 0,042941 | 9,2232% |

Recall mede a fração média de itens da próxima cesta recuperados entre as dez sugestões. Hit Rate mede a fração de clientes com pelo menos um item correto. NDCG também considera a posição. Não são métricas de satisfação, conversão ou economia financeira.

## Análise inicial de erros

| Grupo | Clientes | Recall@10 repetição | Recall@10 cosseno por cesta |
| --- | ---: | ---: | ---: |
| Com histórico no treino | 88.362 | 19,8741% | 8,2941% |
| Sem histórico no treino | 21.480 | 0,2817% | 0,2817% |

Clientes sem histórico representam aproximadamente 19,56% da avaliação. Os três modelos retornam a mesma alternativa global nesse grupo, explicando a igualdade. A cobertura do catálogo de treino também limita a recuperação de itens novos.

O resultado sustenta manter repetição como referência forte para este recorte. Ele não prova causalmente uma preferência por recomprar nem que repetição será o melhor modelo final. O candidato de co-compra foi pior nesta execução; registramos esse resultado sem acrescentar complexidade apenas pela aparência técnica.

Hipóteses futuras: recuperação por texto/categoria e preferências declaradas para quem não tem histórico; combinação de repetição com descoberta; comparação de candidatos geográficos quando a semântica do geohash e a regra de cobertura forem definidas. Cada hipótese precisa de avaliação própria.

## Reprodução e evidências

```sh
python scripts/legacy/fetch_nearbite_sg.py
python -m meal_discovery prepare-singapore --output data/processed/singapore-v1.sqlite
python -m meal_discovery validate-singapore --database data/processed/singapore-v1.sqlite --output reports/singapore-validation-v1.json
```

Saídas existentes são protegidas contra sobrescrita: para repetir em um workspace já executado, escolher novos nomes de banco/relatório. O download confere a cópia local existente.

[Relatório agregado completo](../evaluations/results/singapore-validation-v1.json): versões, hashes de fontes/implementação/banco, protocolo, segmentos, cobertura e tempo medido. São 31 testes automatizados nesta etapa, incluindo descarte de pedidos completos, proteção de fontes reais, exemplos calculados manualmente e invariância a eventos futuros.

As latências desse relatório são de funções locais em uma execução sequencial, com cache de vizinhos. O ajuste compartilhado levou aproximadamente 35 segundos no ambiente utilizado. Esses números não representam API pública, carga concorrente ou desempenho em outros equipamentos. Não foram produzidos intervalos de confiança nesta primeira avaliação.

## Estado e próxima decisão

Preparação real e primeira validação concluídas. Teste continua reservado. Não há modelo persistido no Hugging Face, interface publicada ou agente com LLM. Próximo marco: busca lexical e por embeddings avaliada, apoiada no catálogo real, e funções que possam ser expostas por API e usadas pelo assistente.
