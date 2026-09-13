# afml_v1 — resultado

**Não houve ganho consistente neste experimento.** FFD escolhida internamente
melhorou log-loss em julho/agosto, mas piorou setembro, ficando nesse mês
também abaixo da constante. Nenhuma tentativa adicional foi feita.

[Protocolo](afml-v1-protocol.md) registrado em f79a9e6 antes do treino;
execução em a33a7ca. Uma rodada, 111 ajustes, três d e três folds externos.
Tempo: 15.5 segundos nesta máquina, CPU com threads numéricas limitadas a uma.

## Comparação externa no mesmo universo

Menor log-loss é melhor. FFD = 28 features + uma coluna orientada pela direção.
Controle foi reajustado com as mesmas linhas, scaler no treino e unicidade
recalculada. Constante usa prior ponderado desse treino.

| Mês | Candidatos | Positivos | d interno | Constante | Controle | FFD | Adaptativo |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-07 | 18501 | 4169 | 0.75 | 0.539705 | 0.547102 | 0.521714 | 0.547102 |
| 2025-08 | 14772 | 3240 | 0.25 | 0.531209 | 0.534570 | 0.530543 | 0.530543 |
| 2025-09 | 13923 | 3149 | 0.25 | 0.543158 | 0.522098 | 0.544459 | 0.544459 |

Adaptativo respeita escolha interna: em julho mantém controle; em agosto e
setembro usa d=0.25. Portanto, a melhora retrospectivamente observada da FFD
em julho não pode ser atribuída à política adaptativa. Essa política empata
julho, melhora agosto e piora setembro contra controle.

| Mês | Brier controle | Brier FFD | AP controle | AP FFD |
|---|---:|---:|---:|---:|
| 2025-07 | 0.178849 | 0.170864 | 0.212953 | 0.308764 |
| 2025-08 | 0.173648 | 0.171746 | 0.223819 | 0.261201 |
| 2025-09 | 0.171219 | 0.177698 | 0.338150 | 0.236505 |

## Todas as tentativas internas

Seleção minimiza log-loss interna, empate por menor d. Permutação, SFI e
ADF são diagnósticos; não removem features e não escolhem configuração.

| Mês externo | Validação interna | Controle | d=0.25 | d=0.50 | d=0.75 |
|---|---|---:|---:|---:|---:|
| 2025-07 | 2025-06 | 0.524140 | 0.561732 | 0.560732 | 0.547626 |
| 2025-08 | 2025-07 | 0.547102 | 0.512821 | 0.513404 | 0.521714 |
| 2025-09 | 2025-08 | 0.534570 | 0.530543 | 0.530651 | 0.531297 |

## Custo do histórico adicional

Janelas de 445/200/79 candles para d=0.25/0.50/0.75; buffer comum de
445 minutos, além de 72h de horizonte conservador. Nenhuma lacuna preenchida.
Tabela antes dos filtros temporais, depois do aquecimento antigo. Todos os
modelos usam interseção pré-fixada, independentemente da classe.

| Mês | Elegíveis antigos | Excluídos adicionais | Comuns | Positivos antigos | Positivos comuns |
|---|---:|---:|---:|---:|---:|
| 2025-01 | 36017 | 6511 | 29506 | 27.15% | 27.26% |
| 2025-02 | 25322 | 6728 | 18594 | 22.23% | 20.03% |
| 2025-03 | 35101 | 6816 | 28285 | 23.69% | 22.32% |
| 2025-04 | 40696 | 7348 | 33348 | 26.20% | 25.85% |
| 2025-05 | 38017 | 6380 | 31637 | 27.34% | 26.45% |
| 2025-06 | 31396 | 7814 | 23582 | 23.84% | 22.37% |
| 2025-07 | 29716 | 7160 | 22556 | 23.96% | 21.36% |
| 2025-08 | 21985 | 7059 | 14926 | 21.98% | 21.77% |
| 2025-09 | 22039 | 6976 | 15063 | 21.44% | 20.91% |

Exclusões adicionais janeiro–setembro: 62792 candidatos.
A população mudou materialmente; não comparar os scores diretamente com
research_v1/neural_v1. Comparação válida aqui é com controle comum acima.

| Fold | Treino interno | Validação interna | Refit | Teste | Expurgo/buffer refit | Fronteira direita teste |
|---|---:|---:|---:|---:|---:|---:|
| 2025-07 | 137689 | 22229 | 163408 | 18501 | 1544 | 4055 |
| 2025-08 | 163408 | 18501 | 183397 | 14772 | 4111 | 154 |
| 2025-09 | 183397 | 14772 | 202248 | 13923 | 186 | 1140 |

## Importância e redundância

Aumento de log-loss ao permutar família FFD na validação interna:

| d | Junho | Julho | Agosto | Folds positivos |
|---|---:|---:|---:|---:|
| 0.25 | 0.009837 | 0.130153 | 0.071168 | 3/3 |
| 0.5 | 0.008970 | 0.126797 | 0.069860 | 3/3 |
| 0.75 | -0.008922 | 0.086236 | 0.042228 | 2/3 |

FFD orientada tem maior correlação com direction: aproximadamente 0.89–0.91
nos treinos. Permutar FFD separadamente de direction pode criar combinações
fora da distribuição original. Importância alta não demonstra informação
independente nem causalidade. Repetições por bloco não fornecem p-valores válidos.

