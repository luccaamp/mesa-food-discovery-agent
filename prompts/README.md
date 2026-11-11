# Prompts

O prompt implementado está em [intent_v1.txt](../src/meal_discovery/prompts/intent_v1.txt), incluído no pacote Python como recurso. Ele define ações permitidas, tradução de intenção para termos do catálogo, formato estruturado, exemplos e limites. O LLM não recebe licença para inventar itens, preços ou garantias alimentares.

Fluxo: políticas explícitas → uma chamada de planejamento → validação Pydantic → ferramenta somente leitura → resposta com campos reais. O texto final é montado pelo domínio, não uma síntese livre do modelo. Não afirmar que já existe um agente autônomo com múltiplas etapas ou geração livre validada.

O [protocolo de desenvolvimento](../configs/assistant-development-v1.json) e [execução real](../evaluations/results/product-flow-v1.json) registram casos, tokens, latência e conferência dos itens contra o catálogo. Alguns exemplos de teste também aparecem no prompt; estes resultados são contratos de desenvolvimento, não generalização em teste reservado ou comparação independente entre provedores.

O adaptador OpenAI usa function calling estrito conforme a [documentação oficial](https://developers.openai.com/api/docs/guides/function-calling), mas não foi executado contra o serviço comercial por ausência de chave configurada. A execução demonstrada é Qwen local via llama.cpp.
