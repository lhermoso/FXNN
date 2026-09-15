# session_stability_v1 — resultados de estabilidade e observabilidade

**Há mudança de distribuição, associações familiares instáveis e diferenças
pré-entrada entre conclusivos e censurados. Não há mecanismo causal exclusivo
identificado nem contribuição preditiva estável demonstrada.**

Pré-registro/configuração/código: `2f13983`, commit anterior aos cálculos reais.
Execução única concluída sem falhas; reprodução integral dos agregados em outro
processo, sem ajustes, produziu relatório idêntico. **Zero novos fits de pesquisa;
ledger permanece 103/1.000, byte a byte igual.** Artefatos anteriores preservados.

## 1. Que mudanças de distribuição foram observadas?

As oito features de volatilidade/amplitude têm médias menores nos três externos,
nos três universos, tanto contra treino ponderado quanto uniforme. Distribuição
também fica menos dispersa. Q2 combina essa mudança com forte alteração de
horário; Q3/Q4 não repetem a mesma magnitude de deslocamento em `hour_sin`.

Tabela: `volatility_240`, em unidades do desvio populacional do respectivo treino.
W = unicidade usada no ajuste; U = treino uniforme. Avaliação sempre uniforme.
Caudas W = fração estritamente fora de q05–q95 do treino ponderado, não teste
estatístico. Não comparar universos como ranking de estratégia.

| Externo | Universo | Δmédia W | Δmédia U | σ avaliação/σ treino W | Caudas W |
|---|---|---:|---:|---:|---:|
| 2023Q2 | temporal | -1.128 | -0.902 | 0.204 | 53.7% |
| 2023Q2 | 0.0005 | -1.096 | -1.069 | 0.254 | 42.7% |
| 2023Q2 | 0.001 | -1.107 | -1.104 | 0.253 | 45.8% |
| 2023Q3 | temporal | -0.877 | -0.665 | 0.384 | 28.9% |
| 2023Q3 | 0.0005 | -0.716 | -0.735 | 0.479 | 16.6% |
| 2023Q3 | 0.001 | -0.707 | -0.747 | 0.495 | 15.8% |
| 2023Q4 | temporal | -0.767 | -0.521 | 0.432 | 24.2% |
| 2023Q4 | 0.0005 | -0.563 | -0.582 | 0.543 | 10.8% |
| 2023Q4 | 0.001 | -0.536 | -0.578 | 0.572 | 9.9% |

No temporal, `range_pips_240` desloca −1,338/−1,018/−0,865 σ de treino W em
Q2/Q3/Q4. `hour_sin` desloca +1,373/+0,153/+0,028 σ. Em Q2, desvio de
`hour_sin` cai para 0,352 do treino W; isso descreve concentração no ciclo
horário, sem identificar sozinho quais intervalos de hora a produziram.

Movimento e posição têm deslocamentos de média temporal menores: em módulo,
até 0,066 e 0,106 σ W, respectivamente, nesses externos. Isso não demonstra
estabilidade de sua associação com y. Na trajetória, `efficiency_240` desloca
−0,134/−0,245/−0,287 σ W; usando treino U, +0,178/+0,040/−0,020.
Logo, parte do contraste depende materialmente de qual distribuição de treino
serve de referência. Não equivale a provar que pesos causaram erro preditivo.

**Limite:** drift de volatilidade também existe em Q3, único externo em que as
logísticas CUSUM superaram a constante própria. Portanto, drift marginal não
explica sozinho o sinal da diferença de score. Não há p-valores, IC ou limiar
pós-hoc de “drift significativo”. Todas as 28 features, duas referências e seis
fases estão nas evidências; médias/desvios/quantis completos no relatório local.

## 2. Quais contribuições familiares têm associação instável?

Associação abaixo = média da contribuição no logit entre y=1 menos média entre
y=0, na avaliação não ponderada. Positivo significa contribuição maior entre
positivos observados; não é coeficiente causal nem retorno. Cada trimestre usa
modelo/scaler previamente exportado do respectivo passado: variações misturam
mudança de população e diferenças entre modelos, sem novo ajuste nesta tarefa.

