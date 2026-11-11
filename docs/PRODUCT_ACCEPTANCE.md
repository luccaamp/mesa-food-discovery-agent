# Critérios de aceitação do Mesa

## Revisão de teclado em 10 de novembro de 2026

A janela de evidências deixava o foco ir ao `body` depois do último botão.
Corrigido o ciclo de Tab e Shift+Tab, inclusive quando o segundo botão está
desabilitado pela seleção máxima. O Escape continua fechando o diálogo e o foco
retorna ao botão “Ver evidências”. A descrição das limitações agora está associada
ao diálogo por `aria-describedby`.

Verificação real na prévia local: foco inicial, Tab entre os botões, repetição do
último para o primeiro, Shift+Tab inverso e retorno após Escape. Auditoria básica
do DOM encontrou um `main`, um `h1`, idioma `pt-BR`, nenhum ID duplicado e nenhum
campo/botão visível sem nome. [Registro](../evaluations/results/keyboard-accessibility-v1.json).
Isso não é uma execução axe, estudo com leitor de tela, auditoria de contraste
ou declaração de conformidade WCAG completa.
Com cinco referências selecionadas, a adição de um sexto item fica desabilitada;
Tab e Shift+Tab permanecem no único botão habilitado do diálogo. Esse ramo também
foi conferido no navegador. [Seleção máxima](../evaluations/results/keyboard-accessibility-max-selection-v1.json).

## Aceitação pública Gemini em 10/11

Seis tarefas concluídas no site, três inferências Gemini reais e 24 ocorrências
de itens comparadas com a base oficial SQLite: busca, continuidade de preço,
troca de prato, esclarecimento fora do domínio, restrição sem evidência e
recomendação excluindo a referência. Os tokens das respostas concluídas somaram
1.000. [Registro](../evaluations/results/public-assistant-acceptance-v1.json).
É uma bateria pequena de aceitação; não uma nota de satisfação ou garantia de uptime.

## Correções verificadas em 9 de novembro de 2026

| Tarefa | Comportamento esperado | Verificação |
| --- | --- | --- |
| Ler preço pequeno | `0,002` continua positivo, sem moeda | Teste frontend e navegador |
| Interpretar zero | “Zero na fonte”, sem promessa de gratuidade | Navegador e teste frontend |
| Falha parcial no estado da IA | Catálogo e relatórios continuam carregando; aviso específico | Servidor local de QA com `/v1/system` em 503 |
| Recuperar serviço | “Tentar novamente” remove o aviso, sem recarregar a página | Navegador após retirar a falha simulada |
| Filtrar e limpar | Máximo `0,001`: 5.088 resultados; limpar restaura 27.621 para arroz com frango | Navegador e HTTP com dados oficiais |
| Trocar referências | Sugestões antigas desaparecem até novo cálculo | Navegador |
| Pedir recomendação sem LLM | “Recomende algo” usa ferramenta e identifica ação explícita | Teste HTTP e navegador |
| Conferir motivo de uma sugestão | Resposta do assistente preserva motivo, cestas e coocorrências | Regressão HTTP |
| Ler no celular | Cards em uma coluna, botões e preços legíveis, sem overflow horizontal | Navegador com viewport 360 × 800 |
| Interpretar o laboratório | Offline separado de uso público; execução Qwen identificada como local | Navegador e contrato da API |

Verificações automatizadas: 81 testes Python, 6 testes frontend e build TypeScript/Vite.
O protocolo Qwen foi reexecutado: 13/13 contratos, 48 itens conferidos, 7 chamadas
locais e 2.252 tokens. Não é medida de satisfação humana ou de qualidade geral.

## Por que os preços pareciam zerados

O formatador anterior limitava a exibição a duas casas. No índice oficial,
541.161 produtos têm preço positivo abaixo de 0,005; esses valores eram exibidos
como `0,00`. Há também 294.542 zeros registrados na fonte, preservados como tais.
Isso não permite inferir gratuidade, moeda ou disponibilidade atual. A correção
muda a apresentação, sem reescrever preços nem modificar os bancos de dados.

## Pendências registradas em 9/11, antes da etapa automatizada

- Ampliar a avaliação reservada do Gemini, já configurado e testado em consultas reais.
- Executar a avaliação de relevância por IA com juiz calibrado e rótulos identificados como automáticos.
- Executar perfis simulados e testes de tarefas com verificadores objetivos, sem participantes humanos.

A hospedagem gratuita pode dormir. Limites locais de requisições e de tentativas
Gemini reduzem abuso, mas não substituem a elegibilidade e a cota do provedor.
Não há promessa de aprovação no estágio, impacto comercial ou produto perfeito.

Em 10/11, o autor escolheu avaliação sem participantes humanos. Essa passa a ser
a condição técnica de conclusão: [protocolo e pesquisa](AUTOMATED_EVALUATION.md).
Satisfação humana permanece não medida, sem bloquear a implementação.
