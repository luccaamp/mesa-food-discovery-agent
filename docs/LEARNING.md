# Entender esta primeira implementação

## O que estamos construindo

Um sistema que sugere refeições a partir de compras anteriores e permite buscar opções por conversa. Os dados publicados pela Delivery Hero serão a matéria-prima. A interface mostrará o produto; os experimentos mostrarão a qualidade e os limites.

## Por que começar pelos dados

Para recomendar, precisamos saber quais itens existem e quais compras aconteceram. Se a ligação entre produto, estabelecimento e pedido estiver errada, o sistema aprenderá padrões errados. O comando `prepare-singapore` verifica essas relações e coloca pedidos com produtos ausentes em quarentena antes de criar a base de análise.

## Como as primeiras sugestões funcionam

- Popularidade: sugerir itens frequentes nas compras passadas.
- Repetição: sugerir o que aquele perfil costuma comprar.
- Similaridade por cesta: usar itens que costumam aparecer juntos em pedidos anteriores.

Essas referências permitem testar se uma solução mais sofisticada realmente acrescenta qualidade. O assistente de linguagem e os embeddings serão componentes próprios nas próximas etapas.

## Como conferimos se funciona

Usamos compras antigas para montar os perfis. Guardamos compras posteriores para verificar se os itens comprados aparecem entre as sugestões. A compra futura nunca deve ajudar a construir o perfil que será avaliado.

Os exemplos sintéticos são pequenos registros inventados para testar o código, como testes de uma calculadora com números conhecidos. Eles não comprovam desempenho em pessoas ou operações reais. O relatório deixa essa distinção explícita.

## Exercício de compreensão

No teste automatizado, um perfil novo compra um item que não aparece no treino. Confira no código por que ele conta como erro e por que removê-lo do cálculo melhoraria artificialmente a métrica. Depois, localize o teste que adiciona compras futuras sem alterar a validação anterior. Esse cenário fica só nos testes; produto e experimentos usam dados reais.

## Entender o primeiro resultado real

Na [primeira validação](EXPERIMENT_001.md), repetição recuperou em média 16,04% dos itens da próxima cesta entre dez sugestões. Isso não significa que 16,04% das pessoas gostaram das recomendações. A métrica de clientes com pelo menos um item recuperado foi outra: Hit Rate@10, de 19,89%.

Para estudar antes de apresentar: explique por que 41 linhas problemáticas levaram à exclusão de 35 pedidos inteiros; por que repetições de item dentro de um pedido foram consolidadas; e por que os 21.480 clientes sem histórico recebem as mesmas sugestões nas três referências. Reproduza um teste pequeno e encontre a consulta SQL que limita o treino ao dia 61.