T = logística temporal em universo temporal; E5/E10 = CUSUM original nos
universos 0.0005/0.001; L5/L10 = respectivas versões com L2 equivalente.
Temporal nas entradas CUSUM também foi diagnosticado e está integralmente nas
evidências, sem mudar pareamentos.

| Modelo | Família | Q2 | Q3 | Q4 |
|---|---|---:|---:|---:|
| T | movement | -0.002452 | +0.001124 | -0.000730 |
| T | volatility | +0.002702 | +0.003150 | -0.003888 |
| T | position | +0.016903 | -0.008727 | +0.000022 |
| T | path | -0.046941 | +0.002617 | +0.001439 |
| T | context | -0.040356 | +0.033571 | -0.018943 |
| E5 | movement | -0.004254 | +0.001547 | -0.001956 |
| E5 | volatility | +0.002654 | +0.006905 | -0.006888 |
| E5 | position | +0.014024 | -0.012073 | +0.001510 |
| E5 | path | -0.043229 | +0.002887 | -0.000770 |
| E5 | context | -0.042258 | +0.032394 | -0.024631 |
| L5 | movement | -0.004255 | +0.001547 | -0.001958 |
| L5 | volatility | +0.002653 | +0.006908 | -0.006892 |
| L5 | position | +0.014031 | -0.012076 | +0.001510 |
| L5 | path | -0.043240 | +0.002888 | -0.000770 |
| L5 | context | -0.042260 | +0.032391 | -0.024630 |
| E10 | movement | -0.002441 | +0.001585 | -0.002495 |
| E10 | volatility | +0.001598 | +0.004535 | -0.006973 |
| E10 | position | +0.038401 | -0.021472 | +0.002610 |
| E10 | path | -0.049456 | +0.014040 | -0.003261 |
| E10 | context | -0.030649 | +0.025741 | -0.019720 |
| L10 | movement | -0.002442 | +0.001590 | -0.002507 |
| L10 | volatility | +0.001591 | +0.004536 | -0.006982 |
| L10 | position | +0.038555 | -0.021533 | +0.002619 |
| L10 | path | -0.049573 | +0.014096 | -0.003272 |
| L10 | context | -0.030660 | +0.025737 | -0.019686 |

- **Contexto:** negativo→positivo→negativo em todos os pareamentos. Diferença
  entre classes é positiva em seus treinos ponderados. Padrão externo contradiz
  estabilidade dessa associação; não identifica qual feature de contexto causa isso.
- **Volatilidade:** positivo em Q2/Q3, negativo em Q4. Treino ponderado Q4 é
  positivo. Em Q2, associação positiva não impede contribuição ruim para LL:
  nível e dispersão da probabilidade também importam.
- **Posição:** positivo→negativo→positivo (temporal Q4 quase zero). Já no treino,
  contraste ponderado é positivo e uniforme negativo nos três refits dos modelos
  apresentados. Pesos mudam a associação descritiva de referência.
- **Movimento:** negativo→positivo→negativo nas logísticas CUSUM; magnitudes
  pequenas, sem precisão inferencial estabelecida. Temporal em h=0.001 tem sinais
  diferentes, explicitados na evidência: nenhum padrão universal forçado.
- **Trajetória:** negativo em Q2, positivo em Q3; em Q4 fica negativo nas
  logísticas CUSUM e positivo no temporal em universo temporal. Associação e
  benefício de remoção não têm correspondência obrigatória.

Q1 interno também não oferece validação estável: no temporal todas as cinco
associações são negativas; nas logísticas CUSUM originais somente trajetória é
positiva. Internos Q3/Q4 repetem Q2/Q3 externos; não contam como replicações.

### Remoção individual congelada: todos os grupos

ΔLL = LL sem aquela família − LL original; negativo indica menor loss após
perturbação naquele conjunto. Não escolher famílias a partir da tabela.
Brier completo, médias/desvios por classe e quantis constam no relatório/evidência.

