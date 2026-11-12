# Registro de decisões

## 2026-11-06 — Escolha e fundação

- Hipótese: recomendação com busca conversacional permite evidenciar ML, LLMs e produto de forma integrada.
- Decisão: foco em uma cidade e em uma tarefa principal, descobrir o que pedir, combinando recomendação e busca conversacional.
- Melhoria: explicitar avaliação, ferramentas de IA usadas e direção visual; adiar previsão de demanda.
- Implementação inicial: estrutura do repositório, auditor CSV sem dependências de execução, testes e configuração de CI.
- Resultado de dados/modelos: nenhum experimento DHRD realizado.
- Limitação: acesso aos arquivos ainda pendente; prazos de desenvolvimento são estimativas.
- Próxima decisão: obter os arquivos oficiais e escolher cidade e cortes a partir da auditoria.

Template dos próximos registros: hipótese → alteração → comparação → resultado observado → limitação → próxima decisão.

## 2026-11-06 — Importação relacional e referências de recomendação

- Hipótese: um contrato explícito e um benchmark simples permitem iniciar a engenharia enquanto a aquisição dos arquivos é resolvida.
- Implementação: CSVs configuráveis → SQLite transacional → treino congelado por dia relativo → primeira cesta futura por cliente. Itens identificados pelo par vendedor/produto, com referências de popularidade, repetição e cosseno colaborativo.
- Comparação: testes incluem resultado calculado à mão, cliente novo, alvo fora do catálogo, dados órfãos e duplicatas conflitantes. Adicionar eventos após o período de avaliação não alterou Recall/NDCG da validação no teste de regressão.
- Resultado observado: 19 testes automatizados passaram localmente e a demonstração sintética executou de ponta a ponta. Nenhuma conclusão sobre qualidade ou escala em dados reais.
- Limitação: link oficial sem autenticação redireciona para login. Formato real e protocolo dos splits distribuídos permanecem desconhecidos. O benchmark inicial não aplica restrição geográfica nem disponibilidade.
- Decisão: não escolher cidade, inventar métricas ou trocar a base. SQLite usa biblioteca padrão e garante integridade nesta etapa; DuckDB/Parquet serão reconsiderados a partir dos arquivos e medições.
- Próxima ação: obter distribuição oficial acessível e validar o adaptador. Funções de catálogo e API poderão avançar em paralelo com os contratos conhecidos.

## 2026-11-06 — Aquisição real e remoção de demonstração sintética

- Diretriz: usar sempre dados reais no produto e procurar cópias públicas ou API em vez de esperar apenas pelo acesso ao pacote original.
- Pesquisa: API GitHub, fork oficial, repositórios de análises, projetos dos autores e links públicos de distribuição. O pacote original e o link direto de Singapura exigiram login. Não foi encontrada API pública do DHRD.
- Resultado: arquivo público real dos autores do HyperHawkes baixado, conferido por tamanho e hash Git fixados, com SHA-256 registrado. Auditoria completa em `DATA_ACCESS.md`.
- Correção: removido o comando `demo`; gerador de exemplos transferido para `tests/`. Preparação e benchmark recusam fontes sintéticas por padrão; habilitação interna existe somente para testes e não está exposta na CLI.
- Limite: a cópia derivada não contém todos os atributos do pacote original. Nenhum dado ausente foi inventado, e não foi treinado um modelo real nesta etapa.
- Próxima decisão: definir contrato de sessões e tempo, adaptar os campos reais e avaliar referências nesse recorte. Continuar o pedido de acesso ao original para possível enriquecimento.

## 2026-11-06 — Cópia pública de Singapura com catálogo e contexto

