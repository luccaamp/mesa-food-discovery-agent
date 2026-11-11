# API de catálogo real

Atualização v0.7: também serve `GET /v1/discovery/search`, `POST /v1/recommendations`, `POST /v1/assistant`, `GET /v1/system`, `GET /v1/evaluations` e o build React em `/`. O [guia do produto](../../docs/PRODUCT_GUIDE.md) é o ponto de entrada atual. A OpenAPI versionada inclui os novos contratos. A busca lexical original e a cadeia de procedência permanecem disponíveis.

FastAPI sobre os 1.066.840 produtos oficiais de Singapura. Implementação em `src/meal_discovery/api.py`, modelos em `api_models.py` e [contrato OpenAPI](openapi.json).

## Executar

Na raiz do projeto, com Python 3.11+ e índice oficial já preparado:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -c requirements-api.lock -e ".[api,test]"
python -m uvicorn meal_discovery.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

Abrir a [documentação interativa](http://127.0.0.1:8000/docs). O índice padrão é `data/processed/singapore-catalog-v1.sqlite`, relativo ao diretório de execução. Para outro caminho, definir `$env:MEAL_CATALOG_INDEX='C:\caminho\catalogo.sqlite'`. O servidor não carrega `.env` automaticamente nem precisa de chave de IA. Preparação do índice: [Experimento 002](../../docs/EXPERIMENT_002.md).

## Rotas

| Método e rota | Comportamento |
| --- | --- |
| `GET /health` | Processo atende, sem afirmar prontidão dos dados |
| `GET /ready` | Confere estrutura e metadados declarados do índice |
| `GET /v1/catalog/meta` | Versão, origem, hashes, contagens e limitações |
| `GET /v1/catalog/cuisines` | Culinárias e contagem de produtos |
| `GET /v1/catalog/search` | BM25 com `query`, `cuisine`, `min_price`, `max_price`, `limit` |
| `GET /v1/catalog/items/{vendor_id}/{product_id}` | Detalhes pela chave composta original |

Exemplo: [busca por chicken rice](http://127.0.0.1:8000/v1/catalog/search?query=chicken%20rice&limit=5). `query` exige 1–200 caracteres e termos alfanuméricos; `limit`, 1–50. Culinária é um rótulo exato do catálogo. Preços devem ser finitos, não negativos e ordenados. Parâmetros desconhecidos na busca são rejeitados.

Preços são valores normalizados do dataset, sem moeda ou conversão para reais. O catálogo histórico não comprova estoque, entrega, ingredientes ou segurança alimentar. As rotas originais `/v1/catalog` fazem busca literal; `/v1/discovery` acrescenta glossário e `/v1/assistant` usa o planejador documentado no guia. Embeddings não foram promovidos para o produto. BM25 não é probabilidade.

## Erros e rastreabilidade

`422`: consulta inválida; `404`: item ausente; `503`: catálogo ausente, inválido ou sintético. Uma busca válida sem correspondências retorna `200`, contagem zero e lista vazia. Não há fallback sintético ou download automático.

Erros seguem `{"error":{"code":"...","message":"...","request_id":"...","issues":[]}}`. Respostas incluem `X-Request-ID` e `Server-Timing`. O log da aplicação registra ID de requisição, método, modelo de rota, status e duração, sem texto da busca ou IDs de produto. O comando documentado desabilita o access log do Uvicorn, que pode incluir query strings. Não há integração com plataforma de observabilidade.

Cada operação usa sua própria conexão SQLite somente leitura. Não há escrita ou leitura de pedidos do teste oficial. A prontidão confere estrutura e metadados; não recalcula o hash do banco completo por chamada. Os hashes são estabelecidos durante preparação e indexação.

## Verificação

Com o servidor em execução, em outro terminal ativado:

```powershell
python -m unittest discover -s tests -v
python -m pip check
python scripts/check_api.py --base-url http://127.0.0.1:8000 --output reports/api-contracts.json
```

[Relatório real por HTTP](../../evaluations/results/singapore-api-contracts-v1.json): três buscas, filtros, detalhes, contagens, erros e rastreabilidade. Exporta agregados, sem linhas do catálogo ou históricos. Não mede relevância humana ou capacidade sob carga.

Fixtures ficam nos testes com substituição explícita de dependência. Não existe parâmetro HTTP para habilitá-las. A instalação básica sem extras continua disponível; nela os testes da API são pulados explicitamente. Versões diretas e transitivas estão fixadas em `requirements-api.lock`, aplicado como constraints, sem hashes dos pacotes. O CI verifica instalação e testes em Python 3.11/3.13.

Recomendação, planejador local e frontend foram adicionados na v0.7, com contratos próprios na OpenAPI. Embeddings continuam em piloto fora da API de produto. Autenticação, limitação de requisições para acesso externo e implantação pública permanecem pendentes. A versão atual foi verificada em loopback.

Referências: [validação](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/), [erros](https://fastapi.tiangolo.com/tutorial/handling-errors/) e [testes](https://fastapi.tiangolo.com/tutorial/testing/). A integração de testes usa HTTPX2 conforme a versão instalada de Starlette.
