# Metodologia de pesquisa

Atualização de 14/09/2026: a reconstrução [session_dataset_v1](experiments/session-dataset-v1-protocol.md)
usa 72 horas de mercado aberto, ignora gaps de até 14 minutos de sessão e
censura a partir de 15. Features passam a contar candles observados, sem fill.
Essa versão substitui o contrato de dados para a próxima pesquisa; as regras
e resultados históricos abaixo continuam documentando as versões anteriores.

## Objetivo e hipótese

Estimar, antes de uma entrada, probabilidade de TP 50 pips ocorrer antes de SL
20 pips em menos de 72 horas. R:R planejado 2,5:1, sem confundir com percentual
de risco sobre patrimônio. Valor preditivo precisa existir fora da amostra;
rotulação retrospectiva e seleção ótima não demonstram uma estratégia lucrativa.

## Dados e rótulos

Ampliação de 13/09/2026: 2022–2024 disponíveis. Labels 2022–2023 foram
auditados após pré-registro, sem treino; 2024 segue sem labels nesta sequência.
[Reserva multiyear_v1](experiments/multiyear-v1-protocol.md): desenvolvimento
2022–2023, confirmação histórica 2024, 2025 exploratório. Protocolo operacional
deve ser congelado antes de abrir confirmação; não altera experimentos antigos.
[Triagem de lacunas](data-coverage.md) não autoriza mudar censura nem preencher
dados. Bid/ask segue requisito para validação econômica.

Base inicial: HistData EUR/USD M1, ano 2025, bid-only. Horário original EST fixo
convertido para UTC. Arquivo ZIP original, hashes, lacunas e quarentena preservados.
120 linhas de 60 timestamps repetidos foram isoladas, sem inferir horário correto.
Downloads parciais Dukascopy não são misturados à base HistData.

Positivo = TP primeiro e dentro do prazo. Negativo = SL primeiro ou timeout
observado integralmente. Hard negative = SL primeiro, depois TP dentro do prazo
original; isso não muda o PnL nem transforma perda em acerto. Casos ambíguos,
censurados e incertos no prazo são descartados dos datasets, com contagens auditadas.

As 508 vencedoras não sobrepostas são um conjunto retrospectivo de referência.
Treino usa todos os rótulos conclusivos, nunca somente essas 508 ou somente os
35.264 hard negatives. Rótulos sobrepostos não são observações independentes.

## Features causais

Entrada ocorre na abertura do minuto t. Preços usados em features vêm somente
dos candles fechados até t−1. Calendário de t e direção proposta são conhecidos.
Sem high, low, close, resultado, duração ou alvo posterior do próprio trade.

Primeiro conjunto, limitado deliberadamente:

| Família | Features |
|---|---|
| Movimento | Retornos logarítmicos de 5, 15, 60 e 240 minutos, orientados pela direção |
| Volatilidade | Desvio dos retornos e amplitude média, em pips, nas mesmas janelas |
| Posição | Distância da última cotação à média, normalizada por desvio, orientada pela direção |
| Trajetória | Eficiência direcional em cada janela; corpo/pavios do último candle |
| Contexto | Hora UTC cíclica, dia da semana cíclico, direção proposta |

Janelas exigem sequência M1 contínua. Depois de lacunas, aguardar histórico
suficiente; não preencher retornos inexistentes. Volume HistData não é feature.

## Validação temporal e seleção aninhada

Baseline: regressão logística L2, scaler ajustado exclusivamente em treino.
Pesos por unicidade média dos intervalos dos rótulos, computados somente entre
amostras de treino da divisão. Sem balanceamento artificial de classes.

Protocolo inicial fixado antes de treinar:

1. Três avaliações externas: julho, agosto e setembro de 2025.
2. Para cada avaliação, mês anterior é validação interna; meses anteriores a
   ele são treino interno. Treino usa somente passado.
3. Expurgar treino cujo horizonte conservador de informação (entrada +72h)
   alcance a fronteira de validação. Aplicar buffer adicional de 241 minutos
   antes da fronteira, cobrindo maior histórico usado nas features.