- Objetivo: ampliar a busca por todos os dados, incluindo bancos/catálogos públicos e espelhos de pesquisa.
- Achado: NearBite publica três links de CSVs de Singapura acessíveis sem login. Baixados 419.360.922 bytes com downloader próprio, validação de tamanho/cabeçalho e manifesto SHA-256. A origem é declarada pelo espelho e as contagens conferem com sua documentação; equivalência byte a byte ao original permanece não verificada.
- Auditoria real: 3.431.870 linhas de itens, 1.709.414 pedidos, 476.150 clientes, 1.066.840 produtos, 7.411 vendedores e 78 culinárias. Dias 0–75. Quarenta e uma linhas sem produto no catálogo; zero conflitos de cliente/dia/horário por pedido.
- Comparação de fontes: esta cópia tem preço normalizado, culinária e geohash ausentes no derivado de Estocolmo. Priorizar Singapura para o produto, mantendo as fontes separadas e seus limites explícitos.
- Limite: não foram obtidos os três ZIPs originais nem o teste separado. O carregador OmniRec revelou links e hashes de referência; os downloads continuaram exigindo acesso. Busca em catálogos públicos não encontrou o pacote integral.
- Próxima ação: implementar adaptação do formato real e tratamento registrado das 41 linhas, depois reservar avaliação temporal própria. Nesta data, a aquisição completa ainda não estava concluída.

## 2026-11-06 — Preparação e primeira validação real

- Protocolo registrado antes de medir: treino 0–61, validação 62–68, teste 69–75 reservado. Mesma primeira cesta futura e catálogo de treino para os três modelos; nenhum limite de usuários.
- Preparação: fontes reais verificadas por hashes fixados, índice e dias textuais tratados, contexto preservado. Quarentena de 35 pedidos inteiros (77 linhas) por 41 linhas sem produto; 84.974 repetições item/pedido consolidadas. Restaram 1.709.379 pedidos e 3.346.819 presenças binárias de item.
- Implementação: candidato `basket_cosine` com co-compra por pedido e top-100 vizinhos, distinto do `item_cosine` legado por compradores em comum. Parâmetros definidos antes da primeira validação. Uso de chaves canônicas e treinamento compartilhado permitiu executar o recorte completo localmente.
- Resultado: 109.842 clientes na validação. Recall@10: popularidade 0,2504%, repetição 16,0427%, cosseno por cesta 6,7272%. O candidato mais elaborado perdeu para repetição nesta execução; manter repetição como referência forte.
- Erro prioritário: 21.480 clientes sem histórico recebem popularidade global; 6.278 itens-alvo não estavam no treino. Investigar recuperação por conteúdo e preferências explícitas, sem afirmar ganho antes de avaliar.
- Limites: validação histórica própria, espelho de terceiros, sem restrição geográfica ou teste final. Não demonstra conversão, satisfação ou ganho financeiro.
- Evidências: `EXPERIMENT_001.md`, configuração congelada e relatórios agregados em `evaluations/results/`. Dados e IDs de quarentena ficam locais.

## 2026-11-07 — Distribuição oficial recebida, comparada e escolhida

- Entrada: o usuário baixou os três ZIPs e o README original para o workspace.
- Verificação: SHA-256 dos três pacotes coincide com a referência OmniRec; todos os membros passaram em CRC/tamanho; quinze arquivos extraídos com nomes permitidos e proteção de fontes existentes.
- Auditoria: 4.400.000 pedidos nas três cidades, catálogos e vendedores completos, sem sobreposição de pedidos entre treino/teste. Fingerprints de linhas com multiplicidade confirmam que o arquivo completo contém a união dos splits.
- Comparação SG: campos originais de treino, produtos e vendedores coincidem linha a linha com o espelho. Produtos também têm SHA-256 byte a byte idêntico. A divergência de colunas decorre do índice e de latitude/longitude adicionais, que não entraram no primeiro recomendador.
- Observação: o teste SG inclui dias 76–90, enquanto SE/TW incluem 76–89. No catálogo SG há 41 referências ausentes no treino e oito no teste. Não cortar o dia 90 nem esconder casos ausentes.
- Decisão: fonte principal passa a ser a distribuição oficial; usar SG primeiro, SE como base secundária e TW depois. Manter treino/teste separados e não anexar o arquivo completo como observações extras. Fontes antigas e Experimento 001 permanecem para reprodução, sem relabeling retroativo.
- Próxima ação: migrar explicitamente o adaptador para os originais e definir protocolo com teste oficial separado antes do próximo experimento. A auditoria não executou previsão ou ajuste de modelo sobre os testes oficiais.
