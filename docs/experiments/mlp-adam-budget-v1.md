# mlp_adam_budget_v1 — resultados exploratórios

Execução informada após PR #15; [pré-registro](mlp-adam-budget-v1-protocol.md) commitado em `a67d8f2`, código executado em `eda0c8f65f1599ef566921ca178765b8a0fbb8e4`. Desenvolvimento 2022–2023, confirmação 2024 fechada, nenhum 2025 ou #6–#9.

**Não: o ganho descritivo de eventos sobre MLP temporal não persistiu ao igualar atualizações.** Nos dois limiares, nova MLP eventos melhorou log-loss somente em Q2, piorando Q3/Q4. Brier médio ainda foi menor, mas não basta para satisfazer a regra pré-registrada. MLPs de 20 épocas e logísticas preservam seu ganho descritivo eventos−temporal anterior.

Aumentar orçamento de eventos melhorou Q2 e piorou Q3/Q4 versus 20 épocas. No temporal, Q2 piorou, Q3 melhorou e Q4 ficou idêntico. Novas MLPs superaram logística da mesma amostragem somente em Q2. **Todas MLPs, novas e anteriores, perderam para constante em log-loss e Brier nos três externos.** Nenhum ganho consistente de arquitetura ou valor consistente das features demonstrado.

Oito ajustes de eventos atingiram diagnóstico pré-fixado de estabilização; quatro temporais não. Isso é diagnóstico de loss, não prova de convergência. Resultado mostra sensibilidade ao procedimento de otimização; não identifica orçamento como causa única do ganho anterior, pois exposições e regularização efetiva continuam diferentes.

Sensibilidade eventos−temporal: vantagem Q2 e desvantagem Q3 em log-loss mantêm sinal ao remover qualquer semana, nos dois limiares. Em Q4/h=0,0005, sinal pode inverter (ΔLL de −0,003837 a +0,003451); em h=0,001 permanece desfavorável (+0,001295 a +0,010929). São faixas descritivas, não IC.

12 novos ajustes únicos, todos finitos, exatamente 9.580 atualizações Adam cada; controles históricos reutilizados. Ledger **48/1.000**, saldo **952**. Sem retries, busca, seleção de checkpoint ou extensão após scores.

[Agregado completo](mlp-adam-budget-v1.json), [ledger](mlp-adam-budget-v1-ledger.jsonl), [manifesto SHA-256](mlp-adam-budget-v1-evidence.json). Previsões e trajetórias por batch ficam locais, fora do Git.

## Orçamento e otimização

Orçamento comum derivado exclusivamente dos tamanhos temporais anteriores: 20×ceil(N/1024), máximo 9.580. N=378214/437752/451267/490276 → 7400/8560/8820/9580. Nenhum score participou dessa escolha.

| Ajuste original | N / positivos | Updates | Épocas completas + batches parciais | Exposições/candidato | Diagnóstico |
|---|---:|---:|---:|---:|---|
| 2023Q2:inner:temporal | 378214 / 93309 | 9580 | 25 + 330 | 25.893 | training_loss_not_stabilized |
| 2023Q2:inner:0.0005 | 45254 / 11154 | 9580 | 212 + 40 | 212.905 | training_loss_stabilized |
| 2023Q2:inner:0.001 | 16492 / 4050 | 9580 | 563 + 9 | 563.559 | training_loss_stabilized |
| 2023Q2:refit:temporal | 437752 / 105985 | 9580 | 22 + 164 | 22.384 | training_loss_not_stabilized |
| 2023Q2:refit:0.0005 | 50712 / 12319 | 9580 | 191 + 30 | 191.606 | training_loss_stabilized |
| 2023Q2:refit:0.001 | 18460 / 4469 | 9580 | 504 + 4 | 504.222 | training_loss_stabilized |
| 2023Q3:refit:temporal | 451267 / 106787 | 9580 | 21 + 319 | 21.724 | training_loss_not_stabilized |
| 2023Q3:refit:0.0005 | 51400 / 12359 | 9580 | 187 + 43 | 187.857 | training_loss_stabilized |
| 2023Q3:refit:0.001 | 18686 / 4484 | 9580 | 504 + 4 | 504.219 | training_loss_stabilized |
| 2023Q4:refit:temporal | 490276 / 113146 | 9580 | 20 + 0 | 20.000 | training_loss_not_stabilized |
| 2023Q4:refit:0.0005 | 53940 / 12772 | 9580 | 180 + 40 | 180.759 | training_loss_stabilized |
| 2023Q4:refit:0.001 | 19556 / 4625 | 9580 | 479 + 0 | 479.000 | training_loss_stabilized |

Finitude de losses, coeficientes e momentos Adam verificada. Curvas de épocas completas e loss parcial separadas no JSON; hashes das curvas por batch e momentos finais também publicados. Diagnóstico usa diferença absoluta das duas últimas losses de épocas completas <1e-4; não comprova convergência, não decide parada. `partial_fit` não emite ConvergenceWarning por atingir limite de iterações.

Verificação posterior sem novos fits: todos 12 scalers/pesos e as primeiras 20 losses de épocas completas coincidem exatamente com MLP anterior. Em Q4, nova MLP temporal recebeu o mesmo orçamento anterior: todas suas métricas coincidem exatamente nos três universos. Isso verifica preservação do prefixo nativo e separa efeito de extensão do treino.

Igualar updates não iguala exposição por candidato, convergência ou regularização efetiva. Último batch curto permanece incluído; alpha continua dividido pela soma dos pesos do minibatch. O procedimento longo em eventos repassa os mesmos candidatos muito mais vezes.

