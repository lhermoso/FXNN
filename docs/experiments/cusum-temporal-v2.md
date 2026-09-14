# cusum_temporal_v2 — comparação exploratória executada

**Ambos os CUSUM apresentaram menor log-loss que a logística temporal nos três externos nas respectivas identidades pareadas. Ambos perderam para a constante em Q2 e Q4.** A regra pré-registrada de ganho descritivo contra temporal foi satisfeita, sem seleção entre limiares; superioridade inferencial permanece inconclusiva. Ambas as linhas continuam ativas.

Continuação informada pelo suporte já conhecido de cusum_v1; não confirmação independente. Pré-registro `dbbc2b6`; código executado `80322d1`. Todos os 24 ajustes foram bem-sucedidos: 18 logísticas e 6 constantes, zero falhas técnicas e zero partições inviáveis. Consumo anterior 0, novo 24, global **24/1.000**, saldo 976. cusum_v1 continua com zero fits.

Fontes 2022–2023 verificadas pelos hashes originais; 2024 fechado, nenhum uso de 2025. #6–#9 não executadas. TP50/SL20/<72h, folds, expurgo, buffer 241, features, long/short e logística preservados. Entradas somente após fechamento e continuidade, reset por lacunas. Nenhuma interseção exigida, busca ou escolha de vencedor.

## Comparações externas pareadas

N representa candidatos por lado, não eventos independentes. Dentro de cada linha de universo os três modelos usam exatamente as mesmas identidades. Scores de limiares diferentes não servem para ordená-los. LL = log-loss; AP = average precision.

| Fold | h | N / positivos / aberturas distintas | Modelo | LL | Brier | AP | ROC-AUC |
|---|---|---:|---|---:|---:|---:|---:|
| 2023Q2 | 0.0005 | 624 / 40 / 552 | temporal | 0.355677 | 0.094438 | 0.056432 | 0.397945 |
| 2023Q2 | 0.0005 | 624 / 40 / 552 | constant | 0.300269 | 0.074805 | 0.064103 | 0.500000 |
| 2023Q2 | 0.0005 | 624 / 40 / 552 | cusum | 0.330162 | 0.084980 | 0.058360 | 0.395334 |
| 2023Q2 | 0.001 | 207 / 15 / 182 | temporal | 0.362052 | 0.097645 | 0.056846 | 0.370139 |
| 2023Q2 | 0.001 | 207 / 15 / 182 | constant | 0.312622 | 0.080059 | 0.072464 | 0.500000 |
| 2023Q2 | 0.001 | 207 / 15 / 182 | cusum | 0.339610 | 0.089278 | 0.059527 | 0.362153 |
| 2023Q3 | 0.0005 | 2517 / 413 / 1854 | temporal | 0.444025 | 0.137135 | 0.185092 | 0.574903 |
| 2023Q3 | 0.0005 | 2517 / 413 / 1854 | constant | 0.446938 | 0.137320 | 0.164084 | 0.500000 |
| 2023Q3 | 0.0005 | 2517 / 413 / 1854 | cusum | 0.443876 | 0.136960 | 0.180802 | 0.569466 |
| 2023Q3 | 0.001 | 864 / 141 / 633 | temporal | 0.442444 | 0.136472 | 0.190225 | 0.580246 |
| 2023Q3 | 0.001 | 864 / 141 / 633 | constant | 0.445568 | 0.136744 | 0.163194 | 0.500000 |
| 2023Q3 | 0.001 | 864 / 141 / 633 | cusum | 0.440997 | 0.135966 | 0.188556 | 0.579981 |
| 2023Q4 | 0.0005 | 4477 / 997 / 3100 | temporal | 0.554846 | 0.178001 | 0.279225 | 0.589495 |
| 2023Q4 | 0.0005 | 4477 / 997 / 3100 | constant | 0.540123 | 0.176070 | 0.222694 | 0.500000 |
| 2023Q4 | 0.0005 | 4477 / 997 / 3100 | cusum | 0.553476 | 0.178353 | 0.279627 | 0.588840 |
| 2023Q4 | 0.001 | 1508 / 315 / 1050 | temporal | 0.536539 | 0.169846 | 0.251591 | 0.571479 |
| 2023Q4 | 0.001 | 1508 / 315 / 1050 | constant | 0.518053 | 0.166907 | 0.208886 | 0.500000 |
| 2023Q4 | 0.001 | 1508 / 315 / 1050 | cusum | 0.527777 | 0.168546 | 0.254755 | 0.575686 |

