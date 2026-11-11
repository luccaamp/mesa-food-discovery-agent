# Direção de experiência e visual

Implementado como Mesa: frontend React/TypeScript com descoberta, conversa e laboratório, conectado ao backend real. A direção abaixo orientou a implementação. Não foi realizado estudo com usuários nem há protótipo aprovado por terceiros.

Verificação: layouts 360/768/1440 pixels CSS sem overflow horizontal, navegação real, diálogo com rótulo e Escape, retorno ao topo nas mudanças de área, estado vazio e recuperação de busca. Seis combinações principais de texto foram corrigidas para razões de contraste 6,22–6,49. Isso não é certificação completa de acessibilidade.

## Telas

1. Descobrir: busca destacada, preferências suportadas, cidade histórica, resultados e origem dos atributos.
2. Conversar: mensagens e cards sincronizados; edição de filtros, esclarecimentos e estado das ferramentas.
3. Entender recomendação: evidência do catálogo/histórico, limites e versão; associação não será rotulada como causa.
4. Laboratório: comparação de modelos, distribuição de erros, cobertura, custo e latência medidos; vazio informativo até existirem experimentos.

## Sistema visual inicial

Fundo creme `#FAF8F5`, texto `#17231D`, verde escuro `#153F32` para ações e terracota `#A63F2A` para destaque. Conferir contraste das combinações efetivamente usadas. Tipografia sans-serif legível, grade consistente, cards leves e espaçamento de 8px como referência. Identidade própria, sem copiar marcas de terceiros.

Componentes: campo de busca, filtros, card de resultado, painel de evidências, mensagem de ferramenta, gráfico com alternativa textual, seleção de perfil histórico. Sem foto real disponível, usar ilustração por categoria com rótulo, sem sugerir ser foto do item.

## Critérios de aceitação

- Layouts verificados em 360px, 768px e 1440px; navegação por teclado e foco visível.
- Carregando, nenhum resultado, dados ausentes, timeout e falha do provedor têm orientação útil.
- Unidades, cidade, período histórico e preço normalizado aparecem claramente.
- Rótulos acessíveis, contraste verificado, suporte a movimento reduzido e validação de formulários.
- Não exibir métricas ou depoimentos fabricados; evitar números decorativos.
- Avaliar tarefas com pelo menos três voluntários se houver disponibilidade, registrando consentimento, erros e tempo. Amostra pequena será descrita como exploratória.

Protótipos podem usar ferramentas de geração de interface, conforme acesso real. Guardar decisões, revisão humana e limitações; implementar e testar a versão final no repositório.
