# session_models_v1 — retreino no dataset reconstruído

Autorizado por Léo após session_dataset_v1, em 14/09/2026. Este protocolo é
registrado antes de qualquer novo ajuste real. Objetivo: reavaliar os modelos
fixos com o contrato corrigido, sem selecionar configuração por resultados.

## Dados e divisão

Dataset congelado pelos hashes de dataset.npz e manifest.json na configuração.
Somente 2022–2023; não abrir preços/labels 2024, não rodar 2025 ou #6–#9.
Usar X/y, identidades, máscaras CUSUM e partições persistidas, verificadas contra
session_partitions. Nenhum novo label, feature ou filtro. TP50/SL20/<72 horas
abertas, gaps curtos tolerados, censura a partir de 15 minutos abertos.

Três externos Q2/Q3/Q4 de 2023. Fases internas meramente diagnósticas; os
internos Q3/Q4 repetem externos Q2/Q3, não evidência independente. Treino só no
passado, expurgo pelo horizonte completo de 72h abertas e buffer de 241 candles
observados. Avaliação restrita a horizontes anteriores ao fim do trimestre.

Unicidade média somente entre intervalos realizados das linhas de treino,
calculada no relógio de minutos de mercado aberto, normalizada para média 1.
Assim fechamento semanal também não ganha peso artificial por sua duração.
Gaps intrassessão tolerados continuam contando tempo. StandardScaler ponderado
é ajustado apenas nesse treino. Sem balanceamento, seleção, calibração ou PCA.

## Modelos congelados

Constante = média ponderada de y do treino temporal, compartilhada por todos
os universos de avaliação do mesmo passado. Logística L2 C=1, lbfgs, 1.000
iterações máximas, seed 0; parâmetros completos em config. Temporal, CUSUM
h=0.0005 e h=0.001 treinados separadamente, sem interseção ou ranking entre h.

MLP 28→16→1, ReLU/sigmoid, Adam, alpha=0.01, learning rate=0.001,
batch=min(1024,N), seed=0, mesma configuração do experimento anterior. Duas
paradas fixas: 20 épocas e orçamento comum de atualizações. O orçamento comum
é 20 vezes o máximo de ceil(N/batch) entre os quatro treinos temporais únicos;
derivado apenas do suporte, antes de scores. Nenhuma parada por validação.

Ambas usam o mesmo trainer incremental com limite exato de atualizações,
adaptado de mlp_adam_budget_v1. partial_fit mantém Adam; random_state inteiro
repete permutação após a primeira época, conforme comportamento da biblioteca.
Não é shuffle novo independente a cada época. Registrar épocas completas,
atualizações, exposições e loss; época parcial não comparável a loss completa.
Diagnóstico abs(última loss completa − penúltima)<1e-4 não prova convergência
nem muda a parada. ConvergenceWarning/falha numérica torna modelo indisponível;
sem fallback ou retry. Interrupção encerra execução. Python/NumPy/sklearn e
fontes privadas do otimizador fixados em config. CPU, BLAS/OpenMP=1.

## Orçamento e cache

Ledger existente: 48/1.000. Máximo 40 novos ajustes (4 passados × [1 constante,
3 logísticas, 3 MLP20, 3 MLPbudget]); máximo total 88. Nenhuma reinicialização
de ledger. Registrar cada tentativa antes de scaler/modelo, falhas consomem.
Cache por hash de X/y, identidades, intervalos, pesos, parâmetros, versões e
atualizações. Reutilizar entre folds somente com igualdade completa; cachear
falhas também. Quando MLP20 e MLPbudget têm exatamente as mesmas atualizações
e treino, são o mesmo ajuste: alias, zero fit adicional (esperado 39 únicos).
Não reutilizar controles antigos, nem aumentar orçamento após scores.

Viabilidade: treino não vazio, X/intervalos/pesos finitos, intervalos positivos;
logística/MLP exigem ambas classes. Sem piso arbitrário de linhas/positivos.
Uma classe permite constante. Impossibilidade técnica antes do fit não consome.

## Avaliação e artefatos

Em cada universo, mesma identidade/y para todos os modelos comparados.
Relatar constante, logística temporal, MLP20 temporal e MLPbudget temporal;
nos eventos acrescentar versões treinadas naquele h. Métricas não ponderadas:
log-loss, Brier, AP, ROC-AUC, precisão/recall em 0.3/0.4/0.5. Métrica indefinida
é null com motivo, nunca zero fabricado. Salvar previsões por fase/universo.

Contrastes: cada modelo contra constante; MLP contra logística na mesma
amostragem; eventos contra temporal na mesma arquitetura/parada; MLPbudget
contra MLP20. Sensibilidade delete-one-entry-week UTC de LL/Brier sem refit,
descritiva, não intervalo de confiança. Consistência descritiva requer LL menor
nos três externos e média dos deltas Brier <=0; fora disso misto/desfavorável.
Poucos regimes, desenho informado e censura mantêm inferência inconclusiva.
Reportar resultado negativo. Nunca classificar isso como evidência de lucro.

Salvar modelos/scalers em NPZ sem pickle, metadados por ajuste, hashes,
previsões e relatório agregado. Verificar reprodução de probabilidades pelos
pesos exportados. Dados volumosos ficam locais, agregados/evidências no Git.
Resultado não autoriza deployment, novas seeds ou busca de hiperparâmetros.

Antes dos ajustes: testes sintéticos de pesos com fechamento semanal,
isolamento do scaler, pareamento/cache/falha, persistência e parada exata,
equivalência a partial_fit nativo. unittest completo, compileall, diff --check.
