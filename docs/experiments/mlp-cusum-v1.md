# mlp_cusum_v1 — MLP temporal e CUSUM

Exploração informada após PR #14. MLP fixa 28→16→1, seed 0, 20 épocas; sem seleção de arquitetura/épocas. Desenvolvimento 2022–2023; 2024 fechado, nenhum uso de 2025 ou execução de #6–#9.

Pré-registro `e6f6004`; código executado `638d7410962ef323e55a071ee6c0535c7ccf393d`. Controles de cusum_temporal_v2 reutilizados após verificar hashes de fontes, implementação, contratos, identidades de treino/avaliação, pesos/prior e métricas das probabilidades preservadas. Nenhum controle reajustado.

Consumo: anterior 24; novo 12; global **36/1.000**, saldo **964**. Quatro passados únicos × três treinos. Refits Q2/Q3 reutilizados nos internos Q3/Q4 por igualdade de contrato completo, sem repetir fit.

[Protocolo](mlp-cusum-v1-protocol.md), [relatório agregado byte-exato](mlp-cusum-v1.json), [ledger](mlp-cusum-v1-ledger.jsonl), [hashes](mlp-cusum-v1-evidence.json). Previsões volumosas permanecem locais.

## Comparações externas

N = candidatos por lado; não observações independentes. Métodos de cada universo avaliam exatamente mesmas identidades. Não comparar scores entre limiares para ordená-los.