## Métricas externas pareadas

`mlp_*`: orçamento comum; `mlp20_*`: controle anterior de 20 épocas. Sufixo indica treino temporal ou eventos. Todas linhas de um fold/universo usam exatamente mesmas identidades; não comparar métricas entre populações nem ordenar limiares.

| Fold | Universo | Método | N / positivos | Log-loss | Brier | AP | ROC-AUC |
|---|---|---|---:|---:|---:|---:|---:|
| 2023Q2 | temporal | logistic_temporal | 12446 / 799 | 0.345569 | 0.090760 | 0.049443 | 0.411211 |
| 2023Q2 | temporal | constant | 12446 / 799 | 0.300409 | 0.074865 | 0.064197 | 0.500000 |
| 2023Q2 | temporal | mlp20_temporal | 12446 / 799 | 0.321642 | 0.084569 | 0.077440 | 0.609169 |
| 2023Q2 | temporal | mlp_temporal | 12446 / 799 | 0.324032 | 0.085269 | 0.076331 | 0.597641 |
| 2023Q2 | 0.0005 | logistic_temporal | 624 / 40 | 0.355677 | 0.094438 | 0.056432 | 0.397945 |
| 2023Q2 | 0.0005 | constant | 624 / 40 | 0.300269 | 0.074805 | 0.064103 | 0.500000 |
| 2023Q2 | 0.0005 | logistic_event | 624 / 40 | 0.330162 | 0.084980 | 0.058360 | 0.395334 |
| 2023Q2 | 0.0005 | mlp20_temporal | 624 / 40 | 0.328842 | 0.087123 | 0.079747 | 0.594349 |
| 2023Q2 | 0.0005 | mlp20_event | 624 / 40 | 0.321159 | 0.082666 | 0.060394 | 0.483005 |
| 2023Q2 | 0.0005 | mlp_temporal | 624 / 40 | 0.335943 | 0.089479 | 0.075134 | 0.569307 |
| 2023Q2 | 0.0005 | mlp_event | 624 / 40 | 0.306033 | 0.079901 | 0.080265 | 0.575171 |
| 2023Q2 | 0.001 | logistic_temporal | 207 / 15 | 0.362052 | 0.097645 | 0.056846 | 0.370139 |
| 2023Q2 | 0.001 | constant | 207 / 15 | 0.312622 | 0.080059 | 0.072464 | 0.500000 |
| 2023Q2 | 0.001 | logistic_event | 207 / 15 | 0.339610 | 0.089278 | 0.059527 | 0.362153 |
| 2023Q2 | 0.001 | mlp20_temporal | 207 / 15 | 0.345239 | 0.094003 | 0.098255 | 0.601736 |
| 2023Q2 | 0.001 | mlp20_event | 207 / 15 | 0.340180 | 0.090363 | 0.121075 | 0.561111 |
| 2023Q2 | 0.001 | mlp_temporal | 207 / 15 | 0.350791 | 0.095851 | 0.093171 | 0.580556 |
| 2023Q2 | 0.001 | mlp_event | 207 / 15 | 0.329096 | 0.088225 | 0.061334 | 0.406597 |
| 2023Q3 | temporal | logistic_temporal | 38577 / 6359 | 0.438190 | 0.135410 | 0.209733 | 0.602625 |
| 2023Q3 | temporal | constant | 38577 / 6359 | 0.448099 | 0.137808 | 0.164839 | 0.500000 |
| 2023Q3 | temporal | mlp20_temporal | 38577 / 6359 | 0.482603 | 0.146567 | 0.143602 | 0.470021 |
| 2023Q3 | temporal | mlp_temporal | 38577 / 6359 | 0.480746 | 0.145709 | 0.146405 | 0.473349 |
| 2023Q3 | 0.0005 | logistic_temporal | 2517 / 413 | 0.444025 | 0.137135 | 0.185092 | 0.574903 |
| 2023Q3 | 0.0005 | constant | 2517 / 413 | 0.446938 | 0.137320 | 0.164084 | 0.500000 |
| 2023Q3 | 0.0005 | logistic_event | 2517 / 413 | 0.443876 | 0.136960 | 0.180802 | 0.569466 |
| 2023Q3 | 0.0005 | mlp20_temporal | 2517 / 413 | 0.481167 | 0.146449 | 0.150302 | 0.482440 |
| 2023Q3 | 0.0005 | mlp20_event | 2517 / 413 | 0.454272 | 0.139498 | 0.178367 | 0.543890 |
| 2023Q3 | 0.0005 | mlp_temporal | 2517 / 413 | 0.481058 | 0.146257 | 0.152198 | 0.482671 |
| 2023Q3 | 0.0005 | mlp_event | 2517 / 413 | 0.490375 | 0.147775 | 0.146184 | 0.463776 |
| 2023Q3 | 0.001 | logistic_temporal | 864 / 141 | 0.442444 | 0.136472 | 0.190225 | 0.580246 |
| 2023Q3 | 0.001 | constant | 864 / 141 | 0.445568 | 0.136744 | 0.163194 | 0.500000 |
| 2023Q3 | 0.001 | logistic_event | 864 / 141 | 0.440997 | 0.135966 | 0.188556 | 0.579981 |
| 2023Q3 | 0.001 | mlp20_temporal | 864 / 141 | 0.479389 | 0.145825 | 0.152050 | 0.481240 |
| 2023Q3 | 0.001 | mlp20_event | 864 / 141 | 0.451655 | 0.139342 | 0.183877 | 0.542950 |
| 2023Q3 | 0.001 | mlp_temporal | 864 / 141 | 0.479181 | 0.145697 | 0.153910 | 0.483417 |
| 2023Q3 | 0.001 | mlp_event | 864 / 141 | 0.490561 | 0.145970 | 0.169087 | 0.494414 |
| 2023Q4 | temporal | logistic_temporal | 65183 / 16449 | 0.607444 | 0.198756 | 0.292573 | 0.568253 |
| 2023Q4 | temporal | constant | 65183 / 16449 | 0.587528 | 0.195750 | 0.252351 | 0.500000 |
| 2023Q4 | temporal | mlp20_temporal | 65183 / 16449 | 0.656292 | 0.205820 | 0.293428 | 0.550774 |
| 2023Q4 | temporal | mlp_temporal | 65183 / 16449 | 0.656292 | 0.205820 | 0.293428 | 0.550774 |
| 2023Q4 | 0.0005 | logistic_temporal | 4477 / 997 | 0.554846 | 0.178001 | 0.279225 | 0.589495 |
| 2023Q4 | 0.0005 | constant | 4477 / 997 | 0.540123 | 0.176070 | 0.222694 | 0.500000 |
| 2023Q4 | 0.0005 | logistic_event | 4477 / 997 | 0.553476 | 0.178353 | 0.279627 | 0.588840 |
| 2023Q4 | 0.0005 | mlp20_temporal | 4477 / 997 | 0.592075 | 0.183546 | 0.259200 | 0.552714 |
| 2023Q4 | 0.0005 | mlp20_event | 4477 / 997 | 0.560258 | 0.179661 | 0.258825 | 0.565557 |
| 2023Q4 | 0.0005 | mlp_temporal | 4477 / 997 | 0.592075 | 0.183546 | 0.259200 | 0.552714 |
| 2023Q4 | 0.0005 | mlp_event | 4477 / 997 | 0.592920 | 0.183770 | 0.254043 | 0.545735 |
| 2023Q4 | 0.001 | logistic_temporal | 1508 / 315 | 0.536539 | 0.169846 | 0.251591 | 0.571479 |
| 2023Q4 | 0.001 | constant | 1508 / 315 | 0.518053 | 0.166907 | 0.208886 | 0.500000 |
| 2023Q4 | 0.001 | logistic_event | 1508 / 315 | 0.527777 | 0.168546 | 0.254755 | 0.575686 |
| 2023Q4 | 0.001 | mlp20_temporal | 1508 / 315 | 0.563425 | 0.173512 | 0.243419 | 0.553139 |
| 2023Q4 | 0.001 | mlp20_event | 1508 / 315 | 0.532672 | 0.170443 | 0.218925 | 0.535893 |
| 2023Q4 | 0.001 | mlp_temporal | 1508 / 315 | 0.563425 | 0.173512 | 0.243419 | 0.553139 |
| 2023Q4 | 0.001 | mlp_event | 1508 / 315 | 0.571199 | 0.174752 | 0.234952 | 0.534781 |