Em h=0,0005, Brier piorou em Q4 apesar da queda em log-loss; a regra usa Brier médio dos três folds, não exige melhoria em cada um. AP/ROC-AUC tampouco melhoram uniformemente. Q2 tem apenas 40 e 15 positivos: resultado calculável, precisão limitada.

## Baseline no universo temporal completo — separado

| Fold | N / positivos | Modelo | LL | Brier | AP | ROC-AUC |
|---|---:|---|---:|---:|---:|---:|
| 2023Q2 | 12446 / 799 | temporal | 0.345569 | 0.090760 | 0.049443 | 0.411211 |
| 2023Q2 | 12446 / 799 | constant | 0.300409 | 0.074865 | 0.064197 | 0.500000 |
| 2023Q3 | 38577 / 6359 | temporal | 0.438190 | 0.135410 | 0.209733 | 0.602625 |
| 2023Q3 | 38577 / 6359 | constant | 0.448099 | 0.137808 | 0.164839 | 0.500000 |
| 2023Q4 | 65183 / 16449 | temporal | 0.607444 | 0.198756 | 0.292573 | 0.568253 |
| 2023Q4 | 65183 / 16449 | constant | 0.587528 | 0.195750 | 0.252351 | 0.500000 |

Temporal também perde para constante em Q2/Q4 no universo completo. Não confundir melhoria sobre controle logístico fraco com ganho sobre ausência de features.

## Diagnóstico interno — sem seleção

| Fold | Universo | N / positivos | LL temporal | LL constante | LL CUSUM |
|---|---|---:|---:|---:|---:|
| 2023Q2 | temporal | 57057 / 11989 | 0.514971 | 0.515179 | — |
| 2023Q2 | 0.0005 | 5228 / 1117 | 0.520794 | 0.520262 | 0.517810 |
| 2023Q2 | 0.001 | 1874 / 402 | 0.521717 | 0.521495 | 0.518067 |
| 2023Q3 | temporal | 12446 / 799 | 0.345569 | 0.300409 | — |
| 2023Q3 | 0.0005 | 624 / 40 | 0.355677 | 0.300269 | 0.330162 |
| 2023Q3 | 0.001 | 207 / 15 | 0.362052 | 0.312622 | 0.339610 |
| 2023Q4 | temporal | 38577 / 6359 | 0.438190 | 0.448099 | — |
| 2023Q4 | 0.0005 | 2517 / 413 | 0.444025 | 0.446938 | 0.443876 |
| 2023Q4 | 0.001 | 864 / 141 | 0.442444 | 0.445568 | 0.440997 |

As validações internas Q3/Q4 repetem calendário e treino dos externos Q2/Q3. Seus resultados coincidem; não constituem evidência adicional independente. Os ajustes por fase estavam fixados antes da execução e todos foram contabilizados, sem retries ou substituição de tentativa desfavorável. Métricas internas completas e thresholds fixos 0,3/0,4/0,5 estão no JSON.

## Dependência, cobertura e precisão

| Fold | Universo externo | Censura amostrada | Densidade de candidatos | Cobertura retida temporal | Unicidade bruta | Concorrência máx. / média ativa |
|---|---|---:|---:|---:|---:|---:|
| 2023Q2 | temporal | 77.45% | 100.00% | 9.98% | 0.010134 | 422 / 104.19 |
| 2023Q2 | 0.0005 | 78.51% | 4.56% | 0.50% | 0.186567 | 25 / 4.88 |
| 2023Q2 | 0.001 | 78.17% | 1.34% | 0.17% | 0.454913 | 10 / 2.14 |
| 2023Q3 | temporal | 63.73% | 100.00% | 23.56% | 0.005541 | 1112 / 224.85 |
| 2023Q3 | 0.0005 | 57.69% | 4.76% | 1.54% | 0.084950 | 61 / 12.73 |
| 2023Q3 | 0.001 | 55.34% | 1.51% | 0.53% | 0.210625 | 22 / 5.08 |
| 2023Q4 | temporal | 51.13% | 100.00% | 35.89% | 0.004105 | 2317 / 319.04 |
| 2023Q4 | 0.0005 | 45.08% | 5.19% | 2.46% | 0.060905 | 100 / 18.53 |
| 2023Q4 | 0.001 | 44.14% | 1.66% | 0.83% | 0.165410 | 34 / 6.82 |