4. Medir importância conjunta por famílias na validação interna, embaralhando
   blocos de linhas consecutivas. Selecionar somente famílias com aumento médio
   positivo de log-loss ao embaralhar; se nenhuma ajudar, usar probabilidade
   constante do treino, sem inventar feature vencedora.
5. Reajustar baseline completo e versão selecionada no passado disponível,
   repetindo expurgo/buffer antes da avaliação externa.
6. Não selecionar features, thresholds, hiperparâmetros ou número de tentativas
   com resultado do mês externo. Relatar também baseline constante.

Esse desenho é walk-forward aninhado com expurgo e buffer, não K-fold aleatório
nem implementação de CPCV. Não existe treino posterior ao teste; embargo clássico
após teste seria relevante se adicionarmos splits bidirecionais/CPCV.

Outubro–dezembro reservados da modelagem inicial. Não são um holdout historicamente
intocado: já examinamos rótulos e estatísticas anuais. Confirmação final exigirá
período novo, idealmente outros anos/regimes ainda não usados na pesquisa.

## Métricas e importância

Relatar log-loss, Brier, average precision, ROC-AUC e precisão/recall em thresholds
fixos 0,3/0,4/0,5. Relatar suporte por classe e pesos. Accuracy não é objetivo.
Importância de permutação agrupada é diagnóstico condicional ao modelo; não prova
causalidade. Blocos não eliminam toda dependência e não geram p-valores válidos.

MDI e SFI entram como comparações futuras; MDI pode favorecer padrões de treino,
SFI pode perder interações. Diferenciação fracionária deve demonstrar ganho sobre
retornos simples; parâmetro d, PCA, clusters e seletores aprendidos sempre dentro
do treino. Não presumir que estacionariedade ou memória impliquem previsibilidade.

## Limites que impedem alegação de lucro

- Bid-only, sem spread, comissão, swaps ou execução real.
- Alto descarte por lacunas: métricas condicionadas a rótulos conclusivos podem
  sofrer viés de seleção. Inferência real não sabe quais entradas serão censuradas.
- Posições e sinais se sobrepõem; precisão por candidato não é retorno de carteira.
- Um ano tem muitos candles, mas poucos regimes independentes.
- Probabilidade logística não foi calibrada separadamente para execução.

Simulação causal com uma posição por vez e tratamento de censura/mercado fechado
é requisito antes de transformar probabilidades em PnL. Não forçar trade diário.

## Referências

- López de Prado, M. (2018), *Advances in Financial Machine Learning*: capítulos
  3–5 (rótulos, pesos, diferenciação), 7–8 (validação e importância), 12 (CPCV).
