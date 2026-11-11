# Busca pela distribuição completa DHRD

**Atualização de 7/11/2026:** o usuário forneceu os três ZIPs oficiais e o README. Todos foram verificados por hash/CRC, extraídos e auditados; a distribuição completa está disponível localmente. [Fonte principal atual e comparação](OFFICIAL_DATA_MIGRATION.md). As seções abaixo preservam a situação e a pesquisa anteriores ao recebimento dos arquivos.

Pesquisa em 6/11/2026. Objetivo: localizar pedidos, catálogo e estabelecimentos de Singapura, Estocolmo e Taipei, incluindo teste original quando fornecido. As conclusões descrevem esta pesquisa; não provam inexistência de outra cópia na internet.

## Cobertura obtida

| Cidade | Compras | Catálogo e nomes | Preço, culinária e geohash | Teste oficial separado |
| --- | --- | --- | --- | --- |
| Singapura | Cópia de treino, dias 0–75, baixada | Tabela de produtos e de vendedores baixadas | Presentes | Não localizado acessível |
| Estocolmo | Derivado HyperHawkes, baixado | Nomes e IDs de vendedores no derivado | Ausentes no derivado | Não localizado acessível |
| Taipei | Nenhum pacote completo obtido | Não obtido | Não obtido | Não obtido |

O objetivo de obter tudo ainda não foi alcançado. O avanço principal é uma cópia mais rica de Singapura com três tabelas auditadas, suficiente para desenvolver o recorte de produto com dados reais após a preparação. Um teste temporal próprio pode ser reservado dentro dos 76 dias, com protocolo distinto do teste oficial original.

## Onde a distribuição original deveria estar

O [repositório oficial DHRD](https://github.com/deliveryhero/dh-reco-dataset) aponta para [uma pasta Google Drive](https://drive.google.com/drive/folders/1dCUvFVmt9xNOGgadql_O16SwtGy6e_hE). O usuário já solicitou acesso. A [issue #1](https://github.com/deliveryhero/dh-reco-dataset/issues/1) e comentário adicional relatam o mesmo bloqueio.

O carregador público [OmniRec](https://github.com/ISG-Siegen/OmniRec/blob/9800bd4e75d321d37be78de4d33ba72b73d8b92e/src/omnirec/data_loaders/deliveryhero.py) registra os três ZIPs e seus SHA-256 de referência:

| Arquivo | ID público indicado pelo carregador | SHA-256 indicado |
| --- | --- | --- |
| `data_se.zip` | `11OsafYu26ISaUfGEXzFSwNyKDJxKCy8e` | `2a3947bd29a892a634882b0ec45e4d47a09e68dfdc74fca353b53467eeb43da4` |
| `data_sg.zip` | `1v-FfCbLtv02EpNpopDx25EQnHZeT1nL2` | `55a94a5c7eeba9610776b864aae7d653426afdb8aae93e5fa5050cbdc1c25d32` |
| `data_tw.zip` | `1Td7sTeJ7xcP8DLcY4bOQ_JqWUdqT93Ox` | `83e8c0f5bfb4c27f14e3dd13964cc72117975397d7bee2522336301eaed781ec` |

Os três downloads diretos foram testados e redirecionaram para login, em vez de retornar ZIP. Não foram baixados. Usar o ID diretamente, gdown ou a API do Drive não concede permissão a arquivos restritos. Esses hashes serão úteis para conferir o pacote se o acesso for liberado.

## Cópias e projetos inspecionados

| Fonte | Resultado |
| --- | --- |
| [NearBite](https://github.com/jpchawanda1/nearbite-recommender) | Três links públicos de Singapura acessíveis. 419.360.922 bytes baixados; tabelas e relações auditadas. [Detalhes](DATA_ACCESS.md). |
| [HyperHawkes](https://github.com/dbis-uibk/HyperHawkes) | Derivado de Estocolmo com seis campos. 49.974.096 bytes baixados e verificados pelo objeto Git fixado. |
| [RHYTHM](https://github.com/RongZhu735/RHYTHM) | Arquivo DHRD processado de 13.446.207 bytes disponível; não fornece o pacote original completo nem os metadados que faltam. Não adotado como substituto do original. |
| [hassaku](https://github.com/karapostK/hassaku) | Aponta para o mesmo ZIP original restrito de Singapura. |
| [AgenticRecommender](https://github.com/consistentJake/AgenticRecommender) | Código referencia arquivos de treino/teste/produtos/vendedores locais; nenhum pacote completo público foi confirmado na árvore inspecionada. |
| [Leap Case](https://github.com/ErlingAmundsen/Leap-Case-Food-Delivery), [análise DHRD](https://github.com/densmyslov/delivery-hero-dataset), [DH DataVisualisation](https://github.com/jeromelim/DH_DataVisualisation) | Notebooks, código e resultados; pacote original completo não encontrado nas árvores inspecionadas. |
| [Taiwan Foodpanda Trends](https://github.com/Tiff-Tam23/taiwan-foodpanda-trends) | Refere-se às três tabelas TW, mas o pacote não foi encontrado no repositório público. |
| [Foodora Dataverse](https://github.com/oviyasekar11/foodora-dataverse) | A documentação declara dados sintéticos; descartado como fonte real. |

O fork público do repositório oficial foi conferido na etapa anterior; contém a documentação, não o dataset integral.

## Catálogos e APIs pesquisados

- **GitHub:** busca por repositório, conteúdo e nomes exatos como `orders_se_train.txt`, `orders_sg_test.txt`, `products_se.txt`, `vendors_se.txt` e `data_tw.zip`; inspeção de árvores e scripts de distribuição. Isso revelou NearBite e os links/checksums originais do OmniRec.
- **Kaggle:** API pública de datasets, buscas `DHRD`, `Delivery Hero Recommendation` e `delivery hero`. Não apareceu uma distribuição confirmada do DHRD; resultados amplos incluíam avaliações Foodpanda, que são outro conjunto de dados e não foram unidos ao DHRD.
- **Hugging Face:** API pública por `deliveryhero`, `delivery hero`, `delivery-hero`, `dh-reco` e `dhrd`. Nenhuma distribuição completa pertinente confirmada; coincidências de sigla não foram consideradas evidência de origem.
- **Zenodo e DataCite:** consultas pelo título completo; nenhuma distribuição pertinente encontrada.
- **Internet Archive:** consulta pelo título completo; nenhum registro correspondente retornado nessa busca.
- **Web:** páginas dos autores, artigos, referências e projetos de pesquisa. Páginas comerciais de scraping não foram tratadas como DHRD nem como prova de acesso a pedidos anonimizados históricos.

APIs comerciais de integração Delivery Hero são destinadas a operações de parceiros e não constituem uma API pública do DHRD. Não foi acessado banco privado nem usada credencial de terceiro. Não foi enviado pedido ou mensagem aos pesquisadores pelo agente.

Respostas brutas resumidas dos catálogos ficam localmente em `reports/catalog-search.json` e `reports/catalog-search-exact.json`, ignoradas pelo Git. A busca não substitui a validação de arquivos efetivamente baixados.

## Próxima decisão

Usar Singapura como prioridade de preparação por oferecer atributos de catálogo e contexto reais; manter Estocolmo como fonte derivada separada, sem juntar IDs entre cidades. Aguardar o acesso original para recuperar teste e pacotes faltantes, conferindo hashes e diferenças antes de substituir a fonte atual. Não preencher lacunas com dados inventados nem declarar que todas as três cidades já estão disponíveis.
