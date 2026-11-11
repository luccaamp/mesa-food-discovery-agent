# Protocolo de avaliação

Estado atual: recomendação sobre dados oficiais validada em 175.358 clientes,
treino até 61, validação 62–75 e teste oficial 76–90 reservado. Busca e assistentes
Qwen/Gemini têm evidências de execução, separadas de qualidade geral. O
[Experimento 001](../docs/EXPERIMENT_001.md) preserva o protocolo histórico do
espelho, com outros cortes e população; não comparar suas métricas diretamente.

**Decisão de 10/11/2026:** avaliação sem participantes humanos. Usar
[protocolo automatizado e base científica](../docs/AUTOMATED_EVALUATION.md),
[manifesto](../configs/automated-evaluation-v1.json) e Inspect AI isolado. A
primeira [calibração executada](results/judge-calibration-v1.json) reprovou o
Qwen 1,5B como juiz principal na configuração testada. Não há julgamento humano
inventado nem declaração de satisfação de usuários reais.

## Recomendação e recuperação

Auditar os splits fornecidos antes de utilizá-los. Reservar teste sem ajuste de hiperparâmetros; validação deriva apenas do treino, respeitando tempo. Itens do mesmo pedido não podem atravessar partições. Garantir que perfis, popularidade e embeddings treináveis não consumam interações futuras; documentar que um catálogo final pode conter itens ainda inexistentes no corte histórico.

Definir unidade, catálogo candidato, exclusões, disponibilidade aproximada por região e política de repetição. Compras repetidas são relevantes em refeições: comparar política que permite repetição com análise específica de novidade. Ausência de compra não comprova rejeição; negativos amostrados e catálogo completo geram métricas diferentes.

Referências: popularidade global/local e repetição do histórico. Candidatos: filtragem colaborativa implícita, busca lexical, embeddings e combinação de sinais. Escolher algoritmo e biblioteca após auditoria, escala e benchmark inicial.

Medir Recall@10, NDCG@10, cobertura do catálogo, diversidade e latência p50/p95, com protocolo e tamanho das amostras. Separar perfis novos e pouco ativos, itens novos e regiões. Para busca, criar consultas com julgamentos automáticos de relevância, incluindo consultas em português sobre catálogo multilíngue, e verificar os avaliadores antes de aceitar notas. Identificar esses rótulos como estimativas de IA. Informar variabilidade por usuário/período; não comparar números de protocolos distintos.

## LLM e fluxo completo

Alvo inicial: 60 casos julgados, 40 de desenvolvimento e 20 de teste congelado. O arquivo de exemplos é somente desenvolvimento, não um conjunto reservado. Cobrir busca direta, preferências múltiplas, continuação, ausência de resultados, ambiguidade, limites de preço, conteúdo malicioso no catálogo e atributos desconhecidos.

Medir: ferramenta correta, argumentos válidos, IDs existentes, cumprimento dos filtros, números e evidências corretos, esclarecimentos e afirmações sem suporte. Usar verificadores de fonte e calibrar juízes LLM em controles independentes. Comparar prompt simples, fluxo com ferramentas e variantes; manter o teste fora de ajustes. Revisão humana não é exigida pelo protocolo atual.

Registrar provedor/modelo/versão, parâmetros, número de chamadas, falhas, tempo e custo baseado em uso/preço verificados na data do experimento. Comparar mesma tarefa via interface convencional. Não confundir sucesso da chamada HTTP com sucesso da tarefa.

## Automação e simulação

Para consolidação de relatórios, registrar quantidade de execuções e correções; não medir economia de trabalho humano sem uma referência observada. Nas simulações, medir conclusão verificável, turnos, tempo e erros do simulador separados dos erros do produto. Não inferir satisfação humana ou conversão comercial a partir de personas de IA.
