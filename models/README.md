# Modelos e artefatos locais

Três referências de recomendação foram avaliadas em 175.358 clientes de validação interna oficial. [Experimento 002](../docs/EXPERIMENT_002.md). A versão histórica do espelho está preservada no Experimento 001. Pedidos de teste oficial continuam sem avaliação.

- `data/processed/singapore-serving-v1.sqlite`: popularidade e vizinhos por cestas, ajustados exclusivamente até o dia 61, para sugestões a partir de itens selecionados. Artefato local, sem histórico de usuário fabricado.
- `models/e5-small-onnx-v1/`: modelo E5 pré-treinado, convertido para ONNX quantizado, usado no piloto semântico de 10.000 produtos. Não promovido para a busca do produto por qualidade insuficiente.
- `models/qwen-local-v1/`: Qwen2.5-1.5B-Instruct Q4_K_M oficial, para planejamento de intenção em português. Configuração, revisão e SHA-256 em [local-llm-v1.json](../configs/local-llm-v1.json). Runtime llama.cpp portátil fica em `.tools/`, fora do Git.

Nenhum modelo neural foi treinado/fine-tuned pelo projeto ou publicado na conta Hugging Face do autor. Os modelos pré-treinados foram obtidos, verificados e executados localmente. Pesos, bancos e artefatos contendo IDs permanecem ignorados no Git; apenas manifestos e resultados agregados são publicados.