| Modelo | Família removida | ΔLL Q2 | ΔLL Q3 | ΔLL Q4 |
|---|---|---:|---:|---:|
| T | movement | -0.000494 | +0.000205 | -0.000319 |
| T | volatility | -0.016813 | +0.000676 | -0.008883 |
| T | position | +0.001955 | -0.001784 | -0.000193 |
| T | path | -0.008134 | +0.000045 | +0.002518 |
| T | context | -0.030018 | +0.005086 | -0.004789 |
| E5 | movement | -0.000819 | +0.000327 | -0.000527 |
| E5 | volatility | -0.000590 | -0.000118 | -0.008523 |
| E5 | position | +0.002785 | -0.002423 | +0.000214 |
| E5 | path | -0.003794 | +0.000210 | +0.000081 |
| E5 | context | -0.013276 | +0.005293 | -0.004930 |
| L5 | movement | -0.000819 | +0.000327 | -0.000527 |
| L5 | volatility | -0.000590 | -0.000118 | -0.008527 |
| L5 | position | +0.002786 | -0.002423 | +0.000214 |
| L5 | path | -0.003795 | +0.000210 | +0.000082 |
| L5 | context | -0.013278 | +0.005293 | -0.004930 |
| E10 | movement | -0.000869 | +0.000357 | -0.000602 |
| E10 | volatility | -0.000701 | -0.000059 | -0.006308 |
| E10 | position | +0.005261 | -0.003613 | +0.000890 |
| E10 | path | -0.003181 | +0.003441 | +0.000587 |
| E10 | context | -0.008196 | +0.004452 | -0.003970 |
| L10 | movement | -0.000870 | +0.000359 | -0.000603 |
| L10 | volatility | -0.000707 | -0.000061 | -0.006314 |
| L10 | position | +0.005285 | -0.003617 | +0.000906 |
| L10 | path | -0.003185 | +0.003462 | +0.000594 |
| L10 | context | -0.008194 | +0.004452 | -0.003963 |

Contexto contribui para pior LL em Q2/Q4 e melhor LL em Q3 em todos os
pareamentos. Volatilidade é desfavorável em Q4; no temporal, removê-la reduz LL
em 0,008883 e Brier em 0,002914. Esses achados localizam incompatibilidades no
modelo congelado; **não autorizam remover grupos ou testar modelo resultante**.

Zero padronizado corresponde à média ponderada do treino de cada modelo.
Intercepto, coeficientes e scaler foram preservados. LL/Brier não são aditivos:
deltas individuais não somam uma decomposição exata da loss. Features
correlacionadas tornam atribuição não exclusiva. Nenhuma remoção combinada,
inversão de sinal, seleção ou estratégia foi executada.

## 3. Que diferenças pré-entrada existem entre conclusivos e censurados?

Comparação principal inclui somente histórico causal válido, separando censura
de ambiguidade/boundary e falta de histórico. Corte estrito `info_ends < fim do
trimestre`, nunca baseado no fim realizado da operação. Retidos coincidiram
exatamente com identidades das avaliações anteriores de cada universo.

“All” abaixo significa todos os candidatos após corte, inclusive histórico
inválido/ambíguos/boundary. “Par válido” = conclusivos válidos + censurados válidos.
Taxas têm denominadores diferentes; não houve recuperação de dados ausentes.

| Trimestre | Universo | Todos após corte | Retidos/conclusivos válidos | Censurados válidos | Censura/all | Censura/par válido |
|---|---|---:|---:|---:|---:|---:|
| 2023Q1 | temporal | 154,608 | 105,770 | 16,208 | 25.29% | 13.29% |
| 2023Q1 | 0.0005 | 11,420 | 8,152 | 1,194 | 23.26% | 12.78% |
| 2023Q1 | 0.001 | 3,852 | 2,848 | 374 | 21.03% | 11.61% |
| 2023Q2 | temporal | 123,894 | 14,964 | 38,212 | 74.84% | 71.86% |
| 2023Q2 | 0.0005 | 5,690 | 742 | 2,178 | 77.15% | 74.59% |
| 2023Q2 | 0.001 | 1,682 | 236 | 650 | 76.75% | 73.36% |
| 2023Q3 | temporal | 159,438 | 106,339 | 24,393 | 27.24% | 18.66% |
| 2023Q3 | 0.0005 | 7,704 | 5,267 | 1,351 | 27.89% | 20.41% |
| 2023Q3 | 0.001 | 2,484 | 1,733 | 429 | 26.61% | 19.84% |
| 2023Q4 | temporal | 175,406 | 164,679 | 7,302 | 4.39% | 4.25% |
| 2023Q4 | 0.0005 | 9,258 | 8,651 | 494 | 5.43% | 5.40% |
| 2023Q4 | 0.001 | 3,012 | 2,834 | 152 | 5.15% | 5.09% |