| Fold | Universo | N / positivos | Método | Log-loss | Brier | AP | ROC-AUC |
|---|---|---:|---|---:|---:|---:|---:|
| 2023Q2 | temporal | 12446 / 799 | logistic_temporal | 0.345569 | 0.090760 | 0.049443 | 0.411211 |
| 2023Q2 | temporal | 12446 / 799 | constant | 0.300409 | 0.074865 | 0.064197 | 0.500000 |
| 2023Q2 | temporal | 12446 / 799 | mlp_temporal | 0.321642 | 0.084569 | 0.077440 | 0.609169 |
| 2023Q2 | 0.0005 | 624 / 40 | logistic_temporal | 0.355677 | 0.094438 | 0.056432 | 0.397945 |
| 2023Q2 | 0.0005 | 624 / 40 | constant | 0.300269 | 0.074805 | 0.064103 | 0.500000 |
| 2023Q2 | 0.0005 | 624 / 40 | logistic_event | 0.330162 | 0.084980 | 0.058360 | 0.395334 |
| 2023Q2 | 0.0005 | 624 / 40 | mlp_temporal | 0.328842 | 0.087123 | 0.079747 | 0.594349 |
| 2023Q2 | 0.0005 | 624 / 40 | mlp_event | 0.321159 | 0.082666 | 0.060394 | 0.483005 |
| 2023Q2 | 0.001 | 207 / 15 | logistic_temporal | 0.362052 | 0.097645 | 0.056846 | 0.370139 |
| 2023Q2 | 0.001 | 207 / 15 | constant | 0.312622 | 0.080059 | 0.072464 | 0.500000 |
| 2023Q2 | 0.001 | 207 / 15 | logistic_event | 0.339610 | 0.089278 | 0.059527 | 0.362153 |
| 2023Q2 | 0.001 | 207 / 15 | mlp_temporal | 0.345239 | 0.094003 | 0.098255 | 0.601736 |
| 2023Q2 | 0.001 | 207 / 15 | mlp_event | 0.340180 | 0.090363 | 0.121075 | 0.561111 |
| 2023Q3 | temporal | 38577 / 6359 | logistic_temporal | 0.438190 | 0.135410 | 0.209733 | 0.602625 |
| 2023Q3 | temporal | 38577 / 6359 | constant | 0.448099 | 0.137808 | 0.164839 | 0.500000 |
| 2023Q3 | temporal | 38577 / 6359 | mlp_temporal | 0.482603 | 0.146567 | 0.143602 | 0.470021 |
| 2023Q3 | 0.0005 | 2517 / 413 | logistic_temporal | 0.444025 | 0.137135 | 0.185092 | 0.574903 |
| 2023Q3 | 0.0005 | 2517 / 413 | constant | 0.446938 | 0.137320 | 0.164084 | 0.500000 |
| 2023Q3 | 0.0005 | 2517 / 413 | logistic_event | 0.443876 | 0.136960 | 0.180802 | 0.569466 |
| 2023Q3 | 0.0005 | 2517 / 413 | mlp_temporal | 0.481167 | 0.146449 | 0.150302 | 0.482440 |
| 2023Q3 | 0.0005 | 2517 / 413 | mlp_event | 0.454272 | 0.139498 | 0.178367 | 0.543890 |
| 2023Q3 | 0.001 | 864 / 141 | logistic_temporal | 0.442444 | 0.136472 | 0.190225 | 0.580246 |
| 2023Q3 | 0.001 | 864 / 141 | constant | 0.445568 | 0.136744 | 0.163194 | 0.500000 |
| 2023Q3 | 0.001 | 864 / 141 | logistic_event | 0.440997 | 0.135966 | 0.188556 | 0.579981 |
| 2023Q3 | 0.001 | 864 / 141 | mlp_temporal | 0.479389 | 0.145825 | 0.152050 | 0.481240 |
| 2023Q3 | 0.001 | 864 / 141 | mlp_event | 0.451655 | 0.139342 | 0.183877 | 0.542950 |
| 2023Q4 | temporal | 65183 / 16449 | logistic_temporal | 0.607444 | 0.198756 | 0.292573 | 0.568253 |
| 2023Q4 | temporal | 65183 / 16449 | constant | 0.587528 | 0.195750 | 0.252351 | 0.500000 |
| 2023Q4 | temporal | 65183 / 16449 | mlp_temporal | 0.656292 | 0.205820 | 0.293428 | 0.550774 |
| 2023Q4 | 0.0005 | 4477 / 997 | logistic_temporal | 0.554846 | 0.178001 | 0.279225 | 0.589495 |
| 2023Q4 | 0.0005 | 4477 / 997 | constant | 0.540123 | 0.176070 | 0.222694 | 0.500000 |
| 2023Q4 | 0.0005 | 4477 / 997 | logistic_event | 0.553476 | 0.178353 | 0.279627 | 0.588840 |
| 2023Q4 | 0.0005 | 4477 / 997 | mlp_temporal | 0.592075 | 0.183546 | 0.259200 | 0.552714 |
| 2023Q4 | 0.0005 | 4477 / 997 | mlp_event | 0.560258 | 0.179661 | 0.258825 | 0.565557 |
| 2023Q4 | 0.001 | 1508 / 315 | logistic_temporal | 0.536539 | 0.169846 | 0.251591 | 0.571479 |
| 2023Q4 | 0.001 | 1508 / 315 | constant | 0.518053 | 0.166907 | 0.208886 | 0.500000 |
| 2023Q4 | 0.001 | 1508 / 315 | logistic_event | 0.527777 | 0.168546 | 0.254755 | 0.575686 |
| 2023Q4 | 0.001 | 1508 / 315 | mlp_temporal | 0.563425 | 0.173512 | 0.243419 | 0.553139 |
| 2023Q4 | 0.001 | 1508 / 315 | mlp_event | 0.532672 | 0.170443 | 0.218925 | 0.535893 |

## Resposta à pergunta científica

A MLP fixa não demonstrou melhoria consistente sobre logística e perdeu para constante em log-loss e Brier em todos os externos de todos os universos. O efeito descritivo da amostragem persistiu: MLP de eventos superou MLP temporal em log-loss nos três externos, com Brier médio menor, separadamente nos dois limiares. Isso não estabelece valor das features nem superioridade inferencial. Esse contraste mistura amostragem com quantidades diferentes de atualizações Adam e regularização efetiva: são ganhos do procedimento fixo de 20 épocas, sem isolar mecanismo causal ou demonstrar persistência independente da otimização. Ver tabela de atualizações e ressalva abaixo.

No temporal completo, MLP melhorou logística somente em Q2. Nos eventos h=0,0005, melhorou logística de eventos somente em Q2; em h=0,001, perdeu nos três externos. Nenhuma MLP venceu constante em log-loss ou Brier. Os 12 ajustes completaram épocas sem falha técnica, mas todos ficaram em training_loss_not_stabilized. Resultado vale para procedimento de 20 épocas e seed 0; não para redes neurais convergidas em geral.

