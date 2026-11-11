# Executar e demonstrar o Mesa

## Resultado desta versão

Produto publicado no [Render Free](https://mesa-meal-discovery.onrender.com): catálogo real completo, busca PT/EN por glossário explícito, seleção de itens, recomendações por cestas e laboratório com resultados versionados. A versão local usa Qwen. A pública usa Gemini 3.1 Flash-Lite, testado em consultas reais; indisponibilidade ou cota acionam o modo essencial explícito. Automação n8n executada localmente. Estudos com pessoas ainda não foram realizados.

## Preparação

Python 3.11+ e Node 22.15+ para o frontend testado; Node 24 para o n8n atual. Dentro da raiz do repositório:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -c requirements-api.lock -e ".[api,test]"
npm --prefix apps/web ci
npm --prefix apps/web run build
```

O piloto semântico é opcional para o produto. Suas dependências e execução estão no Experimento 003.

Com os ZIPs oficiais já verificados e extraídos:

```powershell
python -m meal_discovery prepare-official-singapore --output data/processed/singapore-official-v1.sqlite
python -m meal_discovery build-catalog --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-catalog-v1.sqlite
python scripts/build_serving_model.py --database data/processed/singapore-official-v1.sqlite --output data/processed/singapore-serving-v1.sqlite
python scripts/fetch_local_llm.py
```

**Estes arquivos já foram preparados nesta máquina.** Não repetir preparação em saídas existentes; as ferramentas as protegem contra sobrescrita. O download local é explícito: aproximadamente 1,12 GB de pesos Qwen mais 25 MB do runtime Windows. Arquivos são fixados por revisão, tamanho e SHA-256; não há instalador global ou serviço de sistema.

## Iniciar

```powershell
.venv\Scripts\python scripts/run_local.py
```

Abrir [http://127.0.0.1:8000](http://127.0.0.1:8000). O launcher usa o modelo em 8081 e a API/interface em 8000, ambos somente loopback. Ctrl+C encerra os processos que ele iniciou. Se portas estiverem ocupadas, encerrar a instância anterior antes de iniciar outra. `--no-llm` permite executar catálogo e glossário sem carregar o modelo; esse modo é identificado na conversa.

O launcher Windows usa o runtime portátil verificado. Em outro sistema operacional, instalar o runtime oficial apropriado, iniciar o endpoint compatível em 8081 e executar Uvicorn com as mesmas variáveis. Não afirmar que o launcher Windows já foi testado em Linux.

## Roteiro de demonstração

1. Explorar “chá com leite” ou “arroz com frango”. Conferir a consulta resolvida em inglês e o nome original dos produtos.
2. Abrir “Ver evidências”. Explicar chave composta, culinária, origem histórica e preço normalizado. Zero normalizado não significa gratuidade.
3. Selecionar itens como referências e clicar “Descobrir sugestões”. Distinguir associação por cestas de fallback por popularidade.
4. No assistente, pedir um prato e depois “até 0,002 unidades normalizadas”. Conferir estado, filtros e chamadas na seção de evidências. “Recomende algo” é uma ação explícita que consulta o recomendador sem LLM; a resposta preserva motivo e contagens.
5. Pedir algo “sem glúten” ou com orçamento em reais. Explicar por que o catálogo não permite garantir a restrição ou converter a moeda.
6. No laboratório, interpretar NDCG e mostrar o resultado negativo do piloto semântico.
7. Executar a automação descrita em [workflows/n8n](../workflows/n8n/README.md) e verificar o relatório gerado.

## Como o assistente funciona

Quando ativo, o modelo produz um plano com ação permitida e consulta curta. Pydantic valida o plano; a aplicação executa apenas busca ou recomendação. O resultado usa nomes, IDs, preços e culinárias fornecidos pelas ferramentas. Não há geração livre de fatos do catálogo. Políticas, recomendações explícitas e refinamentos de preço dispensam o modelo.

A conversa não persiste histórico pessoal no servidor. O contexto estruturado fica no estado da aba. Chamadas têm timeout, limite de tokens e rastros retornados ao usuário. O log padrão não registra mensagem, corpo da requisição ou query string.

O adaptador comercial OpenAI existe, com endpoint fixo, chave no ambiente e function calling estrito; continua **não executado** contra o provedor. Não enviar chave pelo chat nem colocá-la no frontend/Git. A evidência de LLM desta versão é exclusivamente local.

## Evidência e limites

- 13/13 contratos reais de desenvolvimento passaram; 48 itens foram conferidos contra a rota de detalhe. Nova execução com 7 chamadas Qwen, 2.252 tokens e mediana local de 618,86 ms em [product-flow-v2.json](../evaluations/results/product-flow-v2.json). O registro anterior permanece preservado.
- O modelo de recomendação usa 1.410.654 pedidos de treino, 228.822 itens observados e 2.165.201 relações direcionadas persistidas. Teste oficial não avaliado. A interação com seleção de itens não é o protocolo de benchmark de históricos pessoais.
- O n8n executou três nós e consolidou dois relatórios. Não foi medido tempo de tarefa manual; não declarar economia percentual.
- Layouts verificados em 360, 768 e 1440 pixels CSS, sem overflow horizontal. Contraste de seis textos principais corrigido e medido; não é auditoria completa de acessibilidade.
- Não há revisão humana de relevância, estudo com usuários, comparação real de dois provedores ou comprovação de impacto comercial.

## Publicação

Interface e backend estão no Render Free com índices verificados dentro da imagem Docker. Qwen, embeddings, preparação dos dados e n8n continuam locais. Sem chave Gemini ou sem cota, a conversa informa o uso do glossário. [Arquitetura, limites e segredo](CLOUD_DEPLOYMENT.md).
