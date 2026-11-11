# Mesa no Render Free com Gemini

A publicação usa um único serviço Docker com interface React, FastAPI, catálogo
lexical e vizinhos de cestas já calculados. Qwen, embeddings, preparação dos dados
e n8n continuam locais. Nenhum treinamento ou download é feito ao acordar o serviço.

Publicado em [mesa-meal-discovery.onrender.com](https://mesa-meal-discovery.onrender.com).
Seis verificações HTTP passaram no serviço real em 7 de novembro de 2026.
O Gemini 3.1 Flash-Lite foi configurado e testado em chamadas reais em 9 de
novembro. O modelo 2.5 anterior retornou HTTP 404 para a conta nova.
[Evidência do provedor](../evaluations/results/gemini-live-v1.json).
[Evidência da implantação](../evaluations/results/cloud-deployment-v1.json).

Em 9 de novembro, a revisão de uso foi publicada e passou em oito verificações
HTTP, incluindo precisão do preço, filtros decimais e evidência da recomendação
pela conversa. [Evidência atual](../evaluations/results/product-ux-v1.json).

## Dados reais e reprodução

`deploy/catalog-serving-sg-v1.json` fixa SHA-256 e tamanho do ZIP e de cada arquivo.
O build baixa a release `mesa-data-sg-v1`, confere hashes, integridade SQLite,
tabelas permitidas e origem comum. O pacote contém 1.066.840 produtos reais e
2.165.201 associações direcionadas de itens. Não contém tabelas de clientes ou
pedidos individuais. Treino termina no dia 61; não mede o teste oficial.

Licença MIT declarada pelo [publicador do DHRD](https://github.com/deliveryhero/dh-reco-dataset#license).
Atribuição e referência acadêmica seguem em `deploy/DATA-NOTICE.txt` e no ZIP.
Os dois SQLite somente leitura somam 570.863.616 bytes; isso representa tamanho
em disco, não memória RAM. Eles ficam dentro da imagem imutável.

```sh
docker build -t mesa .
docker run --rm --memory=512m --cpus=0.1 -p 10000:10000 -e LLM_PROVIDER=disabled mesa
python scripts/check_cloud.py
```

O workflow manual **Cloud image verification** constrói a imagem e verifica os
dados completos com 512 MB/0,1 CPU e filesystem somente leitura. Ele não chama
Gemini. Testes unitários de transporte também não provam disponibilidade ou
qualidade do modelo externo.

## Configuração do serviço

O `render.yaml` declara explicitamente `plan: free`, sem banco pago ou disco
persistente. A mesma configuração pode ser criada pela API do Render. Escolher
o repositório público e a branch `main`, runtime Docker e health check `/ready`.

O serviço atual foi criado pela URL pública do repositório. Esse modo exige
deploy manual depois de enviar os commits: conferir o histórico de Deploys e
usar **Manual Deploy → Deploy latest commit** quando não houver implantação
pendente. A flag `autoDeploy` isoladamente não comprova integração com o GitHub.
Para automação por push, conectar o provedor Git na conta do Render.

No painel Environment do serviço, cadastrar **GEMINI_API_KEY** como segredo.
Não colocar a chave no Git, no Dockerfile, em captura de tela ou no chat.
Usar um projeto Google elegível para o nível gratuito; não habilitar faturamento
para esta demonstração. A disponibilidade e a cota reais dependem da conta.

Defaults: `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.1-flash-lite`,
`GEMINI_CALLS_PER_MINUTE=4`, `GEMINI_CALLS_PER_DAY=20`, `MEAL_PUBLIC_MODE=1`.
O modelo só interpreta a intenção em JSON; consultas controladas retornam os
produtos e o domínio monta os fatos. A chave vai no header do provedor.

Sem chave, com erro, resposta inválida ou cota esgotada, o assistente usa somente
o glossário explícito e informa a limitação. Busca, filtros e recomendação
continuam disponíveis. `/v1/system` distingue configuração de disponibilidade
verificada: não faz chamadas externas de health check que gastariam a cota.

## Limites conhecidos

O Render Free [suspende serviços ociosos](https://render.com/docs/free), portanto
a primeira abertura pode demorar cerca de um minuto. Há limites mensais de
horas, tráfego e builds. O serviço não mantém alterações em disco entre reinícios.
O plano não oferece garantia de disponibilidade.

A admissão limita globalmente 60 consultas pesadas/minuto, quatro simultâneas e
8 KiB por corpo de requisição pesada. O orçamento Gemini conta tentativas,
inclusive falhas. Erros HTTP transitórios 500/502/503/504 permitem no máximo uma
repetição adicional: até duas tentativas por pedido, cada uma admitida pela cota.
Timeouts, erro de formato, autenticação e 429 não geram repetição automática.
`Retry-After` é respeitado; se a espera exceder o orçamento, a aplicação usa a
contingência em vez de encurtar a espera do provedor. O timeout por tentativa é
de até 20 segundos, com orçamento total de 45 segundos para a integração.
Esses contadores são locais ao processo,
reiniciam em restart e não substituem a cota do Google. O orçamento diário usa UTC.
Não são uma garantia financeira: mantenha o projeto Google sem faturamento.

`usage.provider_attempts` informa tentativas de transporte, incluindo falhas.
Os tokens informados vêm apenas da resposta concluída; o consumo de tentativas
anteriores com erro é desconhecido e aparece em `failed_attempts_usage_unknown`.
Não interpretar esses tokens como faturamento total. `/v1/system` também expõe o
SHA público do deploy por `RENDER_GIT_COMMIT`, quando válido, sem ler segredos.

## Aceitação pública com orçamento

`scripts/check_public_assistant.py --output reports/public-acceptance-new.json`
executa seis contratos sobre o serviço conhecido: busca, refinamento de preço,
troca de prato, esclarecimento, restrição alimentar e recomendação por referência.
Confronta os itens com o SQLite oficial local. O protocolo é de aceitação de deploy,
não um benchmark externo de qualidade. Não lê chave e não confunde glossário com
inferência Gemini. Há no máximo oito tentativas de modelo, ritmo conservador,
interrupção após duas inferências consecutivas falharem e preservação de evidência
parcial. Não reiniciar/republicar para contornar cota.

O diagnóstico de 10/11 distinguiu dois registros anteriores: `network_error` em
06:00 UTC e **HTTP 503 do provedor** em 06:34 UTC. O segundo não era um timeout;
o motivo foi confirmado nos logs sanitizados do Render. A recuperação é testada
por falhas injetadas antes da verificação real, sem alterar o modelo ou o segredo.

Na implantação `03ccef0`, a bateria pública concluiu **6/6 tarefas**, com três
inferências Gemini reais, três tentativas e 1.000 tokens nas respostas concluídas.
Foram conferidas 24 ocorrências de produtos diretamente na cópia oficial SQLite,
mantendo preço, identidade, culinária e exclusão da referência. A mediana HTTP
de 1.393,725 ms inclui rede e tarefas determinísticas; não é latência isolada do
modelo nem comparação com um protocolo local diferente.
[Registro completo](../evaluations/results/public-assistant-acceptance-v1.json).
Todas as inferências concluíram na primeira tentativa. O retry foi comprovado por
testes de falha controlada, não por uma ocorrência 503→sucesso nesta bateria.
Uma execução pequena não garante disponibilidade contínua do Google ou do Render.

Apenas a mensagem e a busca anterior seguem ao provedor; não envie dados pessoais
na demonstração. Logs da aplicação não incluem corpos, query strings ou chave.
Catálogo histórico, preço normalizado e ausência de garantias alimentares ou de
entrega continuam visíveis no produto.