Sensibilidade ao remover uma semana UTC de entradas, sem refit. ΔLL = CUSUM − comparador; negativo favorece CUSUM. Faixa não é IC, não é p-valor e não ajusta toda dependência.

| Fold | h | Comparador | ΔLL | Faixa ΔLL ao remover semana |
|---|---|---|---:|---:|
| 2023Q2 | 0.0005 | temporal | -0.025515 | [-0.027239, -0.024179] |
| 2023Q2 | 0.0005 | constant | +0.029894 | [+0.027994, +0.031916] |
| 2023Q2 | 0.001 | temporal | -0.022442 | [-0.024615, -0.020346] |
| 2023Q2 | 0.001 | constant | +0.026988 | [+0.025444, +0.029417] |
| 2023Q3 | 0.0005 | temporal | -0.000149 | [-0.001668, +0.000805] |
| 2023Q3 | 0.0005 | constant | -0.003061 | [-0.008400, -0.000974] |
| 2023Q3 | 0.001 | temporal | -0.001447 | [-0.002917, +0.000298] |
| 2023Q3 | 0.001 | constant | -0.004571 | [-0.011250, -0.001526] |
| 2023Q4 | 0.0005 | temporal | -0.001370 | [-0.002080, +0.001107] |
| 2023Q4 | 0.0005 | constant | +0.013353 | [+0.003385, +0.016439] |
| 2023Q4 | 0.001 | temporal | -0.008762 | [-0.010044, -0.005065] |
| 2023Q4 | 0.001 | constant | +0.009724 | [+0.001063, +0.012236] |

Intervalos de labels atravessam semanas e regimes persistem. As faixas descrevem influência das semanas observadas; não delimitam erro populacional. Poucos positivos, apenas três externos e censura seletiva limitam precisão. Unicidade bruta não é N efetivo. O JSON contém suporte semanal, deltas/faixas Brier e diagnósticos de treino/refit/validação/teste, incluindo aquecimento e pesos.

## Interpretação e rastreabilidade

- Falha técnica: nenhuma nesta execução; caminho sintético testa falha consumida e continuação de IDs distintos, sem retry.
- Resultado preditivo desfavorável: contra constante em Q2/Q4; misto no conjunto de folds.
- Estimativa inferencial inconclusiva: dependência e precisão não validadas, desenho informado pela auditoria. Nem o ganho descritivo nem as perdas descartam/promovem automaticamente CUSUM.
- Classificação não demonstra lucro: bid-only, spread/custos ausentes, lacunas e censura continuam bloqueios econômicos.

Comando científico único: `.venv/bin/python -m fxnn.cusum_continuation`. Artefatos locais em `output/cusum_temporal_v2`; previsões por identidade permanecem fora do Git.

[Protocolo](cusum-temporal-v2-protocol.md), [relatório integral byte-exato](cusum-temporal-v2.json), [ledger completo](cusum-temporal-v2-ledger.jsonl), [manifesto](cusum-temporal-v2-evidence.json). O ledger conserva prefixo publicado de cusum_v1 e registra cada tentativa antes do fit. SHA das previsões: `5c23c226b20efee2b39532f496c092a08809d87207f349759dd0b0eabd281cab`. Hashes de código, protocolo, fontes e versões estão no relatório.

Exportação sem novo ajuste:

```bash
.venv/bin/python -m fxnn.cusum_evidence --experiment cusum_temporal_v2 \
  --report output/cusum_temporal_v2/report.json \
  --ledger /Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl \
  --destination docs/experiments
```

Reprodução da auditoria publicada dispensa dados de mercado; reexecução científica deste ID é bloqueada. Evidência original não é reescrita por revisões posteriores de testes/documentação.