**Universo temporal**:

- mlp_temporal-vs-logistic_temporal: `mixed_or_unfavorable_predictive_result`.
- mlp_temporal-vs-constant: `mixed_or_unfavorable_predictive_result`.
- logistic_temporal-vs-constant: `mixed_or_unfavorable_predictive_result`.

**Universo 0.0005**:

- mlp_temporal-vs-logistic_temporal: `mixed_or_unfavorable_predictive_result`.
- mlp_temporal-vs-constant: `mixed_or_unfavorable_predictive_result`.
- logistic_temporal-vs-constant: `mixed_or_unfavorable_predictive_result`.
- mlp_event-vs-logistic_event: `mixed_or_unfavorable_predictive_result`.
- mlp_event-vs-mlp_temporal: `consistent_descriptive_gain`.
- logistic_event-vs-logistic_temporal: `consistent_descriptive_gain`.
- mlp_event-vs-constant: `mixed_or_unfavorable_predictive_result`.
- logistic_event-vs-constant: `mixed_or_unfavorable_predictive_result`.

**Universo 0.001**:

- mlp_temporal-vs-logistic_temporal: `mixed_or_unfavorable_predictive_result`.
- mlp_temporal-vs-constant: `mixed_or_unfavorable_predictive_result`.
- logistic_temporal-vs-constant: `mixed_or_unfavorable_predictive_result`.
- mlp_event-vs-logistic_event: `mixed_or_unfavorable_predictive_result`.
- mlp_event-vs-mlp_temporal: `consistent_descriptive_gain`.
- logistic_event-vs-logistic_temporal: `consistent_descriptive_gain`.
- mlp_event-vs-constant: `mixed_or_unfavorable_predictive_result`.
- logistic_event-vs-constant: `mixed_or_unfavorable_predictive_result`.

Regra congelada: LL menor nos três externos e média dos deltas Brier ≤0. Resultado misto/desfavorável é resultado preditivo; ausência técnica e inferência inconclusiva são categorias distintas. Melhorar logística sem superar constante não demonstra valor consistente das features. Nenhum ranking ou escolha de limiar.

## Sensibilidade temporal de todos os contrastes

Δ = primeiro método − segundo; negativo favorece primeiro. Remover uma semana UTC de entradas, sem refit. Faixas descritivas, **não intervalos de confiança**. Labels podem atravessar semanas.