Thresholds fixos 0,3/0,4/0,5: contagens de sinais, TP/FP, precisão/recall e motivos de null para cada modelo/fase no agregado. Nenhum threshold escolhido pelos resultados. Internos Q3/Q4 repetem externos Q2/Q3; não são evidência adicional.

## Contrastes separados

Δ negativo favorece primeiro modelo. Critério: log-loss menor nos três externos e Brier médio não pior. Resultado descritivo não estabelece superioridade inferencial.

| Família | Universo | Contraste | ΔLL Q2 | ΔLL Q3 | ΔLL Q4 | ΔBrier médio | Regra descritiva |
|---|---|---|---:|---:|---:|---:|---|
| orçamento | temporal | mlp_temporal-vs-mlp20_temporal | +0.002390 | -0.001858 | +0.000000 | -0.000053 | misto/desfavorável |
| arquitetura | temporal | mlp_temporal-vs-logistic_temporal | -0.021537 | +0.042556 | +0.048848 | +0.003957 | misto/desfavorável |
| arquitetura | temporal | mlp20_temporal-vs-logistic_temporal | -0.023927 | +0.044413 | +0.048848 | +0.004010 | misto/desfavorável |
| modelo vs constante | temporal | mlp_temporal-vs-constant | +0.023624 | +0.032647 | +0.068764 | +0.009458 | misto/desfavorável |
| modelo vs constante | temporal | mlp20_temporal-vs-constant | +0.021233 | +0.034504 | +0.068764 | +0.009511 | misto/desfavorável |
| modelo vs constante | temporal | logistic_temporal-vs-constant | +0.045161 | -0.009909 | +0.019917 | +0.005501 | misto/desfavorável |
| orçamento | 0.0005 | mlp_temporal-vs-mlp20_temporal | +0.007101 | -0.000109 | +0.000000 | +0.000722 | misto/desfavorável |
| arquitetura | 0.0005 | mlp_temporal-vs-logistic_temporal | -0.019734 | +0.037033 | +0.037228 | +0.003236 | misto/desfavorável |
| arquitetura | 0.0005 | mlp20_temporal-vs-logistic_temporal | -0.026835 | +0.037142 | +0.037228 | +0.002515 | misto/desfavorável |
| modelo vs constante | 0.0005 | mlp_temporal-vs-constant | +0.035674 | +0.034120 | +0.051951 | +0.010363 | misto/desfavorável |
| modelo vs constante | 0.0005 | mlp20_temporal-vs-constant | +0.028573 | +0.034229 | +0.051951 | +0.009641 | misto/desfavorável |
| modelo vs constante | 0.0005 | logistic_temporal-vs-constant | +0.055408 | -0.002913 | +0.014723 | +0.007126 | misto/desfavorável |
| orçamento | 0.0005 | mlp_event-vs-mlp20_event | -0.015126 | +0.036102 | +0.032662 | +0.003207 | misto/desfavorável |
| amostragem | 0.0005 | mlp_event-vs-mlp_temporal | -0.029910 | +0.009317 | +0.000846 | -0.002612 | misto/desfavorável |
| amostragem | 0.0005 | mlp20_event-vs-mlp20_temporal | -0.007683 | -0.026894 | -0.031816 | -0.005097 | ganho consistente |
| amostragem | 0.0005 | logistic_event-vs-logistic_temporal | -0.025515 | -0.000149 | -0.001370 | -0.003094 | ganho consistente |
| arquitetura | 0.0005 | mlp_event-vs-logistic_event | -0.024130 | +0.046499 | +0.039445 | +0.003718 | misto/desfavorável |
| arquitetura | 0.0005 | mlp20_event-vs-logistic_event | -0.009003 | +0.010396 | +0.006782 | +0.000511 | misto/desfavorável |
| modelo vs constante | 0.0005 | mlp_event-vs-constant | +0.005764 | +0.043437 | +0.052797 | +0.007750 | misto/desfavorável |
| modelo vs constante | 0.0005 | mlp20_event-vs-constant | +0.020890 | +0.007335 | +0.020135 | +0.004544 | misto/desfavorável |
| modelo vs constante | 0.0005 | logistic_event-vs-constant | +0.029894 | -0.003061 | +0.013353 | +0.004033 | misto/desfavorável |
| orçamento | 0.001 | mlp_temporal-vs-mlp20_temporal | +0.005552 | -0.000208 | +0.000000 | +0.000573 | misto/desfavorável |
| arquitetura | 0.001 | mlp_temporal-vs-logistic_temporal | -0.011261 | +0.036737 | +0.026887 | +0.003699 | misto/desfavorável |
| arquitetura | 0.001 | mlp20_temporal-vs-logistic_temporal | -0.016813 | +0.036945 | +0.026887 | +0.003126 | misto/desfavorável |
| modelo vs constante | 0.001 | mlp_temporal-vs-constant | +0.038169 | +0.033612 | +0.045372 | +0.010450 | misto/desfavorável |
| modelo vs constante | 0.001 | mlp20_temporal-vs-constant | +0.032617 | +0.033820 | +0.045372 | +0.009876 | misto/desfavorável |
| modelo vs constante | 0.001 | logistic_temporal-vs-constant | +0.049430 | -0.003124 | +0.018486 | +0.006751 | misto/desfavorável |
| orçamento | 0.001 | mlp_event-vs-mlp20_event | -0.011083 | +0.038906 | +0.038527 | +0.002933 | misto/desfavorável |
| amostragem | 0.001 | mlp_event-vs-mlp_temporal | -0.021694 | +0.011381 | +0.007774 | -0.002038 | misto/desfavorável |
| amostragem | 0.001 | mlp20_event-vs-mlp20_temporal | -0.005059 | -0.027734 | -0.030753 | -0.004397 | ganho consistente |
| amostragem | 0.001 | logistic_event-vs-logistic_temporal | -0.022442 | -0.001447 | -0.008762 | -0.003391 | ganho consistente |
| arquitetura | 0.001 | mlp_event-vs-logistic_event | -0.010514 | +0.049564 | +0.043422 | +0.005053 | misto/desfavorável |
| arquitetura | 0.001 | mlp20_event-vs-logistic_event | +0.000569 | +0.010658 | +0.004895 | +0.002119 | misto/desfavorável |
| modelo vs constante | 0.001 | mlp_event-vs-constant | +0.016474 | +0.044993 | +0.053146 | +0.008412 | misto/desfavorável |
| modelo vs constante | 0.001 | mlp20_event-vs-constant | +0.027557 | +0.006086 | +0.014619 | +0.005479 | misto/desfavorável |
| modelo vs constante | 0.001 | logistic_event-vs-constant | +0.026988 | -0.004571 | +0.009724 | +0.003359 | misto/desfavorável |

