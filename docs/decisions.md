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

## Após merge do PR #12 — manter CUSUM como linha ativa

Léo decidiu manter CUSUM em pesquisa, inclusive em paralelo ao baseline temporal.
O encerramento de `cusum_v1` não exclui a hipótese nem justifica promover somente
o baseline às pesquisas seguintes. Nenhum modelo foi ajustado nessa execução.

Os pisos de 1.000 candidatos e 100 por classe foram escolhidos pelo agente na #4
como regras operacionais, sem cálculo de poder estatístico apresentado. A parada
com 624 candidatos/40 positivos na validação interna de abril–junho de 2023
demonstrou descumprimento dessa regra, não inutilidade científica da amostra.
Também preservar a distinção entre candidatos por lado e eventos distintos.

Manter duas linhas explícitas:

- **Temporal:** treino em todos os candidatos elegíveis, como controle ativo.
- **CUSUM:** treino em candidatos dos eventos causais, como hipótese ativa.

Retomada exige novo identificador e pré-registro, porque suporte e interseção
de `cusum_v1` já foram examinados. Preservar protocolo, resultados, hashes e
ledger da execução encerrada; não editar seu histórico para remover a parada.
Revisar os critérios de suporte com justificativa ligada ao modelo e à incerteza
das estimativas, sem reutilizar automaticamente 1.000/100 como veto à pesquisa.
Não basta substituir esses números por outro piso arbitrário.

A interseção entre limiares também é decisão de desenho a revisar: manter CUSUM
não exige que uma interseção escassa encerre todas as linhas. Comparações entre
modelos devem continuar usando as mesmas identidades de avaliação; métricas de
populações distintas serão apresentadas separadamente. Congelar o desenho antes
de novos ajustes e explicitar que revisão usa conhecimento da auditoria anterior.

Desenvolvimento continua em 2022–2023, confirmação 2024 fechada, sem 2025.
Manter causalidade, expurgo, buffer, política de lacunas e ledger global de ajustes.
Manter duas linhas não autoriza abrir confirmação duas vezes nem escolher uma
vencedora retrospectivamente. O resultado anterior permanece inconclusivo, e
nenhuma nova execução foi realizada ao registrar esta decisão.

## Continuação após PRs #12/#13 — cusum_temporal_v2

[Pré-registro](experiments/cusum-temporal-v2-protocol.md) substitui apenas nesta
continuação a guarda operacional 1.000/100 por condições técnicas explícitas,
sem alegar poder estatístico. Dois limiares fixos, avaliações pareadas separadas,
sem seleção entre populações. Histórico multiyear_v1/cusum_v1 preservado.
[Execução](experiments/cusum-temporal-v2.md): 24 ajustes, total 24/1.000.
Ambos CUSUM melhoram log-loss sobre logística temporal nos três externos;
ambos perdem para constante em Q2/Q4. Ganho descritivo não estabelece
superioridade inferencial nem lucro. Temporal e CUSUM seguem ativos;
2024 fechado, nenhum 2025 ou avanço para #6–#9.

## Após PR #14 — mlp_cusum_v1

[Comparação exploratória executada](experiments/mlp-cusum-v1.md): arquitetura
fixa MLP 28→16→1, seed 0, 20 épocas, treino temporal e eventos nos dois limiares.
12 ajustes únicos; controles v2 reutilizados por contrato/hashes/identidades,
sem repetir refits como internos. Global 36/1.000, saldo 964.
CUSUM preservou ganho descritivo sobre MLP temporal; nenhuma MLP superou constante
nos externos. Arquitetura não melhorou logística consistentemente. Todas MLPs
completaram épocas mas sem estabilização da loss pelo diagnóstico pré-fixado;
nenhuma extensão de treino ou troca de seed. Inferência inconclusiva, linhas
ativas, confirmação 2024 fechada, nenhum uso de 2025 ou execução #6–#9.

## Continuação após PR #15 — orçamento Adam igual

[mlp_adam_budget_v1](experiments/mlp-adam-budget-v1.md): 9.580 atualizações por
ajuste, derivadas do maior treino temporal anterior sem scores. 12 ajustes novos,
global 48/1.000, saldo 952. Com orçamento igual, MLP eventos melhora temporal
somente Q2; perde Q3/Q4 nos dois limiares. Ganho descritivo anterior não persistiu.
Todas MLPs perdem para constante em LL/Brier externos. Eventos atingiram diagnóstico
de estabilização de loss; temporais não, sem prova de convergência. Igualar updates
não iguala exposição ou regularização efetiva. Inferência inconclusiva, linhas
ativas, 2024 fechado, nenhum 2025 ou #6–#9. Histórico preservado.