| Fold | Universo | Contraste | ΔLL | Faixa delete-week LL | ΔBrier | Faixa delete-week Brier |
|---|---|---|---:|---|---:|---|
| 2023Q2 | temporal | mlp_temporal-vs-logistic_temporal | -0.023927 | [-0.028123, -0.015488] | -0.006191 | [-0.007654, -0.003138] |
| 2023Q2 | temporal | mlp_temporal-vs-constant | +0.021233 | [0.015898, 0.032426] | +0.009704 | [0.007861, 0.013717] |
| 2023Q2 | temporal | logistic_temporal-vs-constant | +0.045161 | [0.042265, 0.049970] | +0.015895 | [0.014891, 0.017560] |
| 2023Q2 | 0.0005 | mlp_temporal-vs-logistic_temporal | -0.026835 | [-0.035517, -0.012290] | -0.007315 | [-0.010357, -0.002111] |
| 2023Q2 | 0.0005 | mlp_temporal-vs-constant | +0.028573 | [0.020594, 0.045369] | +0.012317 | [0.009518, 0.018380] |
| 2023Q2 | 0.0005 | logistic_temporal-vs-constant | +0.055408 | [0.052173, 0.058792] | +0.019632 | [0.018489, 0.020847] |
| 2023Q2 | 0.0005 | mlp_event-vs-logistic_event | -0.009003 | [-0.012110, -0.006027] | -0.002313 | [-0.003354, -0.001281] |
| 2023Q2 | 0.0005 | mlp_event-vs-mlp_temporal | -0.007683 | [-0.020976, -0.002449] | -0.004456 | [-0.009233, -0.002583] |
| 2023Q2 | 0.0005 | logistic_event-vs-logistic_temporal | -0.025515 | [-0.027239, -0.024179] | -0.009458 | [-0.010063, -0.008943] |
| 2023Q2 | 0.0005 | mlp_event-vs-constant | +0.020890 | [0.018145, 0.024816] | +0.007861 | [0.006936, 0.009166] |
| 2023Q2 | 0.0005 | logistic_event-vs-constant | +0.029894 | [0.027994, 0.031916] | +0.010174 | [0.009546, 0.010861] |
| 2023Q2 | 0.001 | mlp_temporal-vs-logistic_temporal | -0.016813 | [-0.028666, -0.004357] | -0.003642 | [-0.007774, 0.001016] |
| 2023Q2 | 0.001 | mlp_temporal-vs-constant | +0.032617 | [0.022985, 0.046373] | +0.013944 | [0.010559, 0.019072] |
| 2023Q2 | 0.001 | logistic_temporal-vs-constant | +0.049430 | [0.045790, 0.054032] | +0.017586 | [0.016342, 0.019191] |
| 2023Q2 | 0.001 | mlp_event-vs-logistic_event | +0.000569 | [-0.005180, 0.004980] | +0.001086 | [-0.001058, 0.002558] |
| 2023Q2 | 0.001 | mlp_event-vs-mlp_temporal | -0.005059 | [-0.020576, 0.005598] | -0.003640 | [-0.009325, 0.000017] |
| 2023Q2 | 0.001 | logistic_event-vs-logistic_temporal | -0.022442 | [-0.024615, -0.020346] | -0.008368 | [-0.009163, -0.007606] |
| 2023Q2 | 0.001 | mlp_event-vs-constant | +0.027557 | [0.022504, 0.033441] | +0.010304 | [0.008391, 0.012490] |
| 2023Q2 | 0.001 | logistic_event-vs-constant | +0.026988 | [0.025444, 0.029417] | +0.009218 | [0.008736, 0.010027] |
| 2023Q3 | temporal | mlp_temporal-vs-logistic_temporal | +0.044413 | [0.026081, 0.050836] | +0.011157 | [0.007104, 0.012658] |
| 2023Q3 | temporal | mlp_temporal-vs-constant | +0.034504 | [0.018269, 0.041146] | +0.008759 | [0.005416, 0.010216] |
| 2023Q3 | temporal | logistic_temporal-vs-constant | -0.009909 | [-0.012431, -0.007251] | -0.002398 | [-0.003252, -0.001593] |
| 2023Q3 | 0.0005 | mlp_temporal-vs-logistic_temporal | +0.037142 | [0.025174, 0.041873] | +0.009314 | [0.006604, 0.010333] |
| 2023Q3 | 0.0005 | mlp_temporal-vs-constant | +0.034229 | [0.024870, 0.041089] | +0.009129 | [0.007232, 0.010702] |
| 2023Q3 | 0.0005 | logistic_temporal-vs-constant | -0.002913 | [-0.008865, 0.000098] | -0.000184 | [-0.001615, 0.000722] |
| 2023Q3 | 0.0005 | mlp_event-vs-logistic_event | +0.010396 | [0.005209, 0.014780] | +0.002539 | [0.001146, 0.004031] |
| 2023Q3 | 0.0005 | mlp_event-vs-mlp_temporal | -0.026894 | [-0.031173, -0.021017] | -0.006950 | [-0.007901, -0.005505] |
| 2023Q3 | 0.0005 | logistic_event-vs-logistic_temporal | -0.000149 | [-0.001668, 0.000805] | -0.000175 | [-0.000639, 0.000207] |
| 2023Q3 | 0.0005 | mlp_event-vs-constant | +0.007335 | [0.003853, 0.010057] | +0.002179 | [0.001136, 0.002925] |
| 2023Q3 | 0.0005 | logistic_event-vs-constant | -0.003061 | [-0.008400, -0.000974] | -0.000360 | [-0.001579, 0.000222] |
| 2023Q3 | 0.001 | mlp_temporal-vs-logistic_temporal | +0.036945 | [0.024115, 0.040977] | +0.009353 | [0.006346, 0.010192] |
| 2023Q3 | 0.001 | mlp_temporal-vs-constant | +0.033820 | [0.023875, 0.039665] | +0.009081 | [0.006985, 0.010783] |
| 2023Q3 | 0.001 | logistic_temporal-vs-constant | -0.003124 | [-0.011548, 0.001360] | -0.000272 | [-0.002117, 0.001023] |
| 2023Q3 | 0.001 | mlp_event-vs-logistic_event | +0.010658 | [0.007855, 0.016597] | +0.003376 | [0.002335, 0.005342] |
| 2023Q3 | 0.001 | mlp_event-vs-mlp_temporal | -0.027734 | [-0.032508, -0.018755] | -0.006483 | [-0.007572, -0.004440] |
| 2023Q3 | 0.001 | logistic_event-vs-logistic_temporal | -0.001447 | [-0.002917, 0.000298] | -0.000506 | [-0.000967, -0.000063] |
| 2023Q3 | 0.001 | mlp_event-vs-constant | +0.006086 | [0.002316, 0.008738] | +0.002598 | [0.001337, 0.003517] |
| 2023Q3 | 0.001 | logistic_event-vs-constant | -0.004571 | [-0.011250, -0.001526] | -0.000779 | [-0.002319, 0.000094] |
| 2023Q4 | temporal | mlp_temporal-vs-logistic_temporal | +0.048848 | [0.037214, 0.054301] | +0.007064 | [0.004832, 0.008241] |
| 2023Q4 | temporal | mlp_temporal-vs-constant | +0.068764 | [0.054007, 0.077780] | +0.010069 | [0.007489, 0.011646] |
| 2023Q4 | temporal | logistic_temporal-vs-constant | +0.019917 | [0.008185, 0.024620] | +0.003006 | [0.000768, 0.004043] |
| 2023Q4 | 0.0005 | mlp_temporal-vs-logistic_temporal | +0.037228 | [0.030101, 0.043047] | +0.005545 | [0.004035, 0.006716] |
| 2023Q4 | 0.0005 | mlp_temporal-vs-constant | +0.051951 | [0.036948, 0.058519] | +0.007476 | [0.005629, 0.008675] |
| 2023Q4 | 0.0005 | logistic_temporal-vs-constant | +0.014723 | [0.002278, 0.018506] | +0.001931 | [-0.000287, 0.002722] |
| 2023Q4 | 0.0005 | mlp_event-vs-logistic_event | +0.006782 | [0.004847, 0.009106] | +0.001308 | [0.000805, 0.001784] |
| 2023Q4 | 0.0005 | mlp_event-vs-mlp_temporal | -0.031816 | [-0.035076, -0.026268] | -0.003885 | [-0.004706, -0.002694] |
| 2023Q4 | 0.0005 | logistic_event-vs-logistic_temporal | -0.001370 | [-0.002080, 0.001107] | +0.000352 | [0.000226, 0.000665] |
| 2023Q4 | 0.0005 | mlp_event-vs-constant | +0.020135 | [0.010681, 0.023460] | +0.003591 | [0.001903, 0.004247] |
| 2023Q4 | 0.0005 | logistic_event-vs-constant | +0.013353 | [0.003385, 0.016439] | +0.002283 | [0.000379, 0.002976] |
| 2023Q4 | 0.001 | mlp_temporal-vs-logistic_temporal | +0.026887 | [0.021205, 0.032879] | +0.003666 | [0.002359, 0.004733] |
| 2023Q4 | 0.001 | mlp_temporal-vs-constant | +0.045372 | [0.033183, 0.051985] | +0.006604 | [0.004967, 0.007725] |
| 2023Q4 | 0.001 | logistic_temporal-vs-constant | +0.018486 | [0.006128, 0.022280] | +0.002938 | [0.000778, 0.003765] |
| 2023Q4 | 0.001 | mlp_event-vs-logistic_event | +0.004895 | [0.000783, 0.010468] | +0.001897 | [0.000727, 0.003030] |
| 2023Q4 | 0.001 | mlp_event-vs-mlp_temporal | -0.030753 | [-0.036544, -0.021651] | -0.003069 | [-0.004502, -0.001239] |
| 2023Q4 | 0.001 | logistic_event-vs-logistic_temporal | -0.008762 | [-0.010044, -0.005065] | -0.001300 | [-0.001561, -0.000806] |
| 2023Q4 | 0.001 | mlp_event-vs-constant | +0.014619 | [0.011008, 0.017931] | +0.003535 | [0.002480, 0.004355] |
| 2023Q4 | 0.001 | logistic_event-vs-constant | +0.009724 | [0.001063, 0.012236] | +0.001638 | [-0.000028, 0.002204] |