- [Feature importance, MLFinLab](https://random-docs.readthedocs.io/en/latest/implementations/feature_importance.html).
- [Purging/embargo, MLFinLab](https://random-docs.readthedocs.io/en/latest/implementations/cross_validation.html).
- [Unicidade e sampling](https://random-docs.readthedocs.io/en/latest/implementations/sampling.html).
- [Diferenciação fracionária](https://hudsonthames.org/fractional-differentiation/).
- [HistData: formato e timezone](https://www.histdata.com/f-a-q/).

Agrupamento de importância é extensão discutida no livro posterior *Machine
Learning for Asset Managers*. O baseline aqui é uma escolha do projeto, não uma
reprodução integral do AFML.

## Experimento AFML subsequente

[afml_v1](experiments/afml-v1-protocol.md) preserva o protocolo histórico acima
para research_v1. Na nova comparação, usa interseção de candidatos válidos da
grade fixa de FFD e buffer derivado do maior histórico efetivo (445 minutos).
Escolhe d pela log-loss interna; SFI, ADF e permutação não eliminam features.
[Resultado](experiments/afml-v1.md): sem ganho consistente. Esses diagnósticos
não justificam alterar o universo ou repetir busca nos meses externos já vistos.

[cusum_v1 (#5)](experiments/cusum-v1.md) foi executado somente em 2022–2023:
parada pelo piso operacional registrado, zero ajustes. Redução de redundância
observada não demonstra previsibilidade; tampouco essa parada demonstra ausência
de sinal. Por [decisão posterior de Léo](decisions.md), CUSUM permanece ativo em
paralelo ao controle temporal. O piso 1.000/100 não teve cálculo de poder
estatístico apresentado; sua adequação e a interseção de avaliação serão revistas
em novo protocolo antes de novos ajustes, preservando a execução histórica.
Confirmação 2024 continua fechada.

A [continuação exploratória cusum_temporal_v2](experiments/cusum-temporal-v2-protocol.md)
foi pré-registrada após conhecer suporte de v1: mantém os dois limiares separados,
sem interseção obrigatória ou ranking entre populações. Condições técnicas de
ajuste substituem o veto 1.000/100 somente no novo experimento; métricas pequenas
são relatadas com limitações de precisão/dependência. [Resultados](experiments/cusum-temporal-v2.md):
ganho descritivo contra logística temporal, sem ganho consistente contra constante,
inferência inconclusiva. Nenhuma abertura de 2024 ou uso de 2025.

[mlp_cusum_v1](experiments/mlp-cusum-v1-protocol.md) mantém essas linhas na
arquitetura MLP fixa, com reutilização verificável de controles e de treinos
idênticos entre folds. [Resultado](experiments/mlp-cusum-v1.md): efeito descritivo
CUSUM persistiu, sem melhoria consistente de arquitetura ou ganho sobre constante.
20 épocas completadas sem estabilização da loss; inferência inconclusiva, seed 0
somente. Sem alteração de features/rótulos, abertura de 2024 ou execução #6–#9.

## Controles pareados após reconstrução de sessão

[session_controls_v1](experiments/session-controls-v1.md): 16 ajustes novos,
8 constantes próprias CUSUM e 8 logísticas com C=N_temporal/N_event. Ledger
87→103/1.000. Igualar penalização L2 relativa preservou ganho CUSUM frente à
logística temporal nos três externos, com mudanças mínimas frente ao original;
essa diferença de L2 perdeu sustentação como explicação material do ganho.
Prior próprio piorou Q2 e melhorou Q3/Q4. Logísticas original/equivalente
perderam para constante própria em Q2/Q4 e ganharam só Q3, nos dois h.
Sem contribuição informativa estável demonstrada; inferência continua mista.
Controles anteriores preservados, sem novas buscas, 2024 fechado, nenhum
2025/#6–#9 ou lucro alegado.

## Contrato anterior à reconstrução de sessão — PR #16, orçamento Adam igual

[mlp_adam_budget_v1](experiments/mlp-adam-budget-v1.md): 9.580 atualizações por
ajuste, derivadas do maior treino temporal anterior sem scores. 12 ajustes novos,
global 48/1.000, saldo 952. Com orçamento igual, MLP eventos melhora temporal
somente Q2; perde Q3/Q4 nos dois limiares. Ganho descritivo anterior não persistiu.
Todas MLPs perdem para constante em LL/Brier externos. Eventos atingiram diagnóstico
de estabilização de loss; temporais não, sem prova de convergência. Igualar updates
não iguala exposição ou regularização efetiva. Inferência inconclusiva, linhas
ativas, 2024 fechado, nenhum 2025 ou #6–#9. Histórico preservado.

## Integração e continuação autorizadas em 15/09/2026

Léo autorizou integrar a pesquisa de sessão e executar a sequência restante
#6–#9, substituindo as reservas de autorização dessas etapas. Cada experimento
novo continua exigindo protocolo, configuração e código registrados antes de
abrir novos resultados ou ajustar modelos. Confirmar em 2024 exige congelar
primeiro o pipeline completo e executar uma única avaliação; não retunar depois.
2025 não é necessário à sequência planejada e permanece fora das execuções.

Os protocolos e relatórios históricos acima preservam o escopo de suas datas;
menções a ausência de autorização de merge não descrevem esta autorização nova.
[session_stability_v1](experiments/session-stability-v1.md) permanece congelado,
sem novos fits: mudança de distribuição e associações familiares instáveis,
diferenças pré-entrada entre conclusivos/censurados, sem mecanismo causal
exclusivo nem contribuição preditiva estável demonstrada. Ledger na integração:
103/1.000. Nenhuma evidência de lucro; resultados negativos preservados.

## Etapa 6 — barreiras por volatilidade

[Pré-registro volatility_barriers_v1](experiments/volatility-barriers-v1-protocol.md):
duas tarefas distintas, fixa 50/20 e dinâmica 2,5v/v, no mesmo universo causal
de 2022–2023. Volatilidade diária simples com lag exato de 1.440 minutos abertos,
janela finita de 500 endpoints anteriores e buffer de 1.941 candles observados.
Logística e constante própria por tarefa/população, até 48 fits novos. Nunca
ordenar tarefas por LL bruto. Dinâmica continua mecanicamente em #7, sem seleção
pelos externos; 2024 continua fechado nesta etapa.

[Resultado](experiments/volatility-barriers-v1.md): 38 fits novos, global 141/1.000.
Lacunas frequentes inviabilizaram quase toda elegibilidade diária em Q2: zero
exemplos externos fixos, três dinâmicos temporais e zero CUSUM. Q3 favoreceu
logística descritivamente; Q4 a desfavoreceu em todos pares. Comparação
inconclusiva, sem contribuição preditiva estável ou lucro. Rebuild reproduziu
114 arrays/relatório; replay reproduziu 1.755.074 probabilidades sem novos fits.

Documentos da integração de sessão: [dataset](experiments/session-dataset-v1.md),
[modelos](experiments/session-models-v1.md) e [auditoria](experiments/session-v1-audit.md).

## Etapa 7 — primário determinístico e meta-filtro

[Pré-registro meta_primary_v1](experiments/meta-primary-v1-protocol.md): direção
pelo sinal de close[i−1] versus close[i−61], apenas histórico observado anterior,
sobre tarefa dinâmica congelada. Logística/constante próprias, até 24 novos fits,
buffer 1.941 mantido. Threshold escolhido por F1 interno, sem empréstimo entre
períodos; Q2 sem positivos torna filtro externo Q3 indisponível. Probabilidades e
todas oportunidades causais permanecem visíveis, incluindo futuras censuras e
fim de trimestre. Ausência de decisão não equivale a rejeição. 2024 fechado.

[Resultado da etapa 7](experiments/meta-primary-v1.md): 20 fits novos, global
161/1.000. Meta-modelo melhora LL/Brier em Q3 e piora em Q4; decisão Q3
indisponível por calibração Q2 sem positivos. Maior precisão condicional em Q4
vem com forte perda de recall/F1, sem demonstração de contribuição estável ou
lucro. Replay exato de 41 arrays de projeção e 488.292 probabilidades; resultados
negativos e todas oportunidades preservados.

## Etapa 8 — bootstrap uniforme versus sequencial pré-registrado

O [protocolo sequential-bagging-v1](experiments/sequential-bagging-v1-protocol.md)
compara membros logísticos com pesos unitários por ocorrência, mantendo fonte
unilateral dinâmica, folds, features e universos da etapa 7. Sorteios usam o fim
informacional conservador no relógio aberto; expurgo usa o horizonte completo e
1941 barras de buffer. Dois seeds, três membros e K=512 ficam fixos. Ausência de
classe não permite redraw ou reparo do divisor. O teto é 156 novos fits sobre
161 já consumidos; referências ponderadas são replay, sem fit novo. Pré-registro
não constitui evidência de melhora nem abre confirmação 2024–2025. Resultados
científicos serão registrados depois da execução e replay auditados.

[Resultado da etapa 8](experiments/sequential-bagging-v1.md): 130 fits novos,
ledger 161→291/1.000, todos bem-sucedidos. Sequencial não apresentou ganho
consistente nas duas seeds; temporal teve ΔBrier médio entre folds positivo
em ambas, com Q2 limitado a três negativos. CUSUM permanece inconclusivo
pelo externo Q2 vazio. Q3 preserva probabilidades, mas não decisões calibradas.
Replay integral de sorteios, modelos, predições e relatório passou sem novos
fits nem alteração do ledger. Nenhuma seleção de seed, lucro alegado ou
abertura de 2024/2025.
