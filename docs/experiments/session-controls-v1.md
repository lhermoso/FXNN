# session_controls_v1 — resultados dos controles pareados

**Diferença de L2 perdeu sustentação como explicação material do ganho CUSUM. Prior próprio teve efeito misto. Contribuição informativa estável das features continua sem sustentação.**

Execução única em 14/09/2026. Auditoria anterior registrada separadamente em `ba2368a`; protocolo, configuração, runner e testes registrados antes dos ajustes em `a87521bc59d6ee0a382a7e3b924520cf45757c8d` (também código executado). 16 ajustes novos: 8 constantes e 8 logísticas; zero falhas/retries. Ledger canônico **87 → 103/1.000**, saldo 897. Nenhum controle anterior retreinado.

## Evidência e interpretação

1. **Regularização:** igualar `1/(C·Σw)` ao temporal preservou ganho descritivo CUSUM contra logística temporal nos três externos, em ambos h, com Brier também menor em cada externo. Diferença absoluta máxima de LL versus CUSUM original: 0,000004821; Brier: 0,000001526. Portanto, diferença de força L2 não foi necessária para o ganho observado nesta configuração. Não generalizar para outros C ou confundir igualdade do coeficiente L2 com igualdade da geometria dos scalers.

2. **Prior:** constante própria ficou acima da temporal nos três passados externos. Isso piorou LL/Brier em Q2 e melhorou em Q3/Q4. Prior isolado não reproduz padrão de melhora logística CUSUM nos três externos; em Q2 sua direção é oposta. Pode contribuir para efeitos em Q3/Q4, mas este desenho não estima fração causal do ganho atribuível ao prior.

3. **Features além do prior:** logística CUSUM original e equivalente perdem para constante própria em Q2/Q4, ganham somente em Q3, para ambos h. Critério pré-registrado não foi satisfeito. AUC das logísticas CUSUM permanece abaixo de 0,5 em Q2/Q4. Ganho sobre logística temporal não demonstra ordenação estável das oportunidades nem valor preditivo consistente sobre controle sem features.

**Inferência:** resultados continuam mistos; não identificam mecanismo exclusivo. Mudança de população, pesos, nível/dispersão das probabilidades e regime ainda podem contribuir. **Especulação não testada:** seleção por censura pode distorcer relação entre features e resultado; nenhum novo experimento foi aberto para procurar melhoria.

## LL e Brier externos

Comparações somente dentro do mesmo h, mesmas identidades/y. Menor é melhor. Constantes aprendidas exclusivamente no treino, nunca prevalência externa.

### h=0.0005

| Modelo | Q2 LL / Brier | Q3 LL / Brier | Q4 LL / Brier |
|---|---:|---:|---:|
| Constante temporal | 0.375308459 / 0.101904450 | 0.555954862 / 0.184592368 | 0.626155062 / 0.215864486 |
| Logística temporal | 0.421167290 / 0.120978279 | 0.553828778 / 0.183760154 | 0.639892956 / 0.220322214 |
| Logística CUSUM original | 0.392100738 / 0.108783288 | 0.552789292 / 0.183387253 | 0.639209258 / 0.220120960 |
| Constante própria | 0.377358284 / 0.102688489 | 0.555861481 / 0.184558410 | 0.624498144 / 0.215276851 |
| Logística CUSUM L2 equivalente | 0.392101488 / 0.108783629 | 0.552790741 / 0.183387775 | 0.639214079 / 0.220122467 |

### h=0.001

| Modelo | Q2 LL / Brier | Q3 LL / Brier | Q4 LL / Brier |
|---|---:|---:|---:|
| Constante temporal | 0.382101817 / 0.105013211 | 0.562599316 / 0.187582721 | 0.617548896 / 0.212024425 |
| Logística temporal | 0.421411469 / 0.121530972 | 0.562034100 / 0.187243573 | 0.633341305 / 0.217139519 |
| Logística CUSUM original | 0.397039257 / 0.111129081 | 0.559781814 / 0.186474468 | 0.625144654 / 0.214593401 |
| Constante própria | 0.388560635 / 0.107498586 | 0.562182248 / 0.187429960 | 0.613230858 / 0.210473712 |
| Logística CUSUM L2 equivalente | 0.397037381 / 0.111128494 | 0.559784265 / 0.186475375 | 0.625149346 / 0.214594926 |