## Sensibilidade por remoção de semana

Faixas descritivas delete-one-entry-week UTC, nunca IC. Candidatos e labels sobrepostos não são independentes; remover semana não elimina toda dependência. Nenhum refit. Todas comparações abaixo e suportes semanais no JSON.

| Fold | Universo | Contraste | ΔLL | Faixa sem uma semana | ΔBrier | Faixa sem uma semana |
|---|---|---|---:|---|---:|---|
| 2023Q2 | temporal | mlp_temporal-vs-mlp20_temporal | +0.002390 | [+0.001742, +0.003278] | +0.000700 | [+0.000479, +0.001008] |
| 2023Q2 | temporal | mlp_temporal-vs-logistic_temporal | -0.021537 | [-0.025875, -0.013746] | -0.005491 | [-0.007022, -0.002658] |
| 2023Q2 | temporal | mlp20_temporal-vs-logistic_temporal | -0.023927 | [-0.028123, -0.015488] | -0.006191 | [-0.007654, -0.003138] |
| 2023Q2 | temporal | mlp_temporal-vs-constant | +0.023624 | [+0.018146, +0.034167] | +0.010404 | [+0.008493, +0.014197] |
| 2023Q2 | temporal | mlp20_temporal-vs-constant | +0.021233 | [+0.015898, +0.032426] | +0.009704 | [+0.007861, +0.013717] |
| 2023Q2 | temporal | logistic_temporal-vs-constant | +0.045161 | [+0.042265, +0.049970] | +0.015895 | [+0.014891, +0.017560] |
| 2023Q2 | 0.0005 | mlp_temporal-vs-mlp20_temporal | +0.007101 | [+0.005308, +0.007930] | +0.002357 | [+0.001775, +0.002612] |
| 2023Q2 | 0.0005 | mlp_temporal-vs-logistic_temporal | -0.019734 | [-0.027588, -0.006982] | -0.004958 | [-0.007797, -0.000336] |
| 2023Q2 | 0.0005 | mlp20_temporal-vs-logistic_temporal | -0.026835 | [-0.035517, -0.012290] | -0.007315 | [-0.010357, -0.002111] |
| 2023Q2 | 0.0005 | mlp_temporal-vs-constant | +0.035674 | [+0.028523, +0.050677] | +0.014674 | [+0.012079, +0.020155] |
| 2023Q2 | 0.0005 | mlp20_temporal-vs-constant | +0.028573 | [+0.020594, +0.045369] | +0.012317 | [+0.009518, +0.018380] |
| 2023Q2 | 0.0005 | logistic_temporal-vs-constant | +0.055408 | [+0.052173, +0.058792] | +0.019632 | [+0.018489, +0.020847] |
| 2023Q2 | 0.0005 | mlp_event-vs-mlp20_event | -0.015126 | [-0.020792, -0.004895] | -0.002765 | [-0.004266, +0.000745] |
| 2023Q2 | 0.0005 | mlp_event-vs-mlp_temporal | -0.029910 | [-0.032391, -0.026996] | -0.009578 | [-0.010408, -0.008627] |
| 2023Q2 | 0.0005 | mlp20_event-vs-mlp20_temporal | -0.007683 | [-0.020976, -0.002449] | -0.004456 | [-0.009233, -0.002583] |
| 2023Q2 | 0.0005 | logistic_event-vs-logistic_temporal | -0.025515 | [-0.027239, -0.024179] | -0.009458 | [-0.010063, -0.008943] |
| 2023Q2 | 0.0005 | mlp_event-vs-logistic_event | -0.024130 | [-0.032902, -0.010921] | -0.005079 | [-0.007620, -0.000536] |
| 2023Q2 | 0.0005 | mlp20_event-vs-logistic_event | -0.009003 | [-0.012110, -0.006027] | -0.002313 | [-0.003354, -0.001281] |
| 2023Q2 | 0.0005 | mlp_event-vs-constant | +0.005764 | [-0.002647, +0.019499] | +0.005096 | [+0.002670, +0.009892] |
| 2023Q2 | 0.0005 | mlp20_event-vs-constant | +0.020890 | [+0.018145, +0.024816] | +0.007861 | [+0.006936, +0.009166] |
| 2023Q2 | 0.0005 | logistic_event-vs-constant | +0.029894 | [+0.027994, +0.031916] | +0.010174 | [+0.009546, +0.010861] |
| 2023Q2 | 0.001 | mlp_temporal-vs-mlp20_temporal | +0.005552 | [+0.003885, +0.006843] | +0.001848 | [+0.001122, +0.002341] |
| 2023Q2 | 0.001 | mlp_temporal-vs-logistic_temporal | -0.011261 | [-0.022439, -0.000460] | -0.001794 | [-0.005839, +0.002351] |
| 2023Q2 | 0.001 | mlp20_temporal-vs-logistic_temporal | -0.016813 | [-0.028666, -0.004357] | -0.003642 | [-0.007774, +0.001016] |
| 2023Q2 | 0.001 | mlp_temporal-vs-constant | +0.038169 | [+0.029212, +0.050270] | +0.015792 | [+0.012494, +0.020407] |
| 2023Q2 | 0.001 | mlp20_temporal-vs-constant | +0.032617 | [+0.022985, +0.046373] | +0.013944 | [+0.010559, +0.019072] |
| 2023Q2 | 0.001 | logistic_temporal-vs-constant | +0.049430 | [+0.045790, +0.054032] | +0.017586 | [+0.016342, +0.019191] |
| 2023Q2 | 0.001 | mlp_event-vs-mlp20_event | -0.011083 | [-0.028056, -0.003382] | -0.002138 | [-0.006672, +0.000291] |
| 2023Q2 | 0.001 | mlp_event-vs-mlp_temporal | -0.021694 | [-0.030346, -0.014913] | -0.007626 | [-0.010699, -0.005280] |
| 2023Q2 | 0.001 | mlp20_event-vs-mlp20_temporal | -0.005059 | [-0.020576, +0.005598] | -0.003640 | [-0.009325, +0.000017] |
| 2023Q2 | 0.001 | logistic_event-vs-logistic_temporal | -0.022442 | [-0.024615, -0.020346] | -0.008368 | [-0.009163, -0.007606] |
| 2023Q2 | 0.001 | mlp_event-vs-logistic_event | -0.010514 | [-0.027131, -0.004191] | -0.001053 | [-0.005520, +0.000912] |
| 2023Q2 | 0.001 | mlp20_event-vs-logistic_event | +0.000569 | [-0.005180, +0.004980] | +0.001086 | [-0.001058, +0.002558] |
| 2023Q2 | 0.001 | mlp_event-vs-constant | +0.016474 | [+0.000528, +0.022415] | +0.008166 | [+0.003904, +0.010038] |
| 2023Q2 | 0.001 | mlp20_event-vs-constant | +0.027557 | [+0.022504, +0.033441] | +0.010304 | [+0.008391, +0.012490] |
| 2023Q2 | 0.001 | logistic_event-vs-constant | +0.026988 | [+0.025444, +0.029417] | +0.009218 | [+0.008736, +0.010027] |
| 2023Q3 | temporal | mlp_temporal-vs-mlp20_temporal | -0.001858 | [-0.002779, -0.001298] | -0.000858 | [-0.001206, -0.000550] |
| 2023Q3 | temporal | mlp_temporal-vs-logistic_temporal | +0.042556 | [+0.024452, +0.049270] | +0.010299 | [+0.006284, +0.011880] |
| 2023Q3 | temporal | mlp20_temporal-vs-logistic_temporal | +0.044413 | [+0.026081, +0.050836] | +0.011157 | [+0.007104, +0.012658] |
| 2023Q3 | temporal | mlp_temporal-vs-constant | +0.032647 | [+0.016640, +0.039580] | +0.007901 | [+0.004595, +0.009438] |
| 2023Q3 | temporal | mlp20_temporal-vs-constant | +0.034504 | [+0.018269, +0.041146] | +0.008759 | [+0.005416, +0.010216] |
| 2023Q3 | temporal | logistic_temporal-vs-constant | -0.009909 | [-0.012431, -0.007251] | -0.002398 | [-0.003252, -0.001593] |
| 2023Q3 | 0.0005 | mlp_temporal-vs-mlp20_temporal | -0.000109 | [-0.001495, +0.000683] | -0.000192 | [-0.000711, +0.000135] |
| 2023Q3 | 0.0005 | mlp_temporal-vs-logistic_temporal | +0.037033 | [+0.024855, +0.041498] | +0.009122 | [+0.006438, +0.010224] |
| 2023Q3 | 0.0005 | mlp20_temporal-vs-logistic_temporal | +0.037142 | [+0.025174, +0.041873] | +0.009314 | [+0.006604, +0.010333] |
| 2023Q3 | 0.0005 | mlp_temporal-vs-constant | +0.034120 | [+0.024551, +0.040483] | +0.008938 | [+0.007066, +0.010314] |
| 2023Q3 | 0.0005 | mlp20_temporal-vs-constant | +0.034229 | [+0.024870, +0.041089] | +0.009129 | [+0.007232, +0.010702] |
| 2023Q3 | 0.0005 | logistic_temporal-vs-constant | -0.002913 | [-0.008865, +0.000098] | -0.000184 | [-0.001615, +0.000722] |
| 2023Q3 | 0.0005 | mlp_event-vs-mlp20_event | +0.036102 | [+0.026316, +0.040463] | +0.008276 | [+0.006375, +0.009205] |
| 2023Q3 | 0.0005 | mlp_event-vs-mlp_temporal | +0.009317 | [+0.004883, +0.013857] | +0.001517 | [+0.000444, +0.002695] |
| 2023Q3 | 0.0005 | mlp20_event-vs-mlp20_temporal | -0.026894 | [-0.031173, -0.021017] | -0.006950 | [-0.007901, -0.005505] |
| 2023Q3 | 0.0005 | logistic_event-vs-logistic_temporal | -0.000149 | [-0.001668, +0.000805] | -0.000175 | [-0.000639, +0.000207] |
| 2023Q3 | 0.0005 | mlp_event-vs-logistic_event | +0.046499 | [+0.032142, +0.051353] | +0.010815 | [+0.007521, +0.012039] |
| 2023Q3 | 0.0005 | mlp20_event-vs-logistic_event | +0.010396 | [+0.005209, +0.014780] | +0.002539 | [+0.001146, +0.004031] |
| 2023Q3 | 0.0005 | mlp_event-vs-constant | +0.043437 | [+0.030169, +0.050379] | +0.010455 | [+0.007511, +0.012048] |
| 2023Q3 | 0.0005 | mlp20_event-vs-constant | +0.007335 | [+0.003853, +0.010057] | +0.002179 | [+0.001136, +0.002925] |
| 2023Q3 | 0.0005 | logistic_event-vs-constant | -0.003061 | [-0.008400, -0.000974] | -0.000360 | [-0.001579, +0.000222] |
| 2023Q3 | 0.001 | mlp_temporal-vs-mlp20_temporal | -0.000208 | [-0.001684, +0.001010] | -0.000128 | [-0.000685, +0.000297] |
| 2023Q3 | 0.001 | mlp_temporal-vs-logistic_temporal | +0.036737 | [+0.023246, +0.040476] | +0.009226 | [+0.006235, +0.010165] |
| 2023Q3 | 0.001 | mlp20_temporal-vs-logistic_temporal | +0.036945 | [+0.024115, +0.040977] | +0.009353 | [+0.006346, +0.010192] |
| 2023Q3 | 0.001 | mlp_temporal-vs-constant | +0.033612 | [+0.023006, +0.038901] | +0.008953 | [+0.006874, +0.010209] |
| 2023Q3 | 0.001 | mlp20_temporal-vs-constant | +0.033820 | [+0.023875, +0.039665] | +0.009081 | [+0.006985, +0.010783] |
| 2023Q3 | 0.001 | logistic_temporal-vs-constant | -0.003124 | [-0.011548, +0.001360] | -0.000272 | [-0.002117, +0.001023] |
| 2023Q3 | 0.001 | mlp_event-vs-mlp20_event | +0.038906 | [+0.027073, +0.048571] | +0.006628 | [+0.004155, +0.008693] |
| 2023Q3 | 0.001 | mlp_event-vs-mlp_temporal | +0.011381 | [+0.008415, +0.016828] | +0.000273 | [-0.000712, +0.001443] |
| 2023Q3 | 0.001 | mlp20_event-vs-mlp20_temporal | -0.027734 | [-0.032508, -0.018755] | -0.006483 | [-0.007572, -0.004440] |
| 2023Q3 | 0.001 | logistic_event-vs-logistic_temporal | -0.001447 | [-0.002917, +0.000298] | -0.000506 | [-0.000967, -0.000063] |
| 2023Q3 | 0.001 | mlp_event-vs-logistic_event | +0.049564 | [+0.035297, +0.058776] | +0.010004 | [+0.006490, +0.011899] |
| 2023Q3 | 0.001 | mlp20_event-vs-logistic_event | +0.010658 | [+0.007855, +0.016597] | +0.003376 | [+0.002335, +0.005342] |
| 2023Q3 | 0.001 | mlp_event-vs-constant | +0.044993 | [+0.032140, +0.055729] | +0.009226 | [+0.006162, +0.011542] |
| 2023Q3 | 0.001 | mlp20_event-vs-constant | +0.006086 | [+0.002316, +0.008738] | +0.002598 | [+0.001337, +0.003517] |
| 2023Q3 | 0.001 | logistic_event-vs-constant | -0.004571 | [-0.011250, -0.001526] | -0.000779 | [-0.002319, +0.000094] |
| 2023Q4 | temporal | mlp_temporal-vs-mlp20_temporal | +0.000000 | [+0.000000, +0.000000] | +0.000000 | [+0.000000, +0.000000] |
| 2023Q4 | temporal | mlp_temporal-vs-logistic_temporal | +0.048848 | [+0.037214, +0.054301] | +0.007064 | [+0.004832, +0.008241] |
| 2023Q4 | temporal | mlp20_temporal-vs-logistic_temporal | +0.048848 | [+0.037214, +0.054301] | +0.007064 | [+0.004832, +0.008241] |
| 2023Q4 | temporal | mlp_temporal-vs-constant | +0.068764 | [+0.054007, +0.077780] | +0.010069 | [+0.007489, +0.011646] |
| 2023Q4 | temporal | mlp20_temporal-vs-constant | +0.068764 | [+0.054007, +0.077780] | +0.010069 | [+0.007489, +0.011646] |
| 2023Q4 | temporal | logistic_temporal-vs-constant | +0.019917 | [+0.008185, +0.024620] | +0.003006 | [+0.000768, +0.004043] |
| 2023Q4 | 0.0005 | mlp_temporal-vs-mlp20_temporal | +0.000000 | [+0.000000, +0.000000] | +0.000000 | [+0.000000, +0.000000] |
| 2023Q4 | 0.0005 | mlp_temporal-vs-logistic_temporal | +0.037228 | [+0.030101, +0.043047] | +0.005545 | [+0.004035, +0.006716] |
| 2023Q4 | 0.0005 | mlp20_temporal-vs-logistic_temporal | +0.037228 | [+0.030101, +0.043047] | +0.005545 | [+0.004035, +0.006716] |
| 2023Q4 | 0.0005 | mlp_temporal-vs-constant | +0.051951 | [+0.036948, +0.058519] | +0.007476 | [+0.005629, +0.008675] |
| 2023Q4 | 0.0005 | mlp20_temporal-vs-constant | +0.051951 | [+0.036948, +0.058519] | +0.007476 | [+0.005629, +0.008675] |
| 2023Q4 | 0.0005 | logistic_temporal-vs-constant | +0.014723 | [+0.002278, +0.018506] | +0.001931 | [-0.000287, +0.002722] |
| 2023Q4 | 0.0005 | mlp_event-vs-mlp20_event | +0.032662 | [+0.022431, +0.037161] | +0.004109 | [+0.003031, +0.005010] |
| 2023Q4 | 0.0005 | mlp_event-vs-mlp_temporal | +0.000846 | [-0.003837, +0.003451] | +0.000224 | [-0.000695, +0.000676] |
| 2023Q4 | 0.0005 | mlp20_event-vs-mlp20_temporal | -0.031816 | [-0.035076, -0.026268] | -0.003885 | [-0.004706, -0.002694] |
| 2023Q4 | 0.0005 | logistic_event-vs-logistic_temporal | -0.001370 | [-0.002080, +0.001107] | +0.000352 | [+0.000226, +0.000665] |
| 2023Q4 | 0.0005 | mlp_event-vs-logistic_event | +0.039445 | [+0.029726, +0.046266] | +0.005417 | [+0.004434, +0.006794] |
| 2023Q4 | 0.0005 | mlp20_event-vs-logistic_event | +0.006782 | [+0.004847, +0.009106] | +0.001308 | [+0.000805, +0.001784] |
| 2023Q4 | 0.0005 | mlp_event-vs-constant | +0.052797 | [+0.033111, +0.060604] | +0.007700 | [+0.004934, +0.009092] |
| 2023Q4 | 0.0005 | mlp20_event-vs-constant | +0.020135 | [+0.010681, +0.023460] | +0.003591 | [+0.001903, +0.004247] |
| 2023Q4 | 0.0005 | logistic_event-vs-constant | +0.013353 | [+0.003385, +0.016439] | +0.002283 | [+0.000379, +0.002976] |
| 2023Q4 | 0.001 | mlp_temporal-vs-mlp20_temporal | +0.000000 | [+0.000000, +0.000000] | +0.000000 | [+0.000000, +0.000000] |
| 2023Q4 | 0.001 | mlp_temporal-vs-logistic_temporal | +0.026887 | [+0.021205, +0.032879] | +0.003666 | [+0.002359, +0.004733] |
| 2023Q4 | 0.001 | mlp20_temporal-vs-logistic_temporal | +0.026887 | [+0.021205, +0.032879] | +0.003666 | [+0.002359, +0.004733] |
| 2023Q4 | 0.001 | mlp_temporal-vs-constant | +0.045372 | [+0.033183, +0.051985] | +0.006604 | [+0.004967, +0.007725] |
| 2023Q4 | 0.001 | mlp20_temporal-vs-constant | +0.045372 | [+0.033183, +0.051985] | +0.006604 | [+0.004967, +0.007725] |
| 2023Q4 | 0.001 | logistic_temporal-vs-constant | +0.018486 | [+0.006128, +0.022280] | +0.002938 | [+0.000778, +0.003765] |
| 2023Q4 | 0.001 | mlp_event-vs-mlp20_event | +0.038527 | [+0.022946, +0.045627] | +0.004309 | [+0.001906, +0.006203] |
| 2023Q4 | 0.001 | mlp_event-vs-mlp_temporal | +0.007774 | [+0.001295, +0.010929] | +0.001240 | [-0.000060, +0.001789] |
| 2023Q4 | 0.001 | mlp20_event-vs-mlp20_temporal | -0.030753 | [-0.036544, -0.021651] | -0.003069 | [-0.004502, -0.001239] |
| 2023Q4 | 0.001 | logistic_event-vs-logistic_temporal | -0.008762 | [-0.010044, -0.005065] | -0.001300 | [-0.001561, -0.000806] |
| 2023Q4 | 0.001 | mlp_event-vs-logistic_event | +0.043422 | [+0.033414, +0.049551] | +0.006206 | [+0.004936, +0.007503] |
| 2023Q4 | 0.001 | mlp20_event-vs-logistic_event | +0.004895 | [+0.000783, +0.010468] | +0.001897 | [+0.000727, +0.003030] |
| 2023Q4 | 0.001 | mlp_event-vs-constant | +0.053146 | [+0.034478, +0.060173] | +0.007844 | [+0.004908, +0.009242] |
| 2023Q4 | 0.001 | mlp20_event-vs-constant | +0.014619 | [+0.011008, +0.017931] | +0.003535 | [+0.002480, +0.004355] |
| 2023Q4 | 0.001 | logistic_event-vs-constant | +0.009724 | [+0.001063, +0.012236] | +0.001638 | [-0.000028, +0.002204] |

