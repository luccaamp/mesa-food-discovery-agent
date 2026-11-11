# Dados e primeira comparação de recomendação

## Distribuição oficial recebida em 7/11/2026

Os três pacotes originais estão extraídos e verificados em `data/raw/dhrd-official-v1/`. Usar `python scripts/verify_official_archives.py` e `python scripts/audit_official_data.py` para reproduzir a inspeção. [Papéis dos arquivos e decisão de fonte](OFFICIAL_DATA_MIGRATION.md). O arquivo completo de pedidos é a união de treino e teste e não deve ser carregado como mais exemplos de treino. A reprodução histórica abaixo continua usando o adaptador do espelho, sem redirecionamento silencioso da origem.

## O que já executa

1. `audit`: inventário de CSVs.
2. `prepare`: valida arquivos com mapeamento explícito e cria um banco SQLite local.
3. `benchmark`: compara popularidade, repetição histórica e similaridade colaborativa de itens.
4. `scripts/fetch_hyperhawkes.py`: baixa a cópia pública real pré-processada do DHRD e verifica o hash.
5. `scripts/fetch_nearbite_sg.py` e `scripts/audit_nearbite_sg.py`: obtêm e auditam as três tabelas reais do espelho público de Singapura.
6. `prepare-singapore`: adapta a versão real fixada por SHA-256, exclui pedidos inteiros com produtos ausentes e preserva contexto.
7. `validate-singapore`: executa a configuração temporal registrada, sem avaliar os dias de teste reservado.

A primeira validação de recomendação em dados reais foi concluída: [Experimento 001](EXPERIMENT_001.md). A preparação específica de Singapura mantém os dados brutos intactos e trata explicitamente índice de exportação, dia textual e quarentena. O comando genérico `prepare` abaixo continua disponível para outros contratos; para esta cópia, usar `prepare-singapore`.

```sh
python -m meal_discovery prepare-singapore --output data/processed/singapore-v1.sqlite
python -m meal_discovery validate-singapore --database data/processed/singapore-v1.sqlite --output reports/singapore-validation-v1.json
```

Saídas existentes não são substituídas. O protocolo em `configs/singapore-experiment-v1.json` fixa treino 0–61, validação 62–68 e teste reservado 69–75. A execução real avaliou todos os 109.842 clientes da validação. Os 35 pedidos com produto ausente foram excluídos inteiros, e as cestas modelam presença de item, consolidando 84.974 repetições. A versão preserva `vendor_context`, `order_context` e `quarantined_orders` no banco local. A quarentena não aparece como pedido válido.

## Obter dados reais agora

Após a instalação descrita no README:

```sh
python scripts/fetch_hyperhawkes.py
```

Esse comando baixa o arquivo real para `data/raw/hyperhawkes-dhrd/` e registra procedência e auditoria. Ver [campos e limites](DATA_ACCESS.md). O comando de demonstração sintética foi removido; CLI de preparação e benchmark exigem dados reais. As fixtures artificiais existem apenas nos testes automatizados.

## Preparar dados reais quando disponíveis

1. Obter arquivos pela fonte oficial; registrar termos, cidade, nomes, tamanho, hashes e divisões fornecidas pelos autores.
2. Inspecionar o formato e os cabeçalhos. Se não forem CSVs compatíveis, implementar e testar uma conversão rastreável, preservando os arquivos originais.
3. Copiar `configs/source.example.json` para `configs/source.local.json` (ignorado pelo Git).
4. Substituir caminhos, cidade, licença e nomes das colunas pelos valores realmente observados. Cada caminho é relativo à pasta do JSON. Não usar o exemplo sem ajuste.
5. Executar a preparação, corrigindo ambiguidades na origem ou criando uma transformação documentada; o importador não remove silenciosamente órfãos ou escolhe um preço entre valores conflitantes.

```sh
python -m meal_discovery prepare --config configs/source.local.json --output data/processed/city-v1.sqlite
```