## Contrastes externos pré-registrados

Δ = primeiro modelo menos segundo. Critério: LL menor nos três externos e média simples ΔBrier <=0. Internos permanecem diagnósticos, sem novas replicações.

| h | Contraste | ΔLL Q2 | ΔLL Q3 | ΔLL Q4 | Média ΔBrier | Critério |
|---|---|---:|---:|---:|---:|---|
| 0.0005 | Logística CUSUM original − Constante própria | +0.014742454 | -0.003072189 | +0.014711114 | +0.003255917 | Não |
| 0.0005 | Logística CUSUM L2 equivalente − Logística CUSUM original | +0.000000750 | +0.000001449 | +0.000004821 | +0.000000790 | Não |
| 0.0005 | Logística CUSUM L2 equivalente − Logística temporal | -0.029065802 | -0.001038037 | -0.000678877 | -0.004255592 | Sim, descritivo |
| 0.0005 | Logística CUSUM L2 equivalente − Constante própria | +0.014743204 | -0.003070739 | +0.014715935 | +0.003256707 | Não |
| 0.0005 | Constante própria − Constante temporal | +0.002049825 | -0.000093381 | -0.001656918 | +0.000054149 | Não |
| 0.001 | Logística CUSUM original − Constante própria | +0.008478622 | -0.002400434 | +0.011913796 | +0.002264897 | Não |
| 0.001 | Logística CUSUM L2 equivalente − Logística CUSUM original | -0.000001875 | +0.000002451 | +0.000004693 | +0.000000615 | Não |
| 0.001 | Logística CUSUM L2 equivalente − Logística temporal | -0.024374088 | -0.002249835 | -0.008191959 | -0.004571756 | Sim, descritivo |
| 0.001 | Logística CUSUM L2 equivalente − Constante própria | +0.008476746 | -0.002397983 | +0.011918488 | +0.002265512 | Não |
| 0.001 | Constante própria − Constante temporal | +0.006458818 | -0.000417068 | -0.004318038 | +0.000260634 | Não |

## Prior, nível, dispersão e ordenação

Probabilidades abaixo em escala 0–1; σ populacional. Quantis e diagnóstico de todos os modelos/fases nas evidências.

| h | Externo | Prior temporal → próprio | Média logística temporal → CUSUM equivalente | σ temporal → CUSUM equivalente | AUC equivalente | AP equivalente |
|---|---|---:|---:|---:|---:|---:|
| 0.0005 | 2023Q2 | 0.256538 → 0.258674 | 0.294892 → 0.267558 | 0.037679 → 0.027623 | 0.330025 | 0.052090 |
| 0.0005 | 2023Q3 | 0.237411 → 0.240754 | 0.229594 → 0.228669 | 0.028066 → 0.026550 | 0.561851 | 0.297467 |
| 0.0005 | 2023Q4 | 0.228378 → 0.232521 | 0.218502 → 0.222615 | 0.030753 → 0.031517 | 0.447258 | 0.268492 |
| 0.001 | 2023Q2 | 0.256538 → 0.263461 | 0.291141 → 0.268081 | 0.040763 → 0.025581 | 0.384914 | 0.064061 |
| 0.001 | 2023Q3 | 0.237411 → 0.248403 | 0.226577 → 0.236983 | 0.030147 → 0.024426 | 0.553299 | 0.305199 |
| 0.001 | 2023Q4 | 0.228378 → 0.241436 | 0.215539 → 0.232469 | 0.031716 → 0.029266 | 0.443941 | 0.261526 |

Em Q2, CUSUM reduz nível e dispersão frente à logística temporal, melhorando proper scores mesmo com AUC pior. Em Q4, eleva nível e aproxima média da prevalência externa, mas ainda perde para constante própria. Esses diagnósticos são compatíveis com efeitos de nível/dispersão; não decompõem matematicamente ou causalmente toda mudança de score.

