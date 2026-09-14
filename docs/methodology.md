# Metodologia de pesquisa

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

## Continuação após PR #15 — orçamento Adam igual

[mlp_adam_budget_v1](experiments/mlp-adam-budget-v1.md): 9.580 atualizações por
ajuste, derivadas do maior treino temporal anterior sem scores. 12 ajustes novos,
global 48/1.000, saldo 952. Com orçamento igual, MLP eventos melhora temporal
somente Q2; perde Q3/Q4 nos dois limiares. Ganho descritivo anterior não persistiu.
Todas MLPs perdem para constante em LL/Brier externos. Eventos atingiram diagnóstico
de estabilização de loss; temporais não, sem prova de convergência. Igualar updates
não iguala exposição ou regularização efetiva. Inferência inconclusiva, linhas
ativas, 2024 fechado, nenhum 2025 ou #6–#9. Histórico preservado.