## Otimização e suporte técnico

| Fit original | N / positivos | Status | Épocas / atualizações | Diagnóstico de loss |
|---|---:|---|---:|---|
| 2023Q2:inner:temporal | 378214 / 93309 | succeeded | 20 / 7400 | training_loss_not_stabilized |
| 2023Q2:inner:0.0005 | 45254 / 11154 | succeeded | 20 / 900 | training_loss_not_stabilized |
| 2023Q2:inner:0.001 | 16492 / 4050 | succeeded | 20 / 340 | training_loss_not_stabilized |
| 2023Q2:refit:temporal | 437752 / 105985 | succeeded | 20 / 8560 | training_loss_not_stabilized |
| 2023Q2:refit:0.0005 | 50712 / 12319 | succeeded | 20 / 1000 | training_loss_not_stabilized |
| 2023Q2:refit:0.001 | 18460 / 4469 | succeeded | 20 / 380 | training_loss_not_stabilized |
| 2023Q3:refit:temporal | 451267 / 106787 | succeeded | 20 / 8820 | training_loss_not_stabilized |
| 2023Q3:refit:0.0005 | 51400 / 12359 | succeeded | 20 / 1020 | training_loss_not_stabilized |
| 2023Q3:refit:0.001 | 18686 / 4484 | succeeded | 20 / 380 | training_loss_not_stabilized |
| 2023Q4:refit:temporal | 490276 / 113146 | succeeded | 20 / 9580 | training_loss_not_stabilized |
| 2023Q4:refit:0.0005 | 53940 / 12772 | succeeded | 20 / 1060 | training_loss_not_stabilized |
| 2023Q4:refit:0.001 | 19556 / 4625 | succeeded | 20 / 400 | training_loss_not_stabilized |