O manifesto fica dentro do banco na tabela `metadata`. Ele registra hashes, configuração, procedência declarada, período e contagens, sem publicar pedidos. `data_kind` vem da configuração: é um rótulo de procedência informado pelo operador, não certificação da autenticidade dos arquivos.

## Contrato de integridade

- Vendedor é único por `vendor_id`.
- Produto é único pelo par `(vendor_id, product_id)`, evitando colisões entre estabelecimentos.
- Pedido é único por `order_id` e tem cliente, dia relativo inteiro e horário local consistentes em todas as linhas.
- O horário deve ser representável como `HH:MM[:SS[.ffffff]]`; não interpretar automaticamente timestamps de formato desconhecido.
- Linhas do mesmo item no mesmo pedido são deduplicadas. A tarefa é presença de item na cesta, não quantidade.
- Referências a produtos e vendedores ausentes, chaves conflitantes, larguras inválidas, IDs vazios e preços não finitos são erros explícitos.
- Preço pode estar vazio. Valor observado é normalizado, sem conversão monetária.
- Arquivos são verificados por hash antes e depois da importação. O banco é publicado somente após validação; saída existente não é sobrescrita.

SQLite foi escolhido nesta etapa pelo suporte transacional e ausência de dependência extra. Parquet/DuckDB continuam opções futuras se os arquivos e o custo de processamento justificarem. A escolha não foi baseada em benchmark de escala real.

## Como avaliar sem usar o futuro

O comando genérico `benchmark` exige `--train-end-day` e `--eval-end-day`; o comando específico `validate-singapore` lê os cortes da configuração versionada. Treino usa todos os pedidos até o primeiro limite, inclusive; avaliação usa o período seguinte até o segundo limite, inclusive. Cortes não devem ser escolhidos a partir do teste ou copiados de fixtures.

Para cada cliente, o alvo é sua primeira cesta no período de avaliação. O treino fica congelado: outras compras posteriores não atualizam o perfil. Empates são resolvidos por dia, horário e ID do pedido. Não há atualização progressiva neste protocolo inicial.

Referências:

- **Popularidade:** quantidade de cestas de treino contendo o item.
- **Repetição:** frequência do item nas cestas de treino do cliente, completada com popularidade.
- **Similaridade por cesta (`basket_cosine`):** cosseno entre presenças de itens em pedidos históricos, com redução de confiança para poucas co-compras. Somar pesos dos vizinhos a partir de até vinte itens frequentes do perfil; completar com popularidade. Recompras são permitidas.

Cada ranking tem IDs únicos e desempate determinístico. Métricas são médias por cliente: Recall@K, NDCG@K e Hit Rate@K. A relevância é binária por item; NDCG usa ganho 1/log2(posição+1). Há segmentos de clientes conhecidos/novos, cobertura do catálogo e latências p50/p95.

O catálogo candidato contém somente itens comprados no treino. Itens-alvo novos permanecem no denominador e contam como falhas. O relatório informa essa cobertura. Não há negativos amostrados nem filtro geográfico ainda; o experimento mede afinidade em catálogo histórico de uma cidade, sem comprovar disponibilidade ou possibilidade de entrega.

`--max-users` limita aos primeiros clientes por ordem cronológica e serve para testar execução/tempo. Esse recorte não é amostra representativa, nem resultado final de portfólio. A execução real não usou esse limite. O candidato padrão agora é `basket_cosine`: co-presença de itens em pedidos, até 100 vizinhos por semente, até 20 sementes por perfil, cosseno com redução de confiança e cache local. O `item_cosine` original por compradores em comum permanece no código e não participou do Experimento 001. O relatório e o artigo do experimento registram a definição exata.

`--split validation` e `--split test` são rótulos no relatório. O programa não impede repetir consultas ao teste. Manter o teste reservado exige disciplina e registro das decisões. Resultados dos splits distribuídos pelos autores só serão comparados depois de entender seu protocolo.

Cada relatório inclui hashes da base, fontes e implementação, além do protocolo. Ainda não escolhemos hiperparâmetros, cidade nem cortes para DHRD.
