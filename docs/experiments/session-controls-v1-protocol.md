# session_controls_v1 — controles pareados de prior e regularização

Pré-registro autorizado por Léo em 14/09/2026, após conhecer session_models_v1
(e auditoria registrada em ba2368a). Este experimento explora mecanismos do
ganho CUSUM; não confirma previsibilidade em dados intocados. Código, configuração
e este protocolo devem estar no Git antes de qualquer ajuste real.

## Contrato congelado e controles

EURUSD M1 de 2022–2023; session_dataset_v1 exclusivamente. TP50/SL20, TP antes de
72 horas abertas. Domingo 17h–sexta 17h America/New_York, DST histórico;
fechamento semanal pausa relógio, gaps intrassessão não. Até 14 ausências
consecutivas toleradas; censura ao completar 15. Nenhum candle/preço sintético.
Features usam apenas candles anteriores à entrada, janelas por observações.
Preservar todas as 28 features, labels, máscaras h=0.0005/h=0.001, pesos,
partições, candidatos excluídos e controles. Nunca escolher apenas vencedoras.

Usar loader/splits de sessão com expurgo do horizonte completo e buffer das
241 observações. Verificar partições persistidas contra cálculo original.
Configuração fixa hashes do dataset, manifesto, candidatos, evidências,
relatório e verificação anteriores. Antes de novos ajustes, conferir contratos
X/y, identidades, intervalos, pesos, versões, scalers/prior e modelos dos
controles reutilizados; confrontar ledger e reproduzir suas previsões/métricas
pareadas. Fontes do commit executado 51b6f22 devem corresponder aos hashes;
única divergência permitida no checkout é whitespace de session_neural.py com
AST idêntica. Isso não exige retreino.

## Intervenções fixas

Para cada um dos quatro passados únicos e cada h, somente:

1. Constante própria: média ponderada de y no treino CUSUM daquele h.
2. Logística CUSUM L2 com C_event=N_temporal/N_event, contando apenas treino.

Unicidade em minutos abertos, calculada entre intervalos realizados do próprio
treino, pesos normalizados para média 1; scaler ponderado ajustado nesse treino.
Mesmos parâmetros da logística original, exceto C: lbfgs, intercepto, L2,
max_iter=1000, tol=1e-4, seed=0. Parâmetros completos na configuração JSON.
Nenhuma busca, threshold novo, mudança de features, arquitetura ou calibração.

sklearn 1.8.0 instalado usa l2_reg_strength=1/(C*sum(sample_weight)); fonte
_logistic.py fixada por hash. Como soma dos pesos=N (tolerância numérica
relativa 1e-12), C_event iguala penalização relativa à loss média do temporal
C=1. Isso iguala coeficiente em coordenadas padronizadas; não iguala geometria
do scaler, população, diversidade, ruído, duração dos labels ou solução do
modelo. Nem isola causalmente toda contribuição do prior na logística.
Documentação consultada via chub: scikit-learn/package e numpy/package;
regra também conferida na implementação local.

## Pareamento, métricas e interpretação

Para cada fase interna/refit e cada h, mesmas identidades e y entre:
constante temporal antiga, logística temporal antiga, logística CUSUM original,
constante própria nova e logística CUSUM de penalização equivalente nova.
Reutilizar controles antigos, sem copiá-los como novos fits. Avaliar somente
universos de eventos; nenhum ranking entre h.

Contrastes (A menos B, negativo favorece A em LL/Brier):

- Logística CUSUM original − constante própria.
- Logística equivalente − logística CUSUM original.
- Logística equivalente − logística temporal.
- Logística equivalente − constante própria.
- Constante própria − constante temporal (diagnóstico direto de prior).

LL/Brier não ponderados primários. AUC/AP, precisão/recall nos thresholds já
fixos 0.3/0.4/0.5 e nível/dispersão de probabilidades são diagnósticos. Registrar
média, desvio padrão populacional, mínimo/máximo e quantis 5/25/50/75/95%.
Null com motivo para métricas indefinidas. Sensibilidade delete-one-entry-week
UTC sem refit é descritiva; não intervalo de confiança nem teste estatístico.

Critério descritivo inalterado: LL estritamente menor nos três externos
Q2/Q3/Q4 e média simples dos deltas Brier <=0. Caso contrário, misto/desfavorável.
Internos repetidos não são novas replicações. Não escolher configuração,
threshold, modelo, sinal invertido, trimestre ou universo após scores.

Se ganho persistir com penalização igual, enfraquece hipótese de que diferença
de L2 seja necessária para ganho original. Se desaparecer, regularização ganha
sustentação como mecanismo, sem prova exclusiva. Superar constante própria é
requisito descritivo para sustentar contribuição além daquele prior; ausência
de ganho consistente enfraquece essa hipótese. Constantes próprias próximas
às temporais com scores mistos enfraquecem explicação exclusiva por prior.
Nenhum desses contrastes decompõe completamente ganho CUSUM em efeitos causais.

## Orçamento e execução única

Ledger canônico /Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl,
consumo inicial confirmado 87/1.000; hash na configuração. Máximo 16 novos
ajustes: 8 constantes + 8 logísticas; teto final 103/1.000. Registrar tentativa
antes de scaler/estimador/constante. Falhas também consomem. Sem reinicializar,
truncar, ocultar, refazer ajuste ou aumentar orçamento.

Cache entre fases/folds somente por contrato idêntico: X/y, identidades,
intervalos, pesos, features, versões, parâmetros, suporte/identidades temporais
e hash do runner. Falhas cacheadas; interrupção aborta execução. Falha de
convergência/numerical invalida aquele modelo, sem fallback; comparações
incompletas indisponíveis. Treino vazio/inválido é indisponível antes do fit;
constante permite uma classe, logística exige ambas.

Executar uma vez em output/session_controls_v1 novo, Git limpo e código
registrado. CPU, OMP/OPENBLAS/MKL/VECLIB threads=1 antes de iniciar Python.
Salvar modelos/scalers NPZ sem pickle, metadados, previsões pareadas, contratos,
hashes, relatório agregado e snapshots completos do ledger. Reabrir e reproduzir
todas as probabilidades, métricas, diagnósticos e contrastes; verificar fórmula
C, scaler/prior somente no treino e vínculo de cada fit ao ledger. Dados,
modelos e previsões volumosas somente locais; agregados/evidências no Git.

Antes do fit real: testes sintéticos de fórmula, isolamento, cache, persistência,
falha sem retry, pareamento e orçamento; suíte unittest completa e diff --check.

## Limitações e reservas

Externos já vistos são exploratórios. Sobreposição e poucos regimes impedem
tratar linhas como amostras independentes. Censura externa após corte de
horizonte: Q2 74,84%, Q3 27,24%, Q4 4,39%; não excluir Q2 nem atribuir toda
instabilidade a ele. Máscaras/pesos mudam população e distribuição-alvo;
universo conclusivo depende de resultado futuro de observabilidade. Bid-only,
sem custos/ask/execução: classificação não prova lucro.

2024 reservado sem abrir preços ou labels; não executar 2025 ou etapas #6–#9.
Sem merge, novas seeds, retreino dos controles ou ampliação de busca.
