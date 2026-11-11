# Dados reais obtidos e acesso à distribuição original

Atualizado em 7/11/2026. **O usuário forneceu os três ZIPs oficiais e o README. A distribuição completa foi verificada e extraída: quinze arquivos, três cidades e 4.400.000 pedidos.** Os hashes dos pacotes coincidem com a referência OmniRec, e a comparação dos campos de Singapura confirmou a cópia anterior. [Decisão de quais dados usar e auditoria](OFFICIAL_DATA_MIGRATION.md). O [registro da busca anterior](SOURCE_SEARCH_2026-11-06.md) foi mantido como histórico.

## Fonte principal atual: distribuição oficial

Dados em `data/raw/dhrd-official-v1/data_sg/`, `data_se/` e `data_tw/`, ignorados pelo Git. Arquivos originais enviados pelo usuário foram preservados na raiz do workspace. [Manifesto agregado](../evaluations/results/official-archives-manifest-v1.json) e [registro de fontes](../configs/official-source-selection-v1.json).

Usar Singapura como cidade principal, com `orders_sg_train.txt`, `products_sg.txt` e `vendors_sg.txt`. Reservar `orders_sg_test.txt` para avaliação final. `orders_sg.txt` já contém treino e teste: serve para auditoria e não deve ser somado aos outros arquivos como mais observações. Estocolmo e Taipei permanecem como cidades separadas para etapas posteriores.

Os três conjuntos oficiais têm teste temporal separado, sem IDs de pedido compartilhados entre treino/teste. O teste SG cobre 76–90; os testes SE/TW cobrem 76–89. Nenhuma métrica de modelo foi calculada nos testes oficiais. A preparação atual de reprodução do Experimento 001 continua fixada no espelho; sua migração para os originais será uma nova versão explícita.

As seções abaixo descrevem as fontes históricas usadas antes de o acesso oficial ser liberado.

## Fonte histórica: espelho público de Singapura

