# Dados: procedência, pipeline e artefatos

## Fonte

[Delivery Hero Recommendation Dataset](https://github.com/deliveryhero/dh-reco-dataset)
(DHRD, RecSys 2023, licença MIT declarada pelo publicador). A distribuição oficial
tem três ZIPs (Singapura, Estocolmo e Taipei), 4.400.000 pedidos e 15 arquivos.
Os SHA-256 dos ZIPs coincidem com os publicados pelo carregador OmniRec, e cada
membro extraído teve CRC e tamanho conferidos
([manifesto](../evaluations/results/official-archives-manifest-v1.json),
[auditoria](../evaluations/results/official-data-audit-v1.json)).

**O projeto usa Singapura,** a cidade com o catálogo mais amplo e com culinária,
rede e geohash por restaurante:

| Arquivo | Conteúdo | Uso |
| --- | --- | --- |
| `orders_sg_train.txt` | 1.709.414 pedidos, dias 0–75 | Análise, treino e validação temporal |
| `orders_sg_test.txt` | 290.586 pedidos, dias 76–90 | Teste final, usado **uma vez** ([Experimento de descoberta](EXPERIMENT_DISCOVERY.md)) |
| `products_sg.txt` | 1.066.840 itens: nome, restaurante e preço normalizado | Catálogo |
| `vendors_sg.txt` | 7.411 restaurantes: culinária, rede e geohash | Contexto |
| `orders_sg.txt` | União de treino e teste | Só auditoria; nunca entra no treino |

Os `.txt` são CSV UTF-8 com uma coluna inicial de índice, ignorada
explicitamente. O DHRD não traz fotos, ingredientes, alergênicos, estoque, tempo
de entrega nem moeda: o preço é normalizado numa escala não publicada (máximo
1,0), e 27,6% dos itens registram 0, que significa preço ausente.

## Pipeline

```text
ZIPs oficiais ──verify_official_archives.py──► data/raw/dhrd-official-v1/   (SHA-256 + CRC, nada sobrescrito)
       │
       └─ prepare-official-singapore ──► singapore-official-v1.sqlite        (só o treino; teste fica no arquivo)
              │   quarentena: 35 pedidos com produto ausente saem inteiros (77 linhas)
              │   84.974 linhas repetidas viram presença única do item na cesta
              │
              ├─ build-catalog ─────────────► singapore-catalog-v1.sqlite   (FTS5/BM25, 1.066.840 itens)
              ├─ build_serving_model.py ────► singapore-serving-v1.sqlite   (popularidade e vizinhos por cesta, dias 0–61)
              ├─ build_price_bands.py ──────► price-bands-v1.json           (tercis de preço por culinária, 77 KB)
              ├─ build_context_popularity ──► context-popularity-v1.json    (mais pedidos por região × horário, 203 KB)
              └─ analysis/*.py ─────────────► evaluations/results/*.json    (análise e experimentos, só agregados)
```

```sh
python scripts/verify_official_archives.py --archive-dir .
python -m meal_discovery prepare-official-singapore --output data/processed/singapore-official-v1.sqlite
python -m meal_discovery build-catalog --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-catalog-v1.sqlite
python scripts/build_serving_model.py --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-serving-v1.sqlite
python scripts/build_price_bands.py
python scripts/build_context_popularity.py
```

Resultado: 1.709.379 pedidos, 3.346.819 presenças de itens em cestas, 1.066.840
itens e 7.411 restaurantes ([manifesto agregado](../evaluations/results/singapore-official-preparation-v1.json)).

## Contrato de integridade

- Restaurante é único por `vendor_id`; item, pelo par `(vendor_id, product_id)`.
- Pedido é único por `order_id`, com cliente, dia e horário consistentes em todas as linhas.
- Todo pedido do DHRD tem um único restaurante; a análise verifica isso em vez de presumir.
- Referências ausentes, chaves conflitantes, IDs vazios e preços não finitos são erros explícitos.
- Arquivos são conferidos por hash antes e depois da importação, e o banco só é publicado depois de validado.
- Nenhuma ferramenta sobrescreve uma saída existente.

## Divisões temporais

| Janela | Dias | Uso |
| --- | --- | --- |
| Treino | 0–61 | Artefato de recomendação do produto; histórico da validação |
| Validação | 62–75 | Escolha de modelos (protocolo v2 e Experimento de descoberta) |
| Teste oficial | 76–90 | Uma única rodada, depois de a validação estar no Git |

## O que vai para produção

O deploy baixa uma release do GitHub (`mesa-data-sg-v1`) com o catálogo e o
artefato de recomendação, conferida por SHA-256 em
[`deploy/catalog-serving-sg-v1.json`](../deploy/catalog-serving-sg-v1.json). Os
dois artefatos pequenos (faixas de preço e região × horário) são versionados no
pacote Python. Nenhum artefato público contém pedidos ou clientes individuais.

Os nomes de bairro do produto aproximam o centro de cada célula geohash de cerca
de 5 km; o dado em si é só o geohash.
