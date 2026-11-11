# Experimento 003 — embeddings e busca híbrida em piloto

## Decisão

Foi implementada e executada a recuperação por embeddings multilíngues, mas ela permanece experimental. Os resultados de desenvolvimento não justificam substituir a busca lexical da API nem afirmar compreensão confiável de português.

O piloto usa **10.000 produtos reais**, aproximadamente **0,94%** do catálogo oficial de Singapura. A API lexical continua cobrindo 1.066.840 produtos. Não confundir essas duas coberturas.

## Fonte, modelo e corpus

O [protocolo de indexação](../configs/semantic-pilot-v1.json) foi registrado antes da execução. A seleção usa os menores SHA-256 das chaves compostas com uma semente fixa, sem consultar nomes, consultas ou interações de teste. Nenhum produto foi inventado ou escolhido por acertar uma consulta.

Modelo base: [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small). A execução usa a conversão ONNX quantizada [Xenova, revisão fixada](https://huggingface.co/Xenova/multilingual-e5-small/tree/761b726dd34fb83930e26aab4e9ac3899aa1fa78), com dois arquivos de 135.390.915 bytes no total. Ambos foram baixados e conferidos por tamanho e SHA-256. Pesos não são publicados no repositório. É inferência de um modelo pré-treinado, sem treinamento ou fine-tuning próprio.

Inferência local em CPU com ONNX Runtime, quatro threads, vetores de 384 dimensões, limite de 128 tokens, pooling por média com máscara de atenção e normalização L2. O texto do documento contém nome e culinária, com prefixo `passage: `; consultas recebem `query: `, inclusive em português, conforme o model card. Preço permanece um filtro, fora do texto do embedding.

O SQLite experimental contém catálogo, FTS5 e vetores float32. A busca densa usa cosseno exato, com filtros aplicados antes de ordenar. A busca híbrida combina os primeiros 50 candidatos de cada método por Reciprocal Rank Fusion com constante 60. Não há índice ANN, LLM ou chamada paga.

[Manifesto do piloto](../evaluations/results/semantic-pilot-preparation-v1.json): hashes de origem, protocolo, seleção e pesos; quantidade indexada e fração do catálogo. Pedidos de teste oficial não são usados. Índices existentes não são sobrescritos e pesos alterados são rejeitados.

## Avaliação de desenvolvimento

[Protocolo de consultas](../configs/retrieval-development-v1.json): doze consultas elaboradas com assistência de IA, seis conceitos em português e inglês. Os três métodos usam o mesmo corpus de 10.000 produtos e K=10.

**Os rótulos são regras automáticas sobre os nomes originais, não julgamentos humanos.** Por exemplo, “arroz com frango” exige as palavras `chicken` e `rice` no nome para ser um positivo desta métrica auxiliar. Variações e alternativas legítimas podem receber rótulo negativo; culinária sozinha não comprova a composição de um prato. A avaliação é pequena, de desenvolvimento, e não constitui teste reservado de relevância.

| Método | NDCG@10 em PT, proxy | NDCG@10 em EN, proxy | NDCG@10 geral, proxy |
| --- | ---: | ---: | ---: |
| Lexical | 0,0000 | **0,9190** | **0,4595** |
| Semântico | 0,0479 | 0,6131 | 0,3305 |
| Híbrido | 0,0479 | 0,8273 | 0,4376 |

[Resultados completos](../evaluations/results/retrieval-development-v1.json), com consultas, contagens, métricas, versões e fingerprints. A falta de correspondência literal em português explica parte do resultado lexical. A recuperação semântica encontrou alguns resultados relacionados, mas não demonstrou qualidade suficiente. Híbrido não superou lexical na média deste proxy; nenhum ganho geral é declarado.

## Inspeção de erros

Na inspeção assistida por IA, “chá com leite” recuperou `Chai Tea Latte` e `Matcha Latte`, alternativas que a regra das palavras `milk` e `tea` não reconhece. Isso evidencia um limite do rótulo automático, sem confirmar preferência do usuário.

“Arroz com frango” recuperou arroz simples em posições altas, incluindo itens de culinária vegetariana. “Café gelado” trouxe itens de gelatina/jelly. A pontuação alta de cosseno não garante correspondência da intenção. Culinária no texto pode ajudar ou introduzir ruído; ainda não houve ablação controlada que atribua causa a esse comportamento.

Ainda não foram isolados os efeitos da quantização, do modelo pequeno e da formulação do documento. Não ajustar regras ou consultas depois de ver os resultados para apresentar um ganho como independente. O próximo experimento deve fixar novas hipóteses e parâmetros antes de medir.

## Revisão humana preparada

Foi gerado localmente `reports/retrieval-review-v1.json`, com doze consultas, candidatos reais agrupados dos três métodos e rubrica 0/1/2. Todos os julgamentos permanecem `null`, com status `pending_human_review`; nenhum avaliador humano foi atribuído. O arquivo contém nomes do catálogo e fica fora do Git. É um pool de desenvolvimento com rankings visíveis, sem anotação cega ou cobertura completa de relevância.

Próximos passos: revisar esse pool, criar consultas adicionais sem usar os resultados para escolhê-las e separar casos de desenvolvimento de uma avaliação reservada. Comparar outro encoder ou normalização de consulta somente em experimento versionado; expandir corpus e integrar ao produto após evidência suficiente.

## Reproduzir

Na raiz do projeto, com ambiente virtual ativado e catálogo oficial preparado:

```powershell
python -m pip install -c requirements-api.lock -c requirements-semantic.lock -e ".[api,test,semantic]"
python scripts/fetch_embedding_model.py
python -m meal_discovery build-semantic --index data/processed/singapore-catalog-v1.sqlite --output data/processed/singapore-semantic-pilot-v1.sqlite
python -m meal_discovery search-semantic --index data/processed/singapore-semantic-pilot-v1.sqlite --query "arroz com frango" --mode hybrid --limit 5
python scripts/evaluate_retrieval.py --index data/processed/singapore-semantic-pilot-v1.sqlite --output reports/retrieval-development.json
python scripts/prepare_relevance_review.py --index data/processed/singapore-semantic-pilot-v1.sqlite --output reports/retrieval-review.json
```

Escolher novas saídas ao repetir. Downloads são explícitos; a busca não acessa a rede para baixar pesos. A instalação básica e a API lexical continuam sem dependências de embeddings. O CI usa fixtures identificadas para testar contratos e matemática, sem baixar pesos ou apresentar vetores de teste como inferência real.
