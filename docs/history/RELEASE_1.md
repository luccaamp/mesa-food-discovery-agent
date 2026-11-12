# Mesa: critérios, decisões e reprodução

Entrega de 10/11/2026. Horários dos registros técnicos estão em UTC;
o ensaio público final ocorreu às 11h46–11h47 de Brasília.

## Critérios da entrega

| Fase | Resultado | Evidência |
| --- | --- | --- |
| Dados e procedência | Catálogo oficial, hashes, quarentena e separação temporal | OFFICIAL_DATA_MIGRATION.md |
| Recomendação | Três referências avaliadas em 175.358 clientes | EXPERIMENT_002.md |
| Busca | Lexical com glossário mantida; E5 não promovido | retrieval-additional-v2.json |
| Assistente público | 10/10 contratos; 3 inferências Gemini; 36 itens conferidos | public-assistant-acceptance-v3.json |
| Contingência | 40/40 cenários e 12/12 adicionais; 73 turnos | usage-timeout-resilience-v3.json e usage-additional-v3.json |
| Confiabilidade | Retry limitado, cota por tentativa e pausa após falhas repetidas | test_cloud.py e test_provider_cooldown.py |
| Julgamento de relevância | Dois ensaios concluídos, ambos reprovados; notas retidas | relevance-judge-cli-v1.json e relevance-judge-single-pair-v1.json |
| Interface | Busca, seleção, evidências, recomendações e teclado conferidos | release-browser-v1.json |
| Publicação | Render e CI verificados; relatório do ensaio identifica commit | PROJECT_STATUS.md |
| Execução | Guia de execução local e na nuvem | PRODUCT_GUIDE.md e CLOUD_DEPLOYMENT.md |

Os arquivos JSON estão em `evaluations/results/`, os testes em `tests/`
e os documentos em `docs/`.

## O que a aceitação demonstra

Execução pública:
busca PT, refinamento de preço, troca de prato mantendo o filtro, busca EN,
restrição alimentar, moeda indevida, injeção, saudação e recomendações com e sem
referência. Três chamadas Gemini concluídas na primeira tentativa, 999 tokens.
Não atribuímos essa recuperação ao retry ou à pausa: nenhum foi necessário
nessa rodada. Falhas anteriores permanecem preservadas.

A proteção contra novas esperas durante uma indisponibilidade foi testada com
relógio e transporte controlados. A cota não é reiniciada pela proteção.
O estado de pausa é local ao processo, assim como o limite defensivo da
demonstração; a cota do provedor é a autoridade final. O orçamento urllib
não é uma garantia rígida de tempo total de DNS, conexão e leitura.

## Conclusão da comparação de relevância

Proxy por nomes em 10.000 produtos, 16 consultas (oito pares PT/EN):

| Método | P@10 | NDCG@10 |
| --- | ---: | ---: |
| Lexical | 0,3000 | 0,4721 |
| Lexical com glossário | 0,6000 | 0,9443 |
| E5 semântico | 0,2875 | 0,4060 |
| Híbrido | 0,3688 | 0,5770 |

São regras automáticas sobre nomes, favorecidas pela sobreposição entre o
vocabulário das consultas e o glossário. Não são rótulos humanos, medição de
ingredientes ou um benchmark externo. A amostra não justifica promover o E5
nem expandir o índice. A busca atual permanece a referência entregue.

O Qwen3-8B acertou 33/48 controles no lote de seis e 28/40 em novos controles
avaliados um por vez, com a mesma rubrica. A mudança foi declarada antes da
segunda execução. Os controles sintéticos foram congelados antes do ensaio,
não ajustados após seus erros. Pesos, runtime, avaliador e resultados possuem
hashes. O snapshot do segundo avaliador preserva os bytes executados.

**Julgamento semântico calibrado continua pendente.** O encerramento destes
experimentos é uma decisão negativa de engenharia, não uma nota de aprovação.
Um novo juiz exigirá controles novos e admissão antes de pontuar o catálogo.

A [rodada posterior](../RELEVANCE_REASONING_2026-11-10.md) corrigiu geração sem
resposta final e abstenções, mas a última configuração ainda mudou uma nota
ao inverter os casos. Foi interrompida em 15/16 acertos, com 32 exigidos.
Nenhuma nota do catálogo foi produzida. As falhas de cada configuração e seus
arquivos executados estão preservados.

## Reprodução

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s tests_eval -v
cd apps/web
npm ci
npm test
npm run build
```

Com os artefatos oficiais preparados e o pacote instalado:

```powershell
python scripts/check_usage_resilience.py --output reports/usage-fresh.json
python scripts/check_usage_resilience.py --suite configs/usage-additional-v1.json --output reports/additional-fresh.json
python evaluations/relevance_judge_cli.py --batch-size 1 --controls configs/relevance-judge-controls-v2.json --output reports/judge-fresh.json
```

O último comando usa Qwen local e pode demorar; a reprovação da calibração
impede gerar notas para o catálogo. Não sobrescrever evidências anteriores.
A aceitação pública é deliberada e limitada por cota; não executá-la
automaticamente em todo commit nem repetir até obter uma aprovação.