## Cobertura, censura e dependência

Diagnósticos herdados de controles verificados: dados/candidatos/partições iguais. Denominadores incluem entradas não conclusivas; censura não é filtro causal disponível na entrada.

| Fold | Universo | Censura | Densidade | Cobertura retida temporal | Unicidade bruta média | Concorrência máxima |
|---|---|---:|---:|---:|---:|---:|
| 2023Q2 | temporal | 77.45% | 100.00% | 9.98% | 0.010134 | 422 |
| 2023Q2 | 0.0005 | 78.51% | 4.56% | 0.50% | 0.186567 | 25 |
| 2023Q2 | 0.001 | 78.17% | 1.34% | 0.17% | 0.454913 | 10 |
| 2023Q3 | temporal | 63.73% | 100.00% | 23.56% | 0.005541 | 1112 |
| 2023Q3 | 0.0005 | 57.69% | 4.76% | 1.54% | 0.084950 | 61 |
| 2023Q3 | 0.001 | 55.34% | 1.51% | 0.53% | 0.210625 | 22 |
| 2023Q4 | temporal | 51.13% | 100.00% | 35.89% | 0.004105 | 2317 |
| 2023Q4 | 0.0005 | 45.08% | 5.19% | 2.46% | 0.060905 | 100 |
| 2023Q4 | 0.001 | 44.14% | 1.66% | 0.83% | 0.165410 | 34 |

Aquecimento, contagens por classe, aberturas distintas, concorrência média ativa, unicidade bruta min/max e diagnósticos de todos treinos/internos constam do JSON. Unicidade não é tamanho amostral efetivo.

## Limitações e reprodução

Inferência inconclusiva: desenho informado, somente três externos, candidatos dependentes, censura alta e suporte positivo reduzido em partes das avaliações. Uma seed não demonstra robustez entre inicializações. Melhorar outro modelo sem superar constante não demonstra valor consistente das features. Resultados não descartam CUSUM ou redes neurais.

Classificação não demonstra lucro: bid-only, ausência de spread/comissão/swaps/slippage, lacunas e seleção pelos rótulos conclusivos. Temporal e eventos seguem linhas ativas. Nenhum avanço #6–#9 ou abertura de 2024.

Execução única (runner recusa ID já tentado ou output existente):

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.mlp_adam_budget
```

Previsões locais: `output/mlp_adam_budget_v1/predictions.csv`; SHA-256 `8da2428f53dc64d42b0575982d2284f5bc38beb17d7b816fdbdbd289e7ba6bfe`. Versões e hashes de código/fontes/configuração no agregado. Originais preservados. Revisão independente e CI executado no SHA final serão vinculados ao PR; sem merge automático.