Completar 20 épocas não prova convergência. No caminho `partial_fit`, scikit-learn não emite `ConvergenceWarning` por atingir limite de iterações; capturar esse aviso é proteção defensiva, não teste de convergência executado. O diagnóstico de otimização publicado é exclusivamente a variação de loss pré-registrada, além das verificações de finitude. Diagnóstico usa apenas diferença absoluta entre duas últimas losses de treino <1e-4; não altera treinamento nem seleção. Curvas completas, pesos e hashes do scaler/contrato no JSON. Batch size igual à regra congelada não iguala quantidade de atualizações nem regularização efetiva entre amostras de tamanhos diferentes.

## Cobertura, censura e dependência

Diagnósticos copiados do controle verificado, pois candidatos, partições e labels são idênticos. Incluem todos candidatos observados antes de descarte; censura não vira filtro ex ante.

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

Internos e todos thresholds fixos 0,3/0,4/0,5, motivos de métricas indefinidas, classes, aquecimento, concorrência média ativa e unicidade bruta min/max estão no JSON. Internos Q3/Q4 repetem externos Q2/Q3; não são confirmação adicional.

## Limitações e reprodução

Inferência permanece inconclusiva: dependência de labels, apenas três trimestres, poucos positivos em partes dos dados, alta censura e desenho informado pelos resultados anteriores. Seed 0 não demonstra robustez entre inicializações. Resultado negativo ou otimização limitada não descarta redes neurais ou CUSUM. Temporal e eventos permanecem linhas ativas.

Classificação não demonstra lucro: bid-only, ausência de spread/comissões/swaps/slippage, lacunas e seleção pelos rótulos conclusivos. Nenhuma execução econômica foi feita.

Execução única:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.mlp_comparison
```

SHA-256 das previsões locais: `1d48f789c4f6c11759e79c7adff16625e14c4504e5429ce2673ab9c9fcb0b4d2`. Caminho: `output/mlp_cusum_v1/predictions.csv`. Fontes, versões e SHA executado constam no relatório e em cada tentativa do ledger.

103 testes sintéticos completos, compileall e git diff --check são executados na entrega. Revisão independente e CI do SHA final registrados no PR; nenhum merge automático.
