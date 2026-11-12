# Dados, modelos e artefatos locais

Nada nesta pasta, em `models/` ou em `reports/` é versionado: o Git guarda só
manifestos, configurações e resultados agregados.

## Fonte

[Delivery Hero Recommendation Dataset](https://github.com/deliveryhero/dh-reco-dataset)
(DHRD, RecSys 2023). Os três ZIPs oficiais (Singapura, Estocolmo e Taipei) foram
verificados por SHA-256 e CRC e extraídos em `data/raw/dhrd-official-v1/`.
O produto usa Singapura: 1.066.840 itens, 7.411 vendedores, pedidos dos dias
0–90. [README da distribuição](../docs/data/DHRD_README.md) ·
[procedência e auditoria](../docs/DATA_ACCESS.md) ·
[quais arquivos usar](../docs/OFFICIAL_DATA_MIGRATION.md).

Há preços normalizados (sem moeda), nomes multilíngues, IDs anonimizados e
geografia aproximada. Não há fotos, ingredientes, alergênicos, estoque ou tempo
de entrega.

## Layout

| Caminho | Conteúdo | Como gerar |
| --- | --- | --- |
| `data/raw/dhrd-official-v1/` | ZIPs oficiais extraídos | [pipeline](../docs/DATA_PIPELINE.md) |
| `data/processed/singapore-catalog-v1.sqlite` | Catálogo com índice FTS5/BM25 | `python -m meal_discovery build-catalog` |
| `data/processed/singapore-serving-v1.sqlite` | Popularidade e vizinhos por cesta, ajustados até o dia 61 | `scripts/build_serving_model.py` |
| `models/qwen-local-v1/` | Qwen2.5-1.5B-Instruct Q4_K_M para rodar sem nuvem | `scripts/fetch_local_llm.py` |
| `models/e5-small-onnx-v1/` | E5 multilíngue em ONNX, piloto semântico não promovido | `scripts/fetch_embedding_model.py` |
| `reports/` | Saídas de execuções locais | scripts de avaliação |

Em produção, o catálogo e o modelo de serving vêm de uma
[release do GitHub](https://github.com/luccaamp/mesa-food-discovery-agent/releases/tag/mesa-data-sg-v1)
baixada e conferida por hash na inicialização (`scripts/fetch_deploy_artifact.py`).

Nenhum modelo foi treinado ou ajustado pelo projeto; os pré-treinados são
baixados com revisão e SHA-256 fixados em `configs/`. Pedidos do teste oficial
(dias 76–90) continuam reservados.
