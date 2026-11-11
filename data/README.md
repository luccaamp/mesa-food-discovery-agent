# Dados

**Fonte principal atual:** ZIPs oficiais de Singapura, Estocolmo e Taipei fornecidos pelo usuário, verificados por SHA-256 e CRC e extraídos em `data/raw/dhrd-official-v1/`. [Quais arquivos usar](../docs/OFFICIAL_DATA_MIGRATION.md). Os conjuntos de teste oficiais permanecem separados para avaliação final, sem métricas de modelo calculadas nesta auditoria. O histórico de aquisição abaixo não representa mais uma pendência de acesso.

Fonte original: [Delivery Hero Recommendation Dataset](https://github.com/deliveryhero/dh-reco-dataset). O README declara MIT e aponta para uma pasta que exige autorização. Já obtivemos a cópia derivada dos autores do HyperHawkes (Estocolmo) e as três tabelas do espelho público NearBite (Singapura), com pedidos, catálogo e vendedores. Ver [procedência, hashes e auditoria](../docs/DATA_ACCESS.md). Arquivos em `data/raw/hyperhawkes-dhrd/` e `data/raw/nearbite-sg/`, fora do Git. O pacote original completo ainda não foi obtido.

O artigo descreve pedidos, produtos e vendedores de três cidades. Há preços normalizados, nomes multilíngues, IDs anonimizados e geografia aproximada. Não há garantia de fotos, ingredientes, alérgenos, estoque atual ou tempo de entrega.

Diretórios locais futuros: `raw/`, `interim/`, `processed/`. Todos ignorados pelo Git. Não publicar dados corporativos, currículo ou transcrições privadas.

Ao obter a base: registrar data, URL, versão, hashes, licença, esquema real, contagens por cidade e split. Conferir duplicatas, unidades, relações de tabelas, cobertura temporal, IDs órfãos e cardinalidade. O comando `prepare` já valida um contrato relacional explícito em CSV e cria SQLite; esse contrato ainda não foi testado com os arquivos DHRD. Ver [pipeline](../docs/DATA_PIPELINE.md) e [acesso](../docs/DATA_ACCESS.md).
