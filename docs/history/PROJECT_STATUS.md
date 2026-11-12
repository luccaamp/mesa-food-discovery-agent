# Estado do Mesa — entrega de 10/11/2026

[Mesa publicado](https://mesa-meal-discovery.onrender.com) ·
[Critérios e evidências da entrega](RELEASE_1.md) ·
[Executar localmente](../PRODUCT_GUIDE.md) ·
[Roadmap](../ROADMAP.md)

O produto público se chama **Mesa**.

**Publicação conferida:** `05da18acc3c5f76e7ac84e134ad27391924aaf51`,
saúde e prontidão aprovadas; laboratório exibindo 10/10 e a reprovação do juiz.
[Registro atual](../../evaluations/results/release-guarded-v1.json).
Esta conferência não consumiu chamadas ao modelo. A CI da consolidação
passou em 126 testes da aplicação, além dos 21 de avaliação e seis da interface.

A interface agora distingue timeout, pausa do provedor, cota e resposta inválida.
O contrato OpenAPI acompanha os novos campos; nenhuma mensagem privada do
provedor é exposta. A verificação pública posterior à publicação conferiu três
restrições em inglês, uma busca comum e a decisão de relevância, sem inferência.
O [teste no navegador](../../evaluations/results/release-guarded-browser-v1.json)
também confirmou a resposta por política e a reprovação visível do juiz.

## Resultado atual

- **Assistente público: 10/10 contratos**, três inferências reais do Gemini,
  três tentativas e 999 tokens nas respostas concluídas. Foram conferidas
  36 ocorrências de produtos contra o catálogo oficial local.
- **Contingência: 52/52 cenários**, 73 turnos e 282 ocorrências de itens,
  com timeout injetado. Esse resultado não representa chamadas reais ao Gemini.
- **CI:** 126 testes da aplicação em Python 3.11 e 3.13, 21 testes de avaliação,
  seis testes frontend e build aprovados na revisão de confiabilidade.
- **Interface:** busca, evidências, seleção limitada a cinco referências,
  invalidação de sugestões antigas, recomendação e navegação por teclado
  conferidas no navegador público.
- **Relevância:** comparação automática adicional concluída em 16 consultas
  bilíngues. As novas configurações de juiz também foram reprovadas; a última parou com 15/16 acertos antes dos 32 exigidos.
  Nenhuma nota semântica não calibrada foi usada para aprovar o produto.

A aceitação pública foi executada em `4b7df71019ee79499035074ef58557ea133c012b`.
A revisão de documentação e exibição dos resultados é posterior e preserva
essa identificação; não atribui a uma revisão uma inferência de outra.

## O que está implementado

Catálogo oficial de 1.066.840 produtos de Singapura, busca com glossário PT/EN,
filtros de preço normalizado e culinária, evidências por produto, seleção de
referências, recomendações por cestas e popularidade, assistente com ações
restritas e laboratório de experimentos.

Gemini tem até duas tentativas sob orçamento de espera. Duas requisições
consecutivas com falha transitória abrem uma pausa de 60 segundos; depois,
somente uma consulta pode testar a recuperação. A pausa não consome cota.
Erros de autenticação e 429 não são repetidos automaticamente. O glossário
é identificado como alternativa sem inferência.

Dados, artefatos e modelos têm procedência e hashes. Qwen e n8n foram
executados localmente. O teste oficial permanece separado e não foi usado
para ajustar ou medir modelos. Os resultados negativos são mantidos.

## Decisões e limites

Manter a busca lexical expandida no produto. Não promover nem ampliar o E5
atual com base no proxy disponível. O último avaliador composto acertou 15/16 controles executados, mas
precisaria de 32/32. Houve mudança de nota ao inverter a ordem dos casos.
As rodadas anteriores (incluindo 28/40 e 33/48) estão preservadas. **O julgamento semântico calibrado ainda não foi entregue.**
A decisão de não usar esses juízes encerra esses experimentos, sem converter
a reprovação em aprovação.

A nova rodada Gemini passou; rodadas anteriores falharam com timeouts.
Não há garantia de disponibilidade contínua. A hospedagem gratuita pode
dormir; a inicialização foi observada no navegador. As métricas de uso e
latência são amostras, não resultados de carga ou satisfação humana.

Preços são normalizados, sem moeda. O catálogo é histórico e não certifica
ingredientes, alérgenos, estoque, compra ou entrega.

## Correções adicionais verificadas

A proteção de restrições alimentares agora cobre expressões em inglês como
allergy, coeliac e gluten-free, sem chamar o modelo para certificar segurança.
Nomes comuns como egg sandwich continuam pesquisáveis. A CI desta revisão
passou em 126 testes da aplicação, 21 de avaliação e seis da interface.

[Pesquisa e resultados da rodada](../RELEVANCE_REASONING_2026-11-10.md).
