# Mesa — interface do produto

React + TypeScript + Vite, conectado ao backend real. Três áreas: exploração do catálogo, assistente e laboratório de experimentos. Não há dados de exemplo como fallback. Os gráficos de pratos são elementos visuais, sem fotos ou nomes de estabelecimentos inventados.

Na raiz do projeto:

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
.venv\Scripts\python scripts/run_local.py
```

Abrir [Mesa local](http://127.0.0.1:8000). O comando inicia o modelo Qwen local e a API; Ctrl+C encerra ambos. Requer dados/índices e pesos já preparados, conforme o [guia completo](../../docs/PRODUCT_GUIDE.md). Para usar somente catálogo e glossário explícito, adicionar `--no-llm`.

Desenvolvimento com atualização automática: executar a API em 8000 e `npm --prefix apps/web run dev`. O Vite encaminha `/v1` à API local. Na versão construída, a própria API serve os assets, sem necessidade de CORS amplo ou chaves no navegador.

Verificado: TypeScript estrito, build de produção, navegação/consulta real, diálogo por teclado, estado vazio sem itens fabricados, recomendações e laboratório. Layouts de 360, 768 e 1440 pixels CSS sem overflow horizontal. Seis combinações principais de texto foram medidas após correção de contraste, com razões entre 6,22 e 6,49. Não é certificação completa de acessibilidade; testes com usuários ainda estão pendentes.

Seleção e conversa vivem apenas no estado desta aba; recarregar reinicia a sessão. É possível selecionar até cinco itens como referências. Recomendações indicam se vieram de associação entre cestas ou de popularidade histórica. O assistente identifica quando usa o glossário em vez do LLM.

Ainda não há implantação pública do backend/modelo. O frontend foi executado localmente; não apresentar a URL do GitHub como URL da aplicação hospedada.