No temporal, após corte, Q2 ainda contém 16.204 conclusivos sem histórico e
54.514 censurados sem histórico. Esses candidatos são contados, sem imputação.
Q4 contém 2.987 conclusivos sem histórico, 391 censurados sem histórico e
47 ambíguos com histórico; nenhum deles foi incorporado ao par principal.
Tabela outcome × histórico e exclusões pelo horizonte completa nas evidências.

Diferenças abaixo = média censurados válidos − média conclusivos válidos,
dividida por σ do passado de treino W do mesmo trimestre/universo. As features
foram calculadas só com informação disponível antes da entrada.

| Trimestre | Universo | volatility_240 | range_pips_240 | hour_sin | weekday_sin |
|---|---|---:|---:|---:|---:|
| 2023Q1 | temporal | -0.216 | -0.238 | +0.762 | -0.228 |
| 2023Q1 | 0.0005 | -0.391 | -0.394 | +0.862 | -0.207 |
| 2023Q1 | 0.001 | -0.450 | -0.432 | +0.889 | -0.251 |
| 2023Q2 | temporal | +0.125 | +0.188 | -0.308 | -0.151 |
| 2023Q2 | 0.0005 | +0.121 | +0.188 | -0.262 | -0.120 |
| 2023Q2 | 0.001 | +0.111 | +0.171 | -0.236 | -0.077 |
| 2023Q3 | temporal | +0.132 | +0.176 | +0.129 | -0.645 |
| 2023Q3 | 0.0005 | +0.057 | +0.084 | +0.301 | -0.707 |
| 2023Q3 | 0.001 | +0.034 | +0.068 | +0.357 | -0.692 |
| 2023Q4 | temporal | +0.232 | +0.338 | -0.526 | -1.362 |
| 2023Q4 | 0.0005 | +0.199 | +0.331 | -0.504 | -1.321 |
| 2023Q4 | 0.001 | +0.175 | +0.287 | -0.454 | -1.323 |

**Observação:** censurados válidos têm volatilidade/amplitude de 240 observações
maiores em Q2/Q3/Q4, mas menores em Q1, nos três universos. Diferença de
`hour_sin` também muda de sinal. `weekday_sin` difere nos quatro trimestres,
particularmente Q4; estatística cíclica não identifica sozinha dia específico.
Não há assinatura fixa de censura válida para todos os períodos e features.

**Inferência limitada:** conjunto avaliado é seletivo em características
observáveis antes da entrada. Isso dá sustentação empírica à preocupação com
seleção por observabilidade; não mostra a prevalência dos censurados nem prova
que seleção causou a inversão das associações familiares. Não se estimou modelo
de censura, correção de pesos ou y ausente. Todas as 28 features, inclusive
pequenas diferenças/ausência de padrão, foram mantidas nas evidências.

## 4. Mecanismos: o que ganhou ou perdeu sustentação?

