# Automação n8n executada

O [workflow versionado](evaluation-report-v1.json) foi importado e executado no n8n 2.46.6 com Node 24.22.2. Consulta a API real, valida o contrato e gera um relatório Markdown com os experimentos de recomendação e recuperação. Não treina modelos dentro do workflow nem envia mensagens a terceiros.

Fluxo: gatilho manual → `GET /v1/evaluations` → validação e formatação em JavaScript. Os três nós concluíram com sucesso. [Evidência sanitizada](../results/n8n-execution-v1.json) e [Markdown produzido](../results/n8n-evaluation-report-v1.md).

Em 10/11, a [versão 2](evaluation-report-v2.json) foi importada e executada,
incluindo os 40 cenários/120 episódios de conversas, 177 turnos e 702 ocorrências
de itens conferidas. Três nós concluídos em aproximadamente 13,15 segundos totais.
[Evidência v2](../results/n8n-execution-v2.json) e
[Markdown v2](../results/n8n-evaluation-report-v2.md).
O runner aceita `--workflow-id mealEvaluationV2`. O Windows precisou da pasta
temporária local `.tools/test-temp`; o script a define para evitar a falha de
inicialização observada. Importações e execuções devem ser sequenciais.

## Reproduzir no Windows

Com a API em 8000, na raiz do repositório:

```powershell
.venv\Scripts\python scripts/setup_n8n.py
$env:PATH="$PWD\.tools\node-v24.22.2-win-x64;"+$env:PATH
$env:N8N_USER_FOLDER="$PWD\.tools\n8n-state"
$env:N8N_DIAGNOSTICS_ENABLED='false'
$env:N8N_PERSONALIZATION_ENABLED='false'
$env:N8N_VERSION_NOTIFICATIONS_ENABLED='false'
.tools\node-v24.22.2-win-x64\node.exe .tools\n8n\node_modules\n8n\bin\n8n import:workflow --input=evaluations/n8n/evaluation-report-v1.json
.venv\Scripts\python scripts/run_n8n_report.py --output reports/n8n-run.json --markdown reports/n8n-report.md
```

Node portátil e estado privado ficam em `.tools/`, ignorado pelo Git. A primeira instalação de n8n pode demorar vários minutos. O helper fixa versão e SHA do Node e a versão principal do pacote n8n; o lock transitivo desta instalação fica local. Não modifica o Node global. Em outro sistema, usar a instalação oficial de Node 24 e n8n 2.46.6; o helper de exportação atual foi testado no Windows.

Para editar visualmente, iniciar o n8n com o mesmo `N8N_USER_FOLDER` e abrir sua instância local. Configurações, chaves, tokens de retomada e logs brutos da execução não devem ser exportados. O script publica somente nomes/status/durações dos nós, hash do Markdown e contagem de relatórios.

## Medidas e limites

A execução medida levou cerca de 8,75 segundos incluindo inicialização da CLI. O relatório distingue os protocolos e informa o caráter fraco dos rótulos de recuperação. Não mede tempo manual; não há economia percentual demonstrada, agendamento recorrente, detecção de regressões ou envio automático de mensagens.

Também foram verificados repetição com o mesmo input, produzindo o mesmo SHA-256 do Markdown, e falha real com uma cópia controlada apontando a uma fonte local indisponível. [Contratos executados](../results/n8n-contract-checks-v1.json). Não houve teste de credencial inválida, pois este workflow não usa credenciais.

O runner usado foi JavaScript. O n8n também informou ausência do ambiente opcional de runner Python; nenhum nó deste workflow depende dele. A automação local concluiu com sucesso.

Referências: [CLI oficial](https://docs.n8n.io/hosting/cli-commands/) e [instalação](https://docs.n8n.io/hosting/installation/npm/). A execução é manual e local, sem conta comercial ou implantação pública do n8n.