Fonte dos links: [NearBite, revisão fixada](https://github.com/jpchawanda1/nearbite-recommender/blob/a58e7255e22fbf7ed60f4854c041a41ba5a5c454/scripts/download_data.py). O autor declara origem DHRD e informa que adicionou latitude/longitude decodificadas de geohash aos pedidos e estabelecimentos. Não executamos código de terceiros; implementamos downloader e auditor próprios. Os dados são identificados como `real_third_party_copy`: disponibilidade, formato e contagens foram verificados, mas não há comparação byte a byte com o pacote original.

```sh
python scripts/fetch_nearbite_sg.py
python scripts/audit_nearbite_sg.py
```

Arquivos locais em `data/raw/nearbite-sg/`; total de 419.360.922 bytes. O manifesto registra URLs, SHA-256 e cabeçalhos. O relatório completo local é `reports/nearbite-sg-audit.json`.

| Conteúdo verificado | Contagem |
| --- | ---: |
| Linhas de itens comprados | 3.431.870 |
| Pedidos distintos | 1.709.414 |
| Clientes distintos | 476.150 |
| Produtos do catálogo | 1.066.840 |
| Estabelecimentos | 7.411 |
| Estabelecimentos presentes em compras | 7.203 |
| Categorias de culinária distintas | 78 |
| Dias relativos | 0 a 75 (76 dias) |

Campos de catálogo: vendedor, produto, nome e preço normalizado. Estabelecimentos: vendedor, rede, geohash e culinária. Pedidos: cliente, geohash, pedido, vendedor, produto, dia da semana, horário e dia relativo. Colunas de índice de exportação são preservadas nos arquivos originais locais e devem ser ignoradas explicitamente na preparação.

Integridade observada: zero chaves duplicadas de vendedor/produto; zero referências a vendedores inexistentes; zero pedidos com cliente/dia/horário conflitantes; zero preços inválidos ou negativos. **41 linhas de compra apontam para produtos ausentes no catálogo.** A preparação `singapore-v1` colocou em quarentena os 35 pedidos afetados por inteiro (77 linhas). Também consolidou 84.974 linhas repetidas por item/pedido para a tarefa binária de cesta. [Relatório de preparação e primeira validação](EXPERIMENT_001.md). O auditor usa banco temporário local para verificar todas as relações e o remove ao concluir.

Hashes SHA-256:

- `vendors_sg_clean.csv`: `a0c4987daa7bd9f84b57ac04169fc04f7e9004d579884aa9c0a412a37d6c0f80`.
- `products_sg.csv`: `63e981a45619a3a7e62af8a037ffb641e7410fee35e26b4882f9db6de5e1385c`.
- `orders_sg_train_clean.csv`: `4d3ceb436c2f66872663357df223fb45b7cff9753c60ca70cd180f62d7acf1c6`.

O espelho não contém teste oficial separado nem arquivos completos das outras duas cidades; esses arquivos agora estão na distribuição oficial recebida. Preço não é valor em reais; geohash/coordenadas decodificadas não são localização exata ou confirmação de raio de entrega. O adaptador de reprodução trata índice e dias textuais explicitamente. Os campos originais da cópia foram comparados linha a linha e coincidem com os arquivos oficiais de Singapura.

## Distribuição acadêmica disponível

Os autores de [HyperHawkes, WWW 2025](https://github.com/dbis-uibk/HyperHawkes) publicam o arquivo `dataset/dhrd/dhrd.inter`. É um derivado pré-processado do DHRD, não uma base inventada nem uma reprodução integral do pacote original. O artigo identifica o recorte DHRD utilizado como Stockholm. As contagens após filtros de treinamento do artigo não devem ser confundidas com as contagens do arquivo distribuído.

Download reproduzível:

```sh
python scripts/fetch_hyperhawkes.py
```

Destino local: `data/raw/hyperhawkes-dhrd/dhrd.inter`. O dataset não é enviado ao GitHub deste projeto. O script fixa a revisão `df2b334bf6444e0da03a1879a2cb8132fa6e71fa`, exige 49.974.096 bytes e confere o hash do objeto Git `1f7c89bf9f3ba91bd6fe526ea44467ac7f45db02`. SHA-256 observado: `57489a010678749186eac350d7c4ed547447553b6cbbc2d4ef647e6e4b355399`.

## Auditoria observada

| Conteúdo | Contagem |
| --- | ---: |
| Interações (linhas) | 740.707 |
| Usuários distintos | 122.931 |
| Itens distintos | 41.695 |
| IDs de estabelecimentos distintos | 1.148 |
| Sessões distintas | 394.040 |

Campos presentes: `user_id`, `item_id`, `timestamp`, `item_name`, `vendor_id`, `session_id`. Nenhum campo vazio observado. Nenhum item foi associado a múltiplos nomes/vendedores; não houve sessão associada a usuários distintos. Intervalo numérico dos timestamps cobre aproximadamente 90 dias; não inferir calendário local ou fuso a partir disso.

Limites: não há preço, `primary_cuisine`, geohash, fotos ou ingredientes. Sessões não devem ser automaticamente declaradas como pedidos originais. Ainda faltam auditar transformações, precisão dos timestamps, semântica das sessões e efeito da seleção da população antes de definir o protocolo final. É preciso adaptar o formato tabulado ao pipeline; não há treinamento ou métrica real publicado ainda.

O repositório HyperHawkes informa GPL-3.0 para seu código; o DHRD original informa MIT. Nosso downloader não copia nem executa o código dos autores. Preservar as referências de ambas as fontes e não presumir que as licenças de código e dados sejam intercambiáveis.

## O que foi investigado

- O [DHRD oficial](https://github.com/deliveryhero/dh-reco-dataset) indica apenas a pasta do Drive como distribuição; não foi localizada API pública de download do DHRD na pesquisa.
- A [issue #1](https://github.com/deliveryhero/dh-reco-dataset/issues/1) e um comentário de outro pesquisador relatam a exigência de autorização.
- O link direto para `data_sg.zip` citado em `karapostK/hassaku/data/data_utils.py` também redirecionou para login. Conhecer o ID do arquivo não forneceu acesso.
- Repositórios de análises e o fork do DHRD foram inspecionados; não forneceram uma cópia completa confirmada do pacote original.
- Uma pasta pública usada em um curso foi localizada, mas não foi confirmada como distribuição completa do DHRD; não foi usada como fonte do dataset.

Não foi enviada mensagem a terceiros. Não foi contornada a autorização do Drive: a cópia obtida é um arquivo público do GitHub dos pesquisadores.

## Política de dados reais

Aplicação, demonstrações de portfólio e experimentos exigem dados reais. Não há fallback para dados sintéticos. O comando público `demo` foi removido, e preparação/benchmark rejeitam fontes marcadas como sintéticas. Fixtures pequenas são restritas a `tests/`; a habilitação interna de teste não é exposta na CLI. O rótulo de procedência em importações genéricas é declarado pelo operador; o downloader da cópia derivada acrescenta verificação efetiva do hash de uma fonte fixa.
