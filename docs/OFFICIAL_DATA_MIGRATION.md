# Fonte principal após receber os ZIPs oficiais

Verificação concluída em 7/11/2026.

Atualização de implementação: a migração já foi executada pelo novo comando `prepare-official-singapore`, com banco independente, teste oficial separado e protocolo v2 registrado antes da validação. A busca lexical também foi executada no catálogo completo. [Experimento 002, resultados e comandos](EXPERIMENT_002.md). As propostas de migração abaixo registram o contexto original da decisão.

Foram obtidos `data_sg.zip`, `data_se.zip`, `data_tw.zip` e [o README da distribuição](data/DHRD_README.md). Os três arquivos correspondem aos SHA-256 publicados pelo carregador OmniRec, e todos os membros extraídos tiveram CRC e tamanho verificados.

## Resultado da auditoria integral

| Cidade | Pedidos no treino | Pedidos no teste | Produtos | Estabelecimentos | Culinárias |
| --- | ---: | ---: | ---: | ---: | ---: |
| Singapura | 1.709.414 | 290.586 | 1.066.840 | 7.411 | 78 |
| Estocolmo | 325.937 | 74.063 | 111.046 | 1.148 | 40 |
| Taipei / TW | 1.643.492 | 356.508 | 810.536 | 9.506 | 13 |

No total, 4.400.000 pedidos e 9.361.089 linhas de itens nas três cidades. São 1.988.422 linhas de catálogo. Contagens de clientes e IDs são mantidas por cidade: o mesmo ID em cidades diferentes não indica a mesma pessoa.

Em todas as cidades, treino cobre dias relativos 0–75, e não houve sobreposição de IDs de pedido entre treino e teste. As contagens e fingerprints com multiplicidade confirmaram que a união dos dois splits corresponde ao arquivo de pedidos completo. Isso não significa que as linhas do arquivo completo tenham necessariamente a mesma ordenação da concatenação.

**Singapura tem teste nos dias 76–90 (15 valores de dia); Estocolmo e Taipei, 76–89.** Não truncar Singapura com um limite de 89 assumido a partir das outras cidades ou do resumo de três meses. A escolha dos arquivos oficiais de teste deve prevalecer sobre um corte inferido.

Não foram encontradas referências a vendedores ausentes. Singapura tem 41 linhas de treino e oito de teste com produto ausente no catálogo. Estocolmo e Taipei não apresentaram esse problema nas verificações realizadas. As 41 linhas de treino são uma característica do pacote oficial, não uma alteração introduzida pelo espelho.

O teste foi lido exclusivamente para verificação estrutural e de integridade: nenhuma previsão, métrica de recomendação ou ajuste de modelo foi executado sobre ele. [Relatório agregado completo](../evaluations/results/official-data-audit-v1.json) e [manifesto dos arquivos](../evaluations/results/official-archives-manifest-v1.json).

As verificações automatizadas do projeto passaram em 38 testes nesta etapa, incluindo proteção contra caminhos inesperados, arquivos parciais preexistentes, divergências de conteúdo e sobreposição entre splits.

## Decisão de fonte

Adotar os arquivos oficiais como fonte principal de todas as novas etapas. A configuração [official-source-selection-v1.json](../configs/official-source-selection-v1.json) registra os quinze arquivos, caminhos locais, hashes e papéis. É um registro de fontes, não uma configuração de treino já executada.

**Singapura será a cidade principal.** Mantém continuidade com o primeiro experimento e oferece catálogo amplo, preço normalizado, culinária, rede e geohash oficiais. Estocolmo é uma cidade secundária útil para verificações menores e robustez. Taipei fica disponível para uma extensão entre cidades. IDs devem incluir a cidade no namespace; não juntar entidades de cidades diferentes por igualdade de identificador.

## Quais arquivos usar

| Arquivo por cidade | Uso |
| --- | --- |
| `orders_<cidade>_train.txt` | Construção de perfis, treinamento e validação temporal interna |
| `products_<cidade>.txt` | Nomes, produto, vendedor e preço normalizado do catálogo |
| `vendors_<cidade>.txt` | Culinária, rede e geohash do estabelecimento |
| `orders_<cidade>_test.txt` | Avaliação final oficial, sem treino ou ajuste de prompts/hiperparâmetros usando seus resultados |
| `orders_<cidade>.txt` | Auditoria da distribuição completa; não adicionar como outro conjunto de treino, pois já inclui treino e teste |

Apesar da extensão `.txt`, os arquivos são CSVs UTF-8. A primeira coluna é um índice de exportação e deve ser ignorada explicitamente. Os originais não incluem as colunas de latitude/longitude adicionadas pelo espelho. Preservar o geohash como aproximação e não apresentá-lo como coordenada exata ou confirmação de raio de entrega.

## Preservar as evidências anteriores

O Experimento 001 foi executado com a cópia NearBite. Seus resultados, hashes e rótulo de procedência permanecem inalterados. Comparar os campos originais efetivamente usados pelo modelo permite conferir sua correspondência, mas não transforma retroativamente aquela execução em uma execução sobre o ZIP oficial.

A comparação integral confirmou igualdade linha a linha em todos os campos originais dos pedidos de treino, produtos e vendedores de Singapura, ignorando índice de exportação e latitude/longitude extras do espelho. O arquivo de produtos é também idêntico byte por byte. Portanto, não apareceu uma divergência nos valores de entrada do Experimento 001. Suas métricas não foram recalculadas nesta etapa nem transformadas em métricas do teste oficial.

Para Estocolmo, o original contém 756.738 linhas de itens, contra 740.707 no HyperHawkes. O derivado permanece uma transformação histórica, não a fonte integral; não se declarou equivalência entre eles.

O próximo adaptador de treino deve ler a fonte oficial diretamente e gerar uma nova versão de dados/manifesto. O adaptador atual `prepare-singapore` continua fixado nos hashes do espelho para reproduzir o Experimento 001; não foi silenciosamente redirecionado. O derivado HyperHawkes e os CSVs NearBite tornam-se referências históricas e fontes de reprodução, sem necessidade de apagar arquivos.

## Plano de avaliação com o pacote oficial

Usar exclusivamente o arquivo oficial de treino durante desenvolvimento. Criar a validação interna por tempo dentro dele e registrar o novo protocolo antes de medir. O teste oficial permanece separado do banco de treino, acessado apenas para auditoria estrutural nesta etapa.

O protocolo v1 anterior (treino 0–61, validação 62–68, reserva interna 69–75) continua associado ao Experimento 001. A disponibilidade de um teste oficial posterior permite propor uma validação interna maior em uma versão v2, mas isso precisa ser registrado antes da execução, com distinção clara entre validação interna e teste oficial.

Nos rótulos de avaliação final, itens sem cadastro ou sem histórico precisam ter cobertura e exclusões registradas; não remover exemplos difíceis apenas para melhorar a métrica. Não anexar o arquivo completo de pedidos ao treino nem filtrar o teste a partir dos acertos do modelo.

## Reproduzir a verificação

```sh
python scripts/verify_official_archives.py --archive-dir .
python scripts/audit_official_data.py
```

Extração em `data/raw/dhrd-official-v1/`, fora do Git. O extrator aceita somente os quinze nomes esperados, verifica hashes dos ZIPs e CRC dos membros e não substitui fontes existentes diferentes. O auditor compara os campos em comum de Singapura com o espelho, examina períodos, sobreposição de pedidos, cobertura de catálogo e fingerprints da união dos splits. O relatório agregado pode ser publicado sem registros individuais.
