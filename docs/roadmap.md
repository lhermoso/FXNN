# Roadmap da pesquisa FXNN

## Conclusão da sequência

**Promoção econômica rejeitada; esta configuração fica arquivada sem promoção
à execução real.** A sequência implementou dados auditáveis, features causais,
validação temporal, controles, replay e simulação bid/ask. Não demonstrou uma
estratégia rentável. Ganhos pontuais de classificação não autorizam seleção
retrospectiva de uma técnica vencedora.

No desenvolvimento de #9, nenhuma das 131.064 probabilidades disponíveis
atingiu 0,5: filtro sem operações e PnL zero. Na confirmação única 2024, uma
operação filtrada perdeu 2,95/2,97/3,10 USD em S0/S1/S2; Q1–Q3 continuaram sem
operações. Os critérios exigem PnL estritamente positivo. O primário permaneceu
com PnL/drawdown conclusivos indisponíveis por lacunas. P1 é cenário contrafactual,
não resgate da evidência P0. Não houve ajuste após abertura.

Execução científica e replay concluídos, guard terminal `COMPLETED`. Aceite e
integração GitHub são acompanhados no PR #24 e nas issues #9/#3.

## Entregas e resultados

| Etapa | Evidência e conclusão |
|---|---|
| Implementação inicial e [AFML/FFD](experiments/afml-v1.md) | Features causais, unicidade e expurgo; ganhos inconsistentes entre externos. Experimentos históricos e seus contratos permanecem preservados. Não reabrir busca de d. |
| [#4: dados e reserva](experiments/multiyear-v1-protocol.md) | Desenvolvimento 2022–2023 e confirmação histórica 2024 separados antes da sequência. Inspeções anteriores de 2025 não o tornam um holdout intocado. |
| [#5 e continuação CUSUM](experiments/cusum-temporal-v2.md) | Melhorias descritivas frente à logística temporal não persistiram frente à constante de forma estável. O piso operacional inicial não demonstrou ausência de sinal. CUSUM e temporal permanecem linhas exploratórias, sem escolha pelo externo. |
| [MLP CUSUM](experiments/mlp-cusum-v1.md) e [orçamento Adam igual](experiments/mlp-adam-budget-v1.md) | Ganho descritivo inicial não persistiu com orçamento de updates igual; todas MLPs perderam para constante nos externos. Não extrapolar para outras seeds ou arquiteturas. |
| [Reconstrução de sessão](experiments/session-dataset-v1.md), [modelos](experiments/session-models-v1.md) e [controles](experiments/session-controls-v1.md) | Calendário e histórico observado recuperaram elegibilidade sem preencher preços. Q2 continuou frágil; nenhum modelo superou consistentemente a constante. L2 equivalente não explicou materialmente o ganho CUSUM nesta configuração. |
| [#6: barreiras por volatilidade](experiments/volatility-barriers-v1.md) | Comparação inconclusiva: Q2 quase sem suporte, melhora descritiva em Q3 e piora em Q4. Tarefas fixa/dinâmica não podem ser ranqueadas por LL bruto. A dinâmica seguiu por regra prévia. |
| [#7: primário/meta-filtro](experiments/meta-primary-v1.md) | LL/Brier melhores em Q3 e piores em Q4. Threshold indisponível em Q3 não equivale a rejeitar todos os sinais; precisão condicional maior em Q4 veio com menor recall/F1. Nenhuma prova econômica. |
| [#8: bagging](experiments/sequential-bagging-v1.md) | Bootstrap sequencial sem ganho consistente nas duas seeds; CUSUM inconclusivo por Q2 vazio. Não selecionar seed/população nem confundir diversidade com generalização. |
| [#19: aquisição bid/ask](experiments/histdata-ticks-v1.md) | 24 meses 2022–2023 adquiridos; 60.631.004 registros, incluindo 7.182 retrocessos de timestamp preservados. Aquisição íntegra não prova observabilidade econômica adequada. |
| [#9: economia e confirmação](experiments/economic-ticks-v1.md) | 12 carteiras em cada janela, custos e incerteza explícitos. Desenvolvimento sem operações filtradas; confirmação 2024 com uma operação e perda nos três custos. Primário inconclusivo. Promoção rejeitada nas duas janelas. |

Cada etapa separou mudanças de dados, eventos, labels, regra primária e amostragem. Dependências eram de conclusão metodológica, não de resultado positivo. Árvores, MDI, grupos aprendidos e outras ideias genéricas do roadmap anterior não foram executadas por esta sequência; não constituem tarefas automaticamente autorizadas nem parte da confirmação congelada.

## O que #9 mediu no desenvolvimento

O dataset contém 748.920 oportunidades em 2022–2023 e 692.209 barras observadas. Os rótulos de candidatos são 83.575 TP, 280.618 SL e 384.727 indisponíveis; candidatos sobrepostos não são retornos de carteira.

As 12 carteiras receberam as mesmas 280.920 oportunidades externas de abril a dezembro de 2023, com continuidade em nove checkpoints mensais. A disponibilidade de inputs completos foi 31 linhas em Q2, 49.256 em Q3 e 81.777 em Q4. O modelo estava disponível em todos os folds; falta de probabilidade por linha resulta de inputs causais indisponíveis, não de ausência do modelo. Q2 tem somente quatro labels diagnosticáveis, todos negativos.

O filtro fez zero operações em todos os custos/políticas/trimestres. O primário P0 entrou duas vezes: uma saída por stop e uma exposição inconclusiva por lacuna, mantida até o fim. Seus PnL/drawdown conclusivos são indisponíveis, não zero. P1 realizou liquidações contrafactuais após incerteza; não reconstrói o percurso não observado, não é limite inferior e não resgata P0.

O desenvolvimento usou oito fits novos e os modelos finais dois: dez dos 14 slots reservados, com reuso de contratos idênticos. O ledger registrado antes do encerramento era 301/1.000. Os modelos finais usaram 364.061 exemplos após expurgo/buffer. Isso não autoriza utilizar slots remanescentes para variantes.

A falha de serialização na publicação foi corrigida de forma explícita [após os resultados](experiments/economic-ticks-v1-publication-recovery.md). Os 62 caminhos científicos originais e S/F permaneceram idênticos. Replays de modelos/probabilidades e das 12 carteiras passaram sem novos fits, com ledger/estado/manifests byte-idênticos; o relatório reconstruído também coincidiu. Essa correção precedeu a revisão completa do release; seus controles isolados não
substituíram os oito critérios de prontidão para abertura.

## Confirmação única e encerramento

Release congelado `cac434dd2a2cf9bcb38ec33bca6b0dcba0d3f951`: revisão completa
aprovada sem achados e [CI executada](https://github.com/lhermoso/FXNN/actions/runs/35046993074).
Pacote P `c7aeb1e50de5abdcb33a56f35f1e2a43b590b25db910ca6aa759bc61f6e65aa1`,
ligando código científico S, fits/modelos F, release R e recibos originais.
Publicador de frações exatas explicitamente ligado ao pacote, sem alterar
os 62 arquivos científicos do pré-registro. Congelamento precedeu aquisição 2024
e selou a única reserva contra novos fits.

2024 contém 377.280 oportunidades e 315.872 probabilidades disponíveis. Um único
sinal atingiu 0,5 e virou operação; os 12 cenários processaram o ano e seus quatro
trimestres. Há 207.805 labels diagnosticáveis e 96.479 censuras por ausência de
cotação. Disponibilidade do arquivo e execução técnica completa não garantem
observabilidade econômica. [Relatório final](experiments/economic-ticks-v1.md),
[agregados](experiments/economic-ticks-v1-final-aggregates.md) e
[CSV](experiments/economic-ticks-v1-final-aggregates.csv) preservam todos os cenários,
perdas, bloqueios, ausência de operações e incerteza.

Guard terminal `COMPLETED`, reserva selada, replay integral de confirmação e
desenvolvimento aprovado e relatório reconstruído idêntico. 301/1.000 fits globais;
nenhum ajuste na confirmação. O fechamento acrescentou apenas `run_finished`,
preservando o prefixo do ledger; SHA-256 final `a7cac20a864602ad4ffd5a9dbb9587fbd8a93b3249cf78957d6a47a0780374f1`.

Abertura única, sem refit, recalibração ou escolha de threshold/seed após 2024.
Essa confirmação está consumida. O SHA posterior de documentação/resultados
não substitui R nem reabre o pacote. Integração e aceite do backlog são
acompanhados no [PR #24](https://github.com/lhermoso/FXNN/pull/24),
[issue #9](https://github.com/lhermoso/FXNN/issues/9) e
[roadmap #3](https://github.com/lhermoso/FXNN/issues/3); não se presume merge ou
fechamento do GitHub a partir da conclusão local.

## Limites e direção futura

Custos/funding são cenários hipotéticos congelados; execução depende do feed e de hipóteses de liquidez. Nenhum estudo desta sequência autoriza ordens reais ou alegação de rentabilidade implementável. Não há nova execução de 2025.

A configuração econômica registrada não está promovida. Preservar resultados negativos, código e trilhas permite arquivar essa hipótese específica sem promoção e manter pesquisa exploratória sem fingir validação. Uma hipótese nova exigirá protocolo e confirmação próprios; não reutilizar 2024 para seleção nem iniciar busca até encontrar lucro. CUSUM, redes ou outras técnicas não são universalmente refutados por esses resultados.