Máxima mudança absoluta de probabilidade externa ao igualar L2: 0,000086392 em h=0.0005 e 0,000399849 em h=0.001. Mesmo solver/tol=1e-4; não interpretar diferenças minúsculas como identificação precisa do efeito em soluções matematicamente exatas. Sem retreino com outra tolerância.

## Suporte e fórmula C

Quatro passados únicos; aliases Q3 interno=Q2 refit e Q4 interno=Q3 refit conferidos por contrato completo, não apenas quantidade de linhas.

| Primeiro uso | N temporal | N h=0.0005 | C h=0.0005 | N h=0.001 | C h=0.001 |
|---|---:|---:|---:|---:|---:|
| 2023Q2 inner | 689952 | 65546 | 10.526225857 | 23209 | 29.727778017 |
| 2023Q2 refit | 804307 | 74242 | 10.833584763 | 26257 | 30.632098107 |
| 2023Q3 refit | 820380 | 75049 | 10.931258245 | 26512 | 30.943723597 |
| 2023Q4 refit | 926669 | 80321 | 11.537070007 | 28249 | 32.803603667 |

Suporte externo (linhas/positivos): h=0.0005 Q2 742/55, Q3 5.267/1.286, Q4 8.651/2.607; h=0.001 Q2 236/19, Q3 1.733/433, Q4 2.834/834. Não comparar universos como ranking.

## Limitações preservadas

Censura após corte de horizonte: Q2 74,84%, Q3 27,24%, Q4 4,39%, sobre todos os candidatos elegíveis pelo horizonte (denominador diferente do conjunto conclusivo usado nos scores). Q2 não foi excluído; Q4 também tem resultado negativo contra constante. Sobreposição, pesos por duração realizada, avaliação condicionada a observabilidade futura e poucos regimes limitam inferência. Internos repetem externos; externos já vistos continuam exploratórios. Sensibilidade semanal é descritiva, sem p-valores ou intervalos de confiança.

Nenhuma abertura de preços/labels 2024; nenhum 2025 ou #6–#9. Contrato de sessão, gaps, labels, features, máscaras e pesos preservado. Sem seleção de thresholds/configuração, sem merge. Bid-only, custos/ask ausentes; classificação não autoriza alegação de lucro.

## Artefatos e verificação

- [Protocolo](session-controls-v1-protocol.md), [configuração](../../configs/session_controls_v1.json), [runner/verificador](../../fxnn/session_controls.py), [evidências agregadas](session-controls-v1-evidence.json).
- Local: `/Users/leohermoso/FXNN-trading-clock/output/session_controls_v1/`. 16 modelos NPZ e metadados, 12 arquivos de previsões, relatório, verificação, run.json e snapshots completos do ledger. Nenhum modelo/previsão no Git.
- 129 testes passaram; `git diff --check` passou. Antes dos fits, 16 controles antigos conferidos e 115.323 probabilidades reproduzidas. Depois, 192.205 probabilidades reproduzidas exatamente nos 12 arquivos; métricas, diagnósticos, contrastes e sensibilidade recalculados.
- Verificação repetida em processo novo sem ajuste: mesmos hashes e métricas; fontes congeladas preservadas. Fórmula C, prior/scaler locais ao treino, identidades, contratos e vínculo dos 16 fits ao ledger conferidos. Prefixo anterior do ledger intacto; zero falhas.

SHA-256 do relatório completo: `fea618bf1e8c1125d76101af149d9e97c2ef561e1494905cbf1db3b036980ff4`.
SHA-256 do ledger final: `3e9ed64b3307b346e0108e8710ceb8031d93645b4504065f5de6ef76f058a2d1`.

Comando executado após pré-registro (destino foi criado uma única vez):

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.session_controls
```

Não repetir esse comando para buscar scores melhores: runner rejeita destino existente e ledger rejeita experimento já tentado. Reprodução de inferência usa `verify_output`, sem treinar estimadores.
