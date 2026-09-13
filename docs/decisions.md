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

## 13/09/2026 — ampliação temporal

Léo fixou 2022–2023 para desenvolvimento e 2024 como confirmação histórica
reservada antes dos novos labels. 2025 permanece exploratório. Treino para
confirmar 2024 deve usar somente passado anterior a 2024; conhecimento prévio
de 2025 impede alegar confirmação prospectiva independente. Critérios e
procedimento final devem ser versionados antes de abrir confirmação.
Detalhes: [multiyear_v1](experiments/multiyear-v1-protocol.md).

Triagem de cobertura não altera labels: candidatos a fechamento não são
fechamentos confirmados. Preservar lacunas e exigir bid/ask para validação
econômica. [Evidência e pendências](data-coverage.md).

## 13/09/2026 — fechamento exploratório de dados (#4)

Contrato `configs/multiyear_v1.json`: três folds trimestrais em 2023, treino desde
2022, pisos de 1.000 linhas/100 por classe, até 1.000 ajustes nas próximas etapas.
Censurar toda lacuna e reiniciar histórico; nenhuma promoção de fim de semana
candidato a fechamento confirmado. Isso permite exploração condicionada a
conclusivos, mantendo bloqueio econômico e confirmação 2024 fechada. Novos
runners devem usar `fxnn.protocol`; calendários de experimentos antigos não mudam.