SFI: ganho de log-loss sobre constante na validação interna, positivo = melhora.
Tabela completa de features, sem seleção retrospectiva:

| Feature | Junho | Julho | Agosto | Folds positivos |
|---|---:|---:|---:|---:|
| return_5 | 0.000083 | -0.000098 | -0.000192 | 1/3 |
| volatility_5 | -0.000234 | -0.000304 | -0.000184 | 0/3 |
| range_pips_5 | -0.000589 | -0.000849 | -0.000553 | 0/3 |
| zscore_5 | 0.000031 | 0.000020 | 0.000108 | 3/3 |
| efficiency_5 | 0.000045 | 0.000074 | -0.000018 | 2/3 |
| return_15 | 0.000113 | -0.000274 | -0.000672 | 1/3 |
| volatility_15 | -0.000318 | -0.000424 | -0.000218 | 0/3 |
| range_pips_15 | -0.000800 | -0.001143 | -0.000811 | 0/3 |
| zscore_15 | 0.000020 | -0.000076 | 0.000334 | 2/3 |
| efficiency_15 | -0.000036 | 0.000243 | -0.000104 | 1/3 |
| return_60 | 0.000083 | -0.000010 | -0.000481 | 1/3 |
| volatility_60 | -0.000916 | -0.000741 | -0.000256 | 0/3 |
| range_pips_60 | -0.001839 | -0.001897 | -0.000912 | 0/3 |
| zscore_60 | 0.000246 | -0.000567 | 0.000441 | 2/3 |
| efficiency_60 | -0.000359 | 0.000327 | 0.000341 | 2/3 |
| return_240 | -0.000968 | -0.000811 | 0.000581 | 1/3 |
| volatility_240 | 0.000555 | 0.001524 | 0.002390 | 3/3 |
| range_pips_240 | -0.000917 | -0.000360 | 0.000724 | 1/3 |
| zscore_240 | 0.000412 | -0.000310 | -0.000315 | 1/3 |
| efficiency_240 | -0.000209 | -0.000679 | 0.001137 | 1/3 |
| body | 0.000022 | 0.000002 | 0.000053 | 3/3 |
| upper_wick | 0.000041 | -0.000053 | -0.000004 | 1/3 |
| lower_wick | 0.000033 | -0.000058 | -0.000057 | 1/3 |
| hour_sin | 0.005928 | 0.009551 | 0.002125 | 3/3 |
| hour_cos | -0.000675 | -0.001026 | 0.006624 | 1/3 |
| weekday_sin | 0.001051 | 0.002081 | -0.000436 | 2/3 |
| weekday_cos | 0.000105 | 0.002744 | 0.000608 | 3/3 |
| direction | 0.004115 | -0.015115 | -0.000666 | 1/3 |
| ffd_0.25 | -0.006343 | -0.007365 | 0.000445 | 1/3 |
| ffd_0.5 | -0.007311 | -0.005610 | 0.000514 | 1/3 |
| ffd_0.75 | -0.007440 | -0.002639 | 0.000564 | 1/3 |

FFD isolada perde da constante em junho/julho e melhora pouco em agosto.
Isso não foi usado para descartar interações. No controle, movement, position
e context apresentam permutação positiva nos três folds internos; demais
famílias variam. Estabilidade completa e repetições estão no JSON.

## Estacionariedade e memória

Regra pré-fixada escolheu o mesmo segmento de treino nos três folds:
5.000 entradas únicas contínuas, índices 119625–124624. Portanto, ADF e
correlações abaixo são um diagnóstico repetido do mesmo segmento, não três
confirmações independentes. Log-preço anterior: ADF p≈0.355.

| d | ADF estatística | ADF p | Correlação com log-preço |
|---|---:|---:|---:|
| 0.25 | -6.9128 | 1.2e-09 | 0.9209 |
| 0.5 | -19.8649 | 0 | 0.6084 |
| 0.75 | -36.5874 | 0 | 0.2494 |

p=0 é saída numérica do teste. Rejeição de raiz unitária nesse segmento e
correlação preservada não implicam previsibilidade. ADF não escolheu d.

## Verificação e limites

- 55 testes locais passaram: binomial independente, d=0/1, truncamento, lacunas,
  invariância a preços futuros, ingestão e isolamento de labels externos.
- Parâmetros/scalers salvos reproduzem probabilidades externas sem novo treino.
- Compilação, pip check e git diff --check passaram. Estado de CI é registrado na tarefa.
- Baselines anteriores preservados; outubro–dezembro não modelados.
- Um ano, bid-only, censura e candidatos sobrepostos. Sem significância declarada
  ou alegação de lucro. Não aumentar busca com base nesses três meses.

[JSON agregado](afml-v1.json) contém métricas externas completas (incluindo
ROC-AUC e thresholds 0.3/0.4/0.5), todas as métricas dos quatro modelos internos,
SFI resumida, permutações, suporte, versões e hashes. Registro completo com
métricas SFI, modelos/scalers, pesos de unicidade e previsões fica em
output/afml_v1, fora do Git. Hash do relatório completo consta no agregado.

Reprodução em ambiente novo, preservando diretório original:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.afml --output output/afml_v1
```
