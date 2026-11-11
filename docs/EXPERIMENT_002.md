# Experimento 002 — fonte oficial e busca real

## Preparação executada

O adaptador `singapore-official-v1` verifica hashes fixos dos arquivos oficiais e prepara exclusivamente catálogo, vendedores e pedidos de treino. O teste oficial permanece fora do banco, referenciado pelo hash e intervalo 76–90. Um teste automatizado confirma que a preparação e a validação funcionam sem abrir esse arquivo.

Banco preparado: 7.411 vendedores, 1.066.840 produtos, 1.709.379 pedidos e 3.346.819 presenças de itens. A quarentena excluiu 35 pedidos completos afetados por produtos ausentes (77 linhas); 84.974 repetições de item foram deduplicadas para presença binária. [Manifesto](../evaluations/results/singapore-official-preparation-v1.json).

## Validação registrada antes de medir

[Protocolo v2](../configs/singapore-official-experiment-v2.json): treino 0–61, validação 62–75, primeira cesta futura por cliente, K=10, perfis congelados, candidatos observados no treino, sem amostragem negativa ou filtro geográfico. Nenhuma métrica foi calculada no teste oficial.

Treino: 1.410.654 pedidos, 435.376 clientes, 228.822 itens. Validação: 175.358 clientes, dos quais 40.767 sem histórico. Dos 352.188 itens relevantes, 12.183 não aparecem no catálogo observado no treino e contam como erros; cobertura de alvos de 96,54%.

| Modelo | Recall@10 | NDCG@10 | HitRate@10 |
| --- | ---: | ---: | ---: |
| Popularidade | 0,2606% | 0,001243 | 0,3034% |
| Repetição pessoal | **14,4442%** | **0,115707** | **17,9096%** |
| Similaridade por cesta | 6,2262% | 0,039786 | 8,5220% |

[Relatório completo](../evaluations/results/singapore-official-validation-v2.json). Repetição continua sendo a melhor referência medida. Clientes sem histórico recebem o mesmo fallback de popularidade nos três modelos. Preferências explícitas e conteúdo são caminhos a avaliar para descoberta de itens.

A janela v2 é maior que a do Experimento 001; diferenças de pontuação não demonstram melhoria ou regressão do algoritmo. As métricas medem previsão offline, sem comprovar conversão comercial. Tempos são locais, sem teste de carga. Resultados históricos e sua procedência permanecem intactos.

## Busca textual executável

`build-catalog` cria um SQLite separado com FTS5/BM25, sem alterar o banco de treino ou usar pedidos de teste. Indexa o catálogo completo, incluindo produtos sem interação de treino. Resultados preservam vendedor/produto, nome, culinária e preço normalizado. A procedência contém hashes do banco e dos arquivos de origem.

`search-catalog` aceita termos literais, culinária exata e limites de preço normalizado. Não executa operadores de FTS/SQL fornecidos na consulta. Rejeita parâmetros inválidos e limita resultados a 1–50. Não há fallback sintético ou substituição de índices existentes.

Verificações reais: “chicken rice” teve 27.621 correspondências, “pizza” 45.706 e “milk tea” 13.826. Os filtros combinados passaram nas três consultas. [Relatório agregado](../evaluations/results/singapore-search-contracts-v1.json). Essas verificações demonstram contratos de execução, sem avaliar relevância com julgamento humano. Os termos podem corresponder ao nome ou à culinária, sem exigir frase contígua.

Limites: não traduz português, não interpreta restrições alimentares nem infere ingredientes/alérgenos, não verifica estoque/entrega e não converte preços para reais. Não há embeddings ou LLM nesta etapa. Scores BM25 não são probabilidades. Idiomas sem separação por espaços precisam de avaliação própria.

## Reprodução

Com os arquivos oficiais já extraídos e Python configurado:

```sh
python -m meal_discovery prepare-official-singapore --output data/processed/singapore-official-v1.sqlite
python -m meal_discovery validate-singapore --database data/processed/singapore-official-v1.sqlite --protocol configs/singapore-official-experiment-v2.json --output reports/singapore-official-validation-v2.json
python -m meal_discovery build-catalog --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-catalog-v1.sqlite
python -m meal_discovery search-catalog --index data/processed/singapore-catalog-v1.sqlite --query "chicken rice" --limit 5
python scripts/check_catalog_search.py --index data/processed/singapore-catalog-v1.sqlite --output reports/singapore-search-contracts-v1.json
```

Saídas existentes são protegidas: escolha outros nomes ao repetir.

## Próximos marcos

1. API com contratos de busca, filtros, procedência e erro explícito se a base estiver ausente.
2. Consultas com julgamentos de relevância para comparar lexical, embeddings e busca híbrida.
3. Assistente com ferramentas e respostas vinculadas a produtos existentes; medir alucinação, custo e latência.
4. Interface profissional para exploração e laboratório de resultados, mantendo dados reais em toda a experiência.
