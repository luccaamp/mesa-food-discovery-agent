# Avaliador de relevância: raciocínio e saída validada

Os experimentos anteriores usavam Qwen3-8B com raciocínio desativado,
temperatura zero e saída JSON restringida. A documentação do modelo recomenda
amostragem diferente e alerta sobre decodificação gulosa:
https://huggingface.co/Qwen/Qwen3-8B.

## Diagnósticos de desenvolvimento

A rubrica e as respostas esperadas foram preservadas. Os controles v2 já
tinham sido observados e são usados apenas para diagnóstico, nunca como
novos controles de admissão.

- `relevance-thinking-diagnostic-v1.json`: raciocínio aberto, temperatura 0,6,
  top-p 0,95, top-k 20, até 2.048 tokens. Quatro notas corretas em português;
  o lote em inglês não gerou uma resposta final aceita. Experimento incompleto,
  juiz não admitido. O lote português levou aproximadamente 301 segundos.
- `relevance-thinking-diagnostic-v2.json`: diagnóstico inglês isolado com
  aceitação de uma cerca JSON completa. Nenhuma nota aceita: faltou o
  delimitador final do raciocínio. A falha não pode ser corrigida extraindo
  um JSON intermediário do raciocínio.

Os arquivos executados desses dois diagnósticos estão em
`evaluations/snapshots/`, com hashes correspondentes aos relatórios.
Nenhum raciocínio interno foi armazenado nos relatórios ou mostrado no produto.

## Candidato com duas fases

`evaluations/relevance_judge_bounded.py` limita o raciocínio a 512 tokens e
depois abre explicitamente a fase final, restringida por esquema JSON.
As duas fases usam o mesmo modelo verificado e a mesma rubrica. As notas
finais ainda precisam passar por validação estrita; completar a geração não
comprova relevância correta.

Os testes verificam a transição após raciocínio truncado e a rejeição de nota
booleana inválida. Os controles v3 foram escritos antes da execução dessa
configuração: oito controles novos, português/inglês e duas ordens, exigindo
32/32 acertos para admissão. Um lote com erro encerra a calibração com rejeição.

Nenhuma configuração será usada para pontuar o catálogo antes dessa admissão.
Os controles são sintéticos e autorados por IA; não equivalem a validação humana
ou a um benchmark externo. Os pedidos oficiais de teste não são utilizados.

## Falhas preservadas e proteções determinísticas

O diagnóstico em duas fases acertou 8/8 controles de desenvolvimento em dois
lotes de aproximadamente 116 e 111 segundos. A primeira calibração nova foi
interrompida com 7/8 acertos: `Item 7392` recebeu 0, embora devesse receber -1
por falta de informação. Os outros 24 julgamentos não foram executados.

O candidato seguinte interceptou códigos de inventário e nomes genéricos,
como `Chef's Special`, antes de chamar o modelo. Na calibração v4, também
parou com 7/8: `Egg-Free Bread` foi considerado seguro para uma consulta sobre
alergia a ovo. Essa versão continua reprovada; a resposta esperada não mudou.

O terceiro candidato reutiliza a proteção de restrições do produto e não
envia essas consultas ao juiz. A proteção do assistente foi ampliada para
`allergy`, `coeliac`, `gluten-free`, `dairy-free`, `no peanuts` e expressões
semelhantes. Nomes comuns como `egg sandwich` continuam permitidos. A regra
apenas recusa garantias que o catálogo não pode fornecer; não diagnostica
alergias nem determina quais alimentos são seguros.

Novos controles v5 foram congelados antes da terceira calibração. As
abstenções determinísticas fazem parte do avaliador composto e são contadas
separadamente das decisões do Qwen. A aprovação desse sistema não será
descrita como 32 acertos produzidos exclusivamente pelo modelo.

O piloto preparado mede somente o primeiro resultado das 16 consultas PT/EN
nos quatro métodos, usando o mesmo relatório de recuperação. Não mede
NDCG@10, recall ou generalização. Buscas vazias não são removidas do cálculo;
abstenções são reportadas e excluídas da taxa de correspondência. Os nomes
entram no juiz sem método, posição, popularidade ou preço.

## Resultado final desta rodada

A terceira calibração foi encerrada com **15/16 acertos**, antes dos 32
previstos. Ao inverter a ordem, `Fish Soup` para a consulta `peixe grelhado`
mudou de nota 0 para nota 1. Essa inconsistência de tipo de prato impede
admitir o avaliador, mesmo depois de corrigir as abstenções e o formato.
Das 16 decisões executadas, quatro abstenções vieram das regras explícitas.

**Nenhum resultado do catálogo foi pontuado pelo juiz.** O piloto top-1 está
implementado com uma barreira de admissão testada, mas não foi executado.
Não há taxa de relevância semântica calibrada a publicar. A decisão continua
sendo manter a busca lexical com glossário; a comparação anterior por regras
de nomes permanece uma aproximação, separada de notas de um juiz.

As melhorias de produto desta rodada são concretas: causas de contingência
distintas na interface, contrato OpenAPI atualizado e proteção de restrições
alimentares em inglês. Elas não dependem da aprovação do juiz experimental.
Os 126 testes da aplicação passaram em Python 3.11 e 3.13, além dos 21 testes
de avaliação, seis testes da interface e build. A CI não executa o modelo local;
os relatórios de calibração documentam essas execuções separadamente.