| Hipótese | Leitura sustentada pelos diagnósticos | O que continua sem identificação |
|---|---|---|
| Distribuição de X mudou | Sustentada: volatilidade/amplitude e contexto variam; pesos afetam referência. | Drift marginal não explica sozinho falhas, pois Q3 também mudou e teve ganho frente à constante. |
| Associações familiares estáveis | Enfraquecida: sinais variam entre externos e contra treino; contexto é exemplo claro. | Não prova ausência universal de sinal nem permite selecionar famílias. |
| Seleção por observabilidade é irrelevante | Enfraquecida: conclusivos/censurados válidos diferem em X pré-entrada. | Regime, calendário de disponibilidade, duração de trajetórias e censura continuam confundidos. |
| Pesos contribuem para discrepâncias | Compatível: referências W/U e associação de posição diferem no mesmo treino. | Nenhum controle de pesos ou novo fit; não há efeito causal estimado. |
| Diferença de L2 explica ganho CUSUM | Continua enfraquecida pelos controles anteriores; diagnósticos original/equivalente semelhantes. | Não extrapolar para outras configurações ou geometria de scaler. |
| Prior sozinho explica tudo | Continua sem sustentação como explicação exclusiva pelo teste anterior. | Nível/dispersão, prior, X e pesos interagem; remoção familiar não separa essas parcelas. |

**Não há diagnóstico causal claro e exclusivo.** Há três fatos simultâneos:
distribuição muda, associação muda, observabilidade seleciona. Desenho não
quantifica quanto cada mecanismo produz do padrão de scores. Q2 não foi
excluído; Q4 tem censura muito menor e ainda mostra inversões/desvantagens.

Especulação ainda não testada: gaps podem preservar trajetórias curtas até SL
e censurar outras mais longas; padrões de disponibilidade podem coincidir com
mudanças de regime. Este diagnóstico não observa desfechos ausentes e não
separa essas hipóteses. Nenhum experimento adicional foi executado para buscar
explicação melhor. Qualquer proposta futura exige novo pré-registro e autorização.

## Verificação, artefatos e limites

- 20 logísticas únicas reabertas, 12 treinos únicos, 18 pares de distribuição,
  42 avaliações de modelos e 12 estratos de observabilidade.
- **628.378 probabilidades persistidas reproduzidas exatamente** por inferência
  matricial. Soma de famílias reconstruiu logits com erro máximo 4,45e−16 e
  probabilidades com erro máximo 1,67e−16, abaixo da tolerância 1e−12.
- **1.105.737 × 28 features reconstruídas exatamente**; máscaras CUSUM e
  histórico conferidos em todos os 1.384.174 candidatos. 158.720 candidatos
  sem histórico, no desenvolvimento completo, ficaram com X indisponível;
  essa contagem global não é denominador dos trimestres após corte.
- 139 testes passaram; `git diff --check` passou. Testes históricos usam apenas
  fixtures sintéticas; runner bloqueou treinamento/rotulação/escrita nos insumos.
- Relatório persistido reproduzido integralmente em processo novo. Todos os
  hashes congelados, fontes 2022–2023 e ledger foram verificados antes/depois.
- Externos vistos continuam exploratórios. Sobreposição e poucos regimes
  impedem converter quantidade de linhas em precisão estatística. Sem p-valores
  ingênuos, confirmação 2024, execução 2025/#6–#9, merge ou alegação de lucro.

[Protocolo](session-stability-v1-protocol.md),
[configuração](../../configs/session_stability_v1.json),
[runner](../../fxnn/session_stability.py),
[evidência compacta de todos os contrastes principais](session-stability-v1-evidence.json).
Evidência usa tabelas com colunas declaradas, sem arredondar floats. Quantis e
resumos completos de treino/classes/unidades originais ficam no relatório local
verificado, sem dados brutos, modelos ou previsões no Git.

Artefatos completos:
`/Users/leohermoso/FXNN-trading-clock/output/session_stability_v1/`:
`report.json`, `verification.json`, `run.json`.

SHA-256 do relatório:
`977737df1ea2b53db912bdf91278c89b368652728f37602df44582168174df5a`.
Ledger preservado:
`3e9ed64b3307b346e0108e8710ceb8031d93645b4504065f5de6ef76f058a2d1`.

Comandos executados após commit do pré-registro:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.session_stability
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.session_stability --verify
```

`--verify` reproduz somente diagnóstico congelado; não treina. Runner rejeita
criar execução sobre diretório existente.
