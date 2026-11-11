# Canal WhatsApp

O mesmo agente do app web atende pelo WhatsApp, pela WhatsApp Cloud API da Meta.

```text
Meta ──webhook──► gateway (Go) ──XADD──► Redis Stream ──XREADGROUP──► worker (Python) ──► agente ──► Graph API
                  │ HMAC-SHA256 do corpo
                  │ deduplicação por message_id (SET NX, 24 h)
                  └ 200 em milissegundos; 503 se a fila cair (a Meta reenvia)
```

## Por que um gateway separado, em Go

A Meta exige resposta rápida ao webhook e reenvia entregas que falham ou
demoram. O agente pode levar alguns segundos. Separar recepção e
processamento resolve os dois problemas:

- o **gateway** só valida, deduplica e enfileira: binário estático de 15,7 MB,
  sem estado, respondendo em cerca de 5 ms;
- o **worker** consome a fila no seu ritmo, com consumer group, e um reenvio da
  Meta nunca gera duas respostas.

Go entrou onde latência e footprint importam; a IA continua em Python.

## Segurança e privacidade (LGPD)

| Medida | Onde |
| --- | --- |
| Assinatura `X-Hub-Signature-256` verificada em tempo constante antes de qualquer parsing | `webhook.go` |
| Corpo limitado a 1 MB; texto limitado a 500 caracteres | `webhook.go` |
| Telefone nunca aparece em logs; chaves e logs usam hash com sal (`MESA_PRIVACY_SALT`) | `channels/whatsapp.py` |
| Contexto da conversa expira após 24 h sem mensagens | `ConversationStore` |
| Mensagens processadas são removidas da fila; a fila de erros guarda só ID e classe do erro | `Worker.process` |
| "apagar meus dados" apaga o contexto na hora, sem chamar o modelo | `Worker.handle` |
| Redis sem persistência em disco e acessível só pela rede interna | `docker-compose.yml`, `render.yaml` |

## Testes

- `services/whatsapp-gateway/webhook_test.go`: handshake, assinatura (inclusive
  corpo adulterado), duplicatas, status de entrega, botões interativos, limite
  de tamanho, fila indisponível e métricas Prometheus.
- `tests/test_whatsapp_worker.py`: contexto entre mensagens, TTL, chaves sem
  telefone, apagamento, fila de erros sem dado pessoal e cliente da Graph API.
- `scripts/check_whatsapp_flow.py`: integração real (binário Go + Redis + worker
  + LLM + catálogo oficial), com a Graph API simulada localmente.
  [Resultado](../evaluations/results/whatsapp-integration-v1.json).

## Rodar localmente

```sh
docker compose up --build        # redis, gateway (:8090) e app com worker (:10000)
```

Para receber mensagens reais, exponha o gateway com um túnel HTTPS
(por exemplo `cloudflared tunnel --url http://localhost:8090`) ou use o
serviço publicado no Render.

## Conectar o número de teste da Meta

1. Siga o guia de contas para criar o app e obter token, Phone number ID,
   App Secret e Verify Token.
2. Configure as variáveis `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`
   (no app) e `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` (no gateway).
3. No painel da Meta, em **WhatsApp → Configuração**, informe a Callback URL
   `https://<gateway>/webhook` e o mesmo Verify Token. Assine o campo `messages`.
4. Mande uma mensagem do celular cadastrado para o número de teste.

O número de teste conversa com até cinco números cadastrados. Mensagens
iniciadas pelo usuário são gratuitas.
