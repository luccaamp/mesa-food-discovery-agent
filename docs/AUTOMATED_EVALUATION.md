# Avaliação automatizada: decisão metodológica e pesquisa

Pesquisa e primeira prova executável em **10 de novembro de 2026**. Não há um
protocolo único universalmente canônico em 2026. A decisão para o Mesa combina
práticas estabelecidas e resultados recentes, com ferramentas executadas no
ambiente do projeto. Esta página distingue pesquisa, implementação e resultados.

## Decisão para o Mesa

Usar **Inspect AI** como organizador de tarefas, inferência, scorers e logs; usar
verificadores próprios para os contratos do catálogo e da conversa. Simuladores
terão objetivos, ações permitidas, limite de turnos e condições verificáveis de
parada. Juízes de IA serão uma camada adicional, condicionada a calibração.

Não há participantes humanos novos neste protocolo. Isso remove a revisão humana
como condição de conclusão técnica; não transforma preferências simuladas em
satisfação de pessoas reais. As mensagens simuladas e as respostas corrompidas
de controle são identificadas. Os produtos e seus atributos continuam oficiais.

O [manifesto do protocolo](../configs/automated-evaluation-v1.json) registra oito
perfis comportamentais, metas de 40 casos de desenvolvimento e 20 reservados,
repetições, orçamento e condições de relato. A bateria objetiva agora tem 40
cenários de desenvolvimento executados; a calibração de juiz continua separada.

## Conversas executadas em 10/11

O [runner HTTP](../evaluations/conversation_suite.py) executa oito perfis
**roteirizados**, com objetivos e até quatro turnos definidos em JSON. O roteiro
é a simulação de comportamento: os usuários não foram gerados livremente por um LLM.
Cada episódio começa com contexto novo e só recebe o contexto retornado pela API.
SQLite é consultado diretamente para conferir identidade, nome, preço e culinária,
além de filtros, exclusão de sementes, evidência do recomendador e ação escolhida.

- Antes das correções: **38/40** episódios aprovados. “bom dia” virou `breakfast`;
  um novo prato junto com preço preservou indevidamente a consulta anterior.
- Depois das correções, mesmos casos, três repetições: **120/120** episódios,
  **177 turnos**, **702 ocorrências de itens conferidas**, **90 chamadas Qwen**,
  nenhum fallback de modelo. Relatórios completos
  [antes](../evaluations/results/conversation-development-v1.json) e
  [depois](../evaluations/results/conversation-development-v2.json).
- `pass^3 = 1` neste conjunto. São repetições com temperatura zero e seed fixada,
  não 120 pessoas, nem estimativa de robustez sob qualquer conversa.
- Falhas factuais não podem ser compensadas por uma nota qualitativa. Esta
  camada não usa um juiz LLM; a qualidade interpretativa continua sem nota.
- Os testes do próprio verificador introduzem mutações de preço, nome, culinária,
  sementes, filtros, ferramentas e contexto para conferir que esses erros falham.

O runner recusa endpoints externos e exige modelo local saudável e catálogo
oficial com a mesma procedência. Não chama o Gemini nem consome o teste de pedidos.
Salva progresso parcial se uma execução for interrompida e não sobrescreve um
relatório anterior. O resumo público é derivado por
`evaluations/summarize_conversations.py` e conferido em teste contra os registros.

```powershell
.venv/Scripts/python evaluations/conversation_suite.py --repetitions 3 --output reports/conversation-new.json
```

Os 20 contratos reservados estão em `configs/conversation-reserved-v1.json`,
congelados no commit `86965e7` antes da primeira inferência. Foram elaborados
depois do desenvolvimento, pelo mesmo processo de autoria por IA; não são um
benchmark externo independente. Eventuais falhas devem permanecer no relatório.
Não ajustar o produto com esses casos e chamar a nova execução de teste intocado.

