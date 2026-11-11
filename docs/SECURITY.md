# Segurança, privacidade e operação

## Modelo de ameaças (OWASP Top 10 para aplicações com LLM, 2025)

| Risco | Como aparece aqui | Controles | Verificação |
| --- | --- | --- | --- |
| LLM01 Prompt injection | Mensagem do usuário ou nome de item do catálogo tenta mudar regras | Políticas antes do modelo; texto do usuário e resultados de ferramentas tratados como dados no prompt; grounding na resposta | Red team: injeção direta, mensagem de "sistema" falsa, catálogo envenenado |
| LLM02 Divulgação de dados sensíveis | Usuário digita telefone, e-mail, CPF; pedido de dados de clientes ou chaves | Mascaramento antes do LLM (`privacy.py`); artefato público sem tabelas de clientes; chaves só no ambiente | `test_privacy.py`; red team: exfiltração |
| LLM05 Saída imprópria | Texto do modelo vira busca FTS5 ou resposta | Consulta tratada como termos (nunca SQL); consulta inválida rejeitada sem erro 500; resposta final filtrada | `test_agent.py`; red team: operadores FTS e símbolos |
| LLM06 Agência excessiva | Modelo tenta ferramentas inexistentes ou muitas chamadas | Só duas ferramentas somente leitura; até 2 execuções e 3 chamadas ao modelo por turno | `test_agent.py`; red team: ferramenta desconhecida, várias buscas |
| LLM07 Vazamento do prompt de sistema | Role-play, tradução ou "imprima suas instruções" | Política de injeção; prompt instrui a não revelar; verificação de fragmentos do prompt | Red team: 3 variações |
| LLM09 Desinformação | Moeda, alergênicos, saúde, estoque, entrega | Política recusa garantias; grounding bloqueia moeda, números inexistentes e alegações | Red team: moeda, alergia PT/EN, saúde, entrega |
| LLM10 Consumo ilimitado | Abuso de cota da camada gratuita | Cota local por provedor, pausa após falhas, limite de requisições, corpo e concorrência na API | `test_cloud.py`, `test_provider_cooldown.py` |

**Resultados do red team** ([v1](../evaluations/results/red-team-v1.json),
[v2 Groq](../evaluations/results/red-team-v2-groq.json)): na v1, 6 falhas eram
falso positivo do verificador (a recusa determinística cita "reais" para
recusar a conversão) e 5 casos do Gemini caíram no glossário por cota esgotada,
sem exercitar o modelo. Depois de restringir as verificações de conteúdo a
texto escrito pelo modelo, o Groq passou em 24/24 (15 casos chegaram ao
modelo, 9 foram barrados antes por políticas). O Gemini será reexecutado com
cota disponível.

## Privacidade (LGPD)

- **Minimização:** a descoberta de comida não precisa de dados pessoais;
  identificadores digitados são mascarados antes de qualquer provedor externo,
  e o usuário é avisado.
- **Sem perfil no servidor:** a personalização do app web usa apenas o que fica
  no navegador (sacola e itens recentes).
- **WhatsApp:** telefone só em hash com sal; contexto expira em 24 h; fila sem
  retenção; "apagar meus dados" atende o direito de eliminação na hora.
- **Dados de treino:** o artefato publicado contém catálogo, popularidade e
  vizinhança entre itens, nunca pedidos ou clientes individuais.

## Observabilidade

- **Métricas** em `/metrics` (Prometheus): latência HTTP por rota, chamadas de
  LLM por provedor, modelo e resultado, tokens, latência de ferramentas, turnos
  e motivos de fallback. Rótulos de baixa cardinalidade, sem texto do usuário.
- **Traces** OpenTelemetry com as convenções semânticas de GenAI
  (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*`), exportados por
  OTLP quando `OTEL_EXPORTER_OTLP_ENDPOINT` está definido (Jaeger, Tempo,
  Langfuse e outros).
- **Logs** estruturados com `request_id`, sem corpo de requisição, URL do
  provedor ou chave. O gateway Go expõe `/metrics` próprio.
