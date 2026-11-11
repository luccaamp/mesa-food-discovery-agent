# Meal Discovery AI — relatório automatizado

Fonte: API local de avaliações versionadas. Teste oficial não avaliado.

## Recomendação temporal

Clientes de validação: 175358

| Modelo | Recall@10 | NDCG@10 |
| --- | ---: | ---: |
| popularity | 0.002606 | 0.001243 |
| repeat | 0.144442 | 0.115707 |
| basket_cosine | 0.062262 | 0.039786 |

## Recuperação experimental

Produtos: 10000. Consultas: 12.

Rótulos automáticos fracos, não julgamentos humanos. Não comparar estes números diretamente com recomendação.

| Método | NDCG@10 — proxy |
| --- | ---: |
| lexical | 0.459479 |
| semantic | 0.330524 |
| hybrid | 0.437592 |

Limites: avaliação offline, sem comprovação de conversão, receita, disponibilidade ou preferência individual.