Os contratos reservados passaram em **60/60 episódios**, com três repetições dos
20 cenários, sem ajuste entre as execuções. [Registro completo](../evaluations/results/conversation-reserved-v1.json).
Isso amplia os contratos objetivos cobertos, mas não é o teste oficial de pedidos
DHRD nem uma amostra representativa de usuários. Os casos novos incluem preços
normalizados de 0,002/0,004 e limite zero, além de novos pratos e trocas de intenção.

## Segundo candidato a juiz

O Qwen3-8B Q4_K_M oficial foi baixado com revisão e SHA-256 fixados, licença
Apache-2.0, 5.027.783.488 bytes, somente para pesquisa local.
[Configuração](../configs/judge-candidate-qwen3-v1.json) e
[fonte oficial dos pesos](https://huggingface.co/Qwen/Qwen3-8B-GGUF).
Não substitui o modelo do produto. Usa o mesmo runtime CPU, seis threads,
contexto 4096 e raciocínio explícito desligado; a avaliação mantém temperatura zero.

Nos controles em inglês, o novo candidato acertou **16/16**, com **8/8** pares
consistentes e 5.258 tokens locais. [Registro](../evaluations/results/judge-calibration-qwen3-v1.json).
Passou no critério necessário para piloto consultivo, não em uma prova universal
de qualidade ou independência. A verificação em português é uma execução separada.

Em português, com veredito primeiro, acertou **15/16** e manteve **7/8** pares
consistentes. Na falha de alergênico, a explicação identificou corretamente a
alternativa sustentada, mas o campo `winner` apontou a oposta. **Não admitido
no piloto multilíngue nessa configuração.** [Registro da falha](../evaluations/results/judge-calibration-qwen3-pt-v1.json).
Esse primeiro registro PT tem uma limitação adicional de procedência do código,
explicitada no próprio JSON; o log de inferência e os resultados foram preservados.
As execuções seguintes capturam o hash do avaliador antes de iniciar a inferência.

Uma configuração distinta em desenvolvimento testa `evidence_field` e explicação
breve antes do veredito. Os mesmos controles e seus gabaritos permanecem intactos;
isso não transforma uma nova configuração em resultado reservado independente.

### Correção de integração encontrada durante os experimentos

O runtime fixado `llama.cpp b12182` lê `response_format.json_schema.schema`.
O formato anterior enviava `schema` diretamente sob `response_format`: o runtime
aceitava HTTP 200, mas tratava a saída como objeto JSON genérico. Isso foi
confirmado no [código da versão executada](https://github.com/ggml-org/llama.cpp/blob/b12182/tools/server/server-common.cpp#L1291).
Os resultados antigos são inferências reais com validação posterior, mas **não
demonstram decodificação restrita pelo schema**. Foram preservados como resultados
anteriores à correção; não são atribuídos à integração corrigida.

A API local e o adaptador de avaliação agora enviam o wrapper reconhecido.
Um teste real pediu uma saída incompatível e recebeu exatamente o único valor
permitido pelo schema: [prova](../evaluations/results/local-schema-probe-v1.json).
Isso verifica esse contrato, não todas as opções de JSON Schema.
A bateria dos mesmos 40 cenários foi repetida após a correção e permaneceu em
**120/120**, sem fallback: [registro v3](../evaluations/results/conversation-development-v3.json).
O teste reservado anterior continua como evidência daquela implementação; não
foi reutilizado para afirmar uma nova avaliação intocada da versão corrigida.

Com schema efetivo e evidência antes do veredito, o juiz Qwen3 passou em
**16/16 controles PT**, **8/8 pares consistentes**, 5.872 tokens. A calibração EN
equivalente é uma execução separada, necessária antes do piloto.
[Registro PT](../evaluations/results/judge-calibration-qwen3-pt-schema-v1.json).
Uma tentativa com raciocínio ligado excedeu o tempo HTTP e foi encerrada;
não conta como calibração completa ou aprovada.

### Usuários gerados por outro modelo

O [simulador Inspect](../evaluations/inspect_user_simulation.py) usa Qwen3-8B
para gerar mensagens de oito perfis. O planejador testado é o Qwen2.5-1.5B.
Os objetivos e ações são fixados antes da geração; o verificador rejeita troca
de prato, adição de ingrediente, orçamento alterado, quantidade errada de turnos
ou restrição perdida. Só mensagens aceitas chegam à API do Mesa. Não há substituição
silenciosa por uma mensagem roteirizada quando o simulador falha.

Na primeira integração, **1/8** saídas do simulador foi aceita. Depois da correção
do wrapper, **8/8** foram aceitas e passaram no produto, com cinco chamadas ao
planejador local: [simulação v1](../evaluations/results/user-simulation-v1.json),
[simulação v2](../evaluations/results/user-simulation-v2.json) e
[execução no Mesa](../evaluations/results/generated-conversations-v1.json).
As mensagens v2 ficaram muito próximas das originais. São inferências reais, mas
não devem ser contadas como oito novas variações independentes. O teste seguinte
usa temperatura 0,7, mantém regras de objetivo e rejeita cópia exata de pedidos
de prato. A quantidade de mensagens alteradas é registrada explicitamente.

Na conferência pública da troca de prato com preço, o Gemini excedeu o tempo e o
glossário incluiu indevidamente as palavras do limite no texto da busca. A falha
foi preservada em [regressão pública v1](../evaluations/results/gemini-context-regression-v1.json).
O limite agora é extraído para o contexto e removido dos termos enviados ao modelo
ou glossário. A simulação de indisponibilidade do provedor é coberta em teste;
essa primeira requisição não conta como sucesso real do Gemini.
Além do teste unitário, uma integração FastAPI com **catálogo oficial completo**
e falha de rede injetada retornou seis produtos reais de chá com leite, preservou
o limite e conferiu os campos diretamente em SQLite.
[Evidência da contingência](../evaluations/results/provider-failure-real-catalog-v1.json).
Depois da publicação do commit `f8710a3`, o mesmo caso passou no site: seis itens
reais conferidos contra o SQLite oficial local, novo prato e limite preservados,
sem palavras do preço na consulta. O Gemini não completou a tentativa; o resultado
foi explicitamente `glossary_fallback`, não uma inferência bem-sucedida do provedor.
[Conferência pública após a correção](../evaluations/results/public-context-regression-v2.json).

### Resultados consolidados dos papéis de IA

- **Calibração factual EN/PT:** 32/32 controles e 16/16 pares consistentes com
  schema efetivo e evidência antes do veredito. O teste EN usou 5.660 tokens;
  o PT, 5.872. [EN](../evaluations/results/judge-calibration-qwen3-en-schema-v1.json).
- **Simulador por objetivos estruturados:** 6/8 episódios aceitos por regras,
  nove mensagens aceitas, cinco com texto diferente do roteiro. Os seis episódios
  passaram no Mesa, com três chamadas Qwen2.5. Duas gerações foram rejeitadas
  pelo contrato lexical conservador; uma usou SQL bruto e outra uma paráfrase
  fora do vocabulário permitido. Isso não prova perda semântica de objetivo:
  o verificador também pode rejeitar uma formulação legítima.
  [Geração v4](../evaluations/results/user-simulation-v4.json) e
  [execução v3](../evaluations/results/generated-conversations-v3.json).
- **Piloto consultivo:** 20 respostas de juiz no formato esperado, 15.468 tokens,
  aproximadamente 8min40s nesta máquina. Houve erros de julgamento: a recusa de
  executar SQL foi penalizada, e faltou contexto inicial ao avaliar limite zero.
  [Registro](../evaluations/results/conversation-advisory-v1.json).
- **Correção do harness:** incluir contexto inicial e o contrato permitido;
  repetir somente os três casos problemáticos, 1.938 tokens. O juiz continuou
  penalizando a recusa correta, mesmo reconhecendo a restrição no texto.
  [Revisão dirigida](../evaluations/results/conversation-advisory-context-v2.json).

**Decisão:** não publicar uma nota agregada de qualidade nem aprovar o produto
por essas opiniões. A calibração factual foi necessária e não foi suficiente
para validar a rubrica qualitativa. A API e a interface mostram cobertura e
contagens, com essa limitação explícita; não apresentam a média interna do Inspect
como porcentagem de qualidade. Os verificadores objetivos continuam independentes.
O protocolo sem humanos está executável, com resultados positivos e negativos
preservados. Qualquer futura nota de qualidade exige controles próprios da rubrica
e nova configuração ou outro avaliador; não ajustar a resposta para agradar ao juiz.

Reproduzir os papéis locais (cada comando encerra o servidor de juiz ao terminar):

```powershell
.venv/Scripts/python scripts/fetch_judge_candidate.py
.venv/Scripts/python scripts/run_judge_candidate.py --language pt --evidence-first --output reports/judge-pt-new.json
.venv/Scripts/python scripts/run_judge_candidate.py --task simulation --output reports/simulation-new.json
.venv/Scripts/python evaluations/conversation_suite.py --suite reports/simulation-new-suite.json --output reports/generated-new.json
.venv/Scripts/python scripts/run_judge_candidate.py --task review --output reports/advisory-new.json
```

O runner de produto exige a API/Qwen local iniciados separadamente. Os logs brutos
Inspect ficam ignorados em `reports/`; os relatórios sanitizados, schemas, revisão
dos pesos e hashes estão versionados. A imagem do Render só inclui os resumos
pequenos; não carrega Inspect, Qwen3, logs ou dados de pedidos.

O piloto de rubrica em `evaluations/inspect_conversation_review.py` examina
atendimento ao pedido, clareza e aderência à evidência, em escala 0–3. Exige
calibrações EN/PT aprovadas. Oculta nome do planejador, métricas e resultado do
verificador. Saída inválida permanece sem nota, com cobertura explícita.
Não usa médias de opinião como aceite do produto. Calibração factual em pares
não valida a precisão de notas absolutas; Qwen3 e Qwen2.5 compartilham família,
portanto não afirmamos painel independente nem ausência de erros correlacionados.

## Fundamentação científica

| Trabalho e situação | Prática aproveitada | Limite da adaptação |
| --- | --- | --- |
| [CheckList, Ribeiro et al., ACL 2020](https://aclanthology.org/2020.acl-main.442/) | Testes mínimos, invariância e mudanças direcionais de comportamento | Aplicar a filtros, paráfrases e contexto; não importar resultados do artigo |
| [G-Eval, Liu et al., EMNLP 2023](https://aclanthology.org/2023.emnlp-main.153/) | Rubricas explícitas por dimensão e avaliação estruturada | Não chamar nossa rubrica de reprodução exata do G-Eval: não implementamos sua ponderação probabilística de notas |
| [MT-Bench / LLM-as-a-Judge, Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685) | Comparação cega, inversão A/B e controle de extensão/proveniência | Concordância observada no artigo não é transferível ao nosso juiz ou domínio |
| [LLMBar, Zeng et al., ICLR 2024](https://arxiv.org/abs/2310.07641) | Avaliar o avaliador com alternativas atraentes que violam a instrução | Nossos controles são adaptações locais; não são uma execução do benchmark LLMBar |
| [τ-bench, Yao et al., 2024](https://arxiv.org/abs/2406.12045) | Usuário simulado, ferramentas e sucesso conferido pelo estado final; confiabilidade em repetições | O Mesa é somente leitura: conferir filtros, contexto, IDs e evidências, não mutações de compras |
| [τ²-bench, Barres et al., 2025](https://arxiv.org/abs/2506.07982) | Simulador ligado a objetivos e estados verificáveis, com transições controladas | Não reproduzir o domínio telecom nem declarar pontuação τ²-bench |
| [Yoon et al., NAACL 2024](https://arxiv.org/abs/2403.09738) | Verificar se o próprio simulador segue objetivos e expressa preferências coerentes | Não tratar personas como amostra de uma população real |
| [M-Prometheus, 2025](https://arxiv.org/abs/2504.04953) | Considerar avaliadores especializados e adequação multilíngue | Candidato de pesquisa; pesos não foram baixados ou aprovados, e a licença publicada precisa ser esclarecida |
| [FairJudge, Yang et al., ICML 2026](https://proceedings.mlr.press/v306/yang26n.html) | Auditar aderência à rubrica, vieses não semânticos e consistência | Pesquisa recente, não um padrão universal; seu treinamento não foi reproduzido |
| [Kohli, Apple Research, junho de 2026](https://machinelearning.apple.com/research/correlated-llm-evaluation-panels) | Somar juízes não garante independência nem maior correção | Evidência em tarefas específicas; medir erros compartilhados no nosso conjunto antes de agregar votos |

As bases antigas são deliberadas: publicação recente não demonstra, por si só,
que um método substitui uma prática estabelecida. Os trabalhos de 2026 reforçam
a necessidade de verificar o juiz, em vez de simplesmente aumentar o painel.

## Ferramentas e fronteiras

- **Inspect AI 0.3.288**, ferramenta aberta do UK AI Security Institute e Meridian
  Labs: [documentação](https://inspect.aisi.org.uk/). Foram usados `Task`, `Sample`,
  `ModelAPI`, `generate`, scorer customizado e logs reais. Não é uma promessa de
  usar a ferramenta: a primeira calibração foi executada.
- **SQLite somente leitura** e verificadores de domínio continuam como fonte
  dos fatos. Um juiz não pode validar um preço por opinião.
- **Testes existentes + testes de avaliação isolados** verificam parser, restrição
  a loopback e inversão dos controles. Regras de invariância seguem o desenho
  CheckList, sem exigir a biblioteca antiga para o runtime do produto.
- **Qwen local** é barato para protótipos e usuários simulados, mas a versão de
  1,5B foi reprovada como juiz principal. Capacidade de planejamento não prova
  capacidade de avaliação.
- **Prometheus 2** tem implementação pública e rubricas oficiais, mas seu modelo
  [7B é declarado em inglês](https://huggingface.co/prometheus-eval/prometheus-7b-v2.0).
  Candidatos especializados precisam de templates próprios, adequação PT/EN,
  licença, custo e calibração verificados. Não baixar modelos por popularidade.

Não instalar vários harnesses equivalentes só para listar ferramentas. Inspect
é a escolha principal. Ragas seria mais apropriado a uma avaliação de RAG com
documentos e contextos; a ferramenta central do Mesa consulta catálogo e ranking.

## Primeira calibração executada

[Código executável](../evaluations/inspect_judge_calibration.py) e
[primeiro resultado](../evaluations/results/judge-calibration-v1.json) e
[resultado com papéis separados](../evaluations/results/judge-calibration-v2.json).

Referência: um produto real do catálogo oficial, preservando nome, preço,
identificadores e origem. Criar oito pares de respostas de controle: preço,
moeda, nome, disponibilidade, garantia alimentar, histórico pessoal, extensão e
instrução maliciosa dentro da resposta. Cada par tem uma alternativa correta e
uma violação deliberada conhecida pelo código. Inverter A/B sem informar o
gabarito ao modelo, totalizando 16 inferências locais.

Resultado do Qwen2.5-1.5B Q4_K_M, preservando as duas configurações:

| Configuração | Controles completos corretos | Pares consistentes sob inversão | Admissão |
| --- | --- | --- | --- |
| Instruções e dados no mesmo texto | 9/16 | 1/8 | Reprovado |
| Instruções no papel de sistema; candidatos como dados do usuário | 14/16 | 7/8 | Reprovado |

- Separar papéis melhorou os resultados nestes controles, sem demonstrar melhora geral.
- Na segunda configuração houve uma escolha de garantia alimentar sem suporte e uma referência ao campo de evidência errado.
- Saídas parseáveis não garantiram julgamentos corretos.
- **Não qualificado para o piloto de juiz**; suas notas não aprovarão o produto.

Houve 5.442 tokens locais na primeira execução e 5.280 na segunda, sem chamadas
a API comercial. No total, 32 julgamentos reais, com os dois resultados preservados.
O teste usa um conjunto pequeno de controles fáceis e não estima preferências
humanas. Mesmo 16/16 seria somente uma condição necessária para avançar.

O resumo atual agrupa pares pelo identificador e orientação, sem depender da ordem
do log, e rejeita controles incompletos ou duplicados. Acertos e consistência
não são somados como se fossem medidas independentes.
O template do juiz é parte da configuração testada; o resultado não é uma medida
universal da capacidade do Qwen em qualquer prompt.

## Protocolo de usuários simulados e aceitação

1. Fixar objetivos e estados permitidos antes da geração de mensagens. O modelo
   simulador controla a forma da conversa; o código valida objetivo, orçamento,
   ação permitida e limite de turnos.
2. Rejeitar episódios em que o simulador muda o objetivo ou inventa atributos.
   Registrar falha de simulação separadamente de falha do produto.
3. No produto, conferir cada item contra a fonte, exclusão de sementes, limites,
   ferramenta acionada e continuidade ou troca explícita de consulta.
4. Testar relações: reduzir o preço máximo não admite um item mais caro;
   reformular o mesmo pedido preserva o conceito; trocar o prato não reutiliza
   a consulta antiga. Consultas equivalentes não precisam ter strings idênticas.
5. Aplicar juiz apenas a dimensões que precisem de interpretação. Fornecer
   rubrica, fatos e IDs; ocultar nome do modelo e ranking de origem; inverter a
   ordem. Usar abstinência explícita e registrar cobertura e discordâncias.
6. Congelar conjunto reservado, rubrica e decisões de configuração. Corrigir em
   desenvolvimento; não relabelar o teste para fazer a métrica melhorar.
7. Repetir casos reservados e registrar sucesso médio e **pass^k**: probabilidade
   de todas as k tentativas terem sucesso, diferente de pass@k. Com n tentativas,
   c sucessos e n ≥ k, estimar `comb(c, k) / comb(n, k)` por cenário, depois agregar.
8. Calcular variabilidade por cenário-base; paráfrases e repetições não são
   pessoas independentes. Distinguir falhas de infraestrutura, ausência de
   julgamento e falha do próprio sistema.

O teste oficial de pedidos DHRD é outra avaliação. Não abri-lo para escolher
juiz ou prompt conversacional. Mantê-lo reservado até congelar o protocolo de
recomendação correspondente.

## Reprodução da prova local

Usar Python 3.13. O ambiente de avaliação é separado do `.venv` da API:

```powershell
.venv\Scripts\python -m venv .tools/eval-venv
.tools\eval-venv\Scripts\python -m pip install -r requirements-eval.lock
# Em um terminal, iniciar o Qwen já verificado:
.venv\Scripts\python scripts/run_local.py
# Em outro terminal, na raiz do projeto:
$env:PYTHONPATH = Join-Path $PWD 'src'
.tools\eval-venv\Scripts\python evaluations/inspect_judge_calibration.py --prompt-layout roles --output reports/judge-calibration-new.json
```

`--prompt-layout inline` preserva a comparação com a primeira configuração;
o padrão é separar instruções e dados por papel. O alvo do juiz é exclusivamente
HTTP loopback, sem chave. Não há execução de
código por esse juiz. O controle rejeita URL externa e credenciais no endpoint.

A instalação mais recente de `agent-client-protocol` (1.0.0) não fornecia
`acp.helpers`, importado pelo Inspect desta versão. Foi fixada a versão 0.12.0;
`pip check` passou e a avaliação completou. No Windows houve aviso de superfície
opcional de controle por falta de `AF_UNIX`; o harness de inferência e scoring
funcionou. Essa superfície opcional foi desativada na segunda execução, que
também completou. Os resultados estão preservados. Nada foi instalado na imagem do
Render, e o modelo do site não foi substituído.

## O que não podemos concluir

Não há medida de satisfação humana, representatividade de personas ou impacto
comercial. A pesquisa não prova que Prometheus, FairJudge ou qualquer marca será
o melhor juiz do Mesa. Essa escolha depende de medição no domínio. A camada
objetiva pode ser aceita por testes sem que um juiz reprovado seja promovido.
