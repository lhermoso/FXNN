# Registro de decisões

| Decisão | Motivo |
|---|---|
| Repositório privado, dados fora do Git | Preservar pesquisa e evitar distribuir arquivos de terceiros |
| Python; core de labels sem dependências | Referência simples, verificável e reproduzível |
| NumPy + scikit-learn opcionais para pesquisa | Baseline tabular suficiente antes de redes neurais |
| TP 50 / SL 20 / <72h | Primeiro contrato de rotulação pedido pelo usuário |
| Descartar ambíguos | Ordem intrabar desconhecida não vira label inventado |
| Quarentena de horários duplicados | Não corrigir feed adivinhando |
| Hard negatives preservados como negativos | Alvo posterior não apaga stop já executado |
| Todas as classes conclusivas no treino | Evitar conjunto artificial de vencedoras ideais |
| Seleção de features interna ao fold | Reduzir vazamento de informação de avaliação |
| Nenhum resultado financeiro no primeiro baseline | Censura, custos e execução ainda não resolvidos |

Data inicial: 2026-09-13 UTC. Decisões novas devem registrar motivo e impacto;
mudanças de metodologia exigem novo identificador de experimento.
