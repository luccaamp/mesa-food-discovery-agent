# data/

Dados brutos e processados ficam aqui, fora do Git. Procedência, pipeline,
contrato de integridade e divisões temporais estão em [docs/DATA.md](../docs/DATA.md).

| Caminho | Conteúdo |
| --- | --- |
| `raw/dhrd-official-v1/` | ZIPs oficiais do DHRD extraídos e conferidos |
| `processed/singapore-official-v1.sqlite` | Pedidos de treino de Singapura, preparados |
| `processed/singapore-catalog-v1.sqlite` | Catálogo com índice FTS5/BM25 |
| `processed/singapore-serving-v1.sqlite` | Popularidade e vizinhos por cesta (dias 0–61) |
