# Servidor MCP

O Mesa expõe suas ferramentas de catálogo pelo
[Model Context Protocol](https://modelcontextprotocol.io). Qualquer cliente MCP
(Claude Desktop, Claude Code, Cursor, agentes em IDE) pode buscar pratos,
ler um item e pedir recomendações por cestas reais, usando as mesmas funções
de domínio do assistente web.

| Ferramenta | O que faz |
| --- | --- |
| `search_catalog_items` | Busca BM25 por nome de prato ou bebida, com glossário PT→EN, filtro de preço e culinária |
| `get_item` | Lê um item pelos identificadores anonimizados |
| `recommend_items` | Itens comprados junto com até cinco referências, completados por popularidade |
| `list_cuisines` | Culinárias disponíveis como filtro |

Recurso: `mesa://catalog/provenance`, com dataset, hashes e limites do catálogo servido.

Todas as ferramentas são marcadas como somente leitura (`readOnlyHint`) e
idempotentes. Argumentos são validados por schema. Pedidos de garantia
alimentar são recusados, porque nomes não comprovam ingredientes.

## Instalar e rodar

```sh
pip install -e ".[mcp]"
mesa-mcp                      # stdio; ou: python -m meal_discovery.mcp_server
```

Os caminhos dos índices vêm de `MEAL_CATALOG_INDEX` e `MEAL_SERVING_INDEX`
(padrão: `data/processed/`).

## Claude Desktop

Em `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mesa": {
      "command": "C:/caminho/para/mesa-food-discovery-agent/.venv/Scripts/mesa-mcp.exe",
      "env": {
        "MEAL_CATALOG_INDEX": "C:/caminho/para/mesa-food-discovery-agent/data/processed/singapore-catalog-v1.sqlite",
        "MEAL_SERVING_INDEX": "C:/caminho/para/mesa-food-discovery-agent/data/processed/singapore-serving-v1.sqlite"
      }
    }
  }
}
```

## Claude Code

```sh
claude mcp add mesa -- python -m meal_discovery.mcp_server
```

## Verificação

`tests/test_mcp_server.py` abre uma sessão MCP real em memória: lista as
ferramentas, confere as anotações de somente leitura, busca, lê e recomenda
sobre um catálogo de teste e verifica que argumentos fora do schema são
rejeitados pelo protocolo.
