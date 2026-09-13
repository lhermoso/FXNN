# afml_v1 — protocolo pré-registrado

Registrado antes de qualquer treino AFML em dados reais. Auditoria descritiva
universe_v1 precede este protocolo. Branch parte de 82efcb0 (neural_v1 local);
não pressupõe que neural_v1 já esteja integrado na principal.

## Hipótese e orçamento

Acrescentar memória de log-preço às 28 features melhora log-loss da logística?
Uma execução, três folds externos (julho, agosto, setembro de 2025), sempre com
mês anterior como validação interna. Outubro–dezembro não entram nos modelos.
Meses externos já vistos: resultado exploratório. Não variar TP/SL, thresholds,
arquitetura, regularização, grade ou janela após olhar resultados.

Por fold: quatro ajustes internos completos (controle e três d), 31 ajustes SFI
(28 features antigas e uma para cada d), dois refits externos (controle e melhor d).
Total máximo: 111 ajustes logísticos; constante e fallback reutilizam prior/modelo.
Permutação não ajusta modelos: 3 repetições por família, blocos de 128 linhas,
seed igual ao mês externo. Falha técnica interrompe execução; eventual correção
é documentada, não permite nova tentativa estatística ou mudança de hipótese.

## Transformação e candidatos

Para d em [0.25, 0.50, 0.75], w0=1 e wk=-w(k-1)*(d-k+1)/k.
Parar antes do primeiro peso com módulo <1e-4. Máximo de 1440 coeficientes;
se não atingir corte, abortar, sem truncamento silencioso. Não renormalizar pesos.
Janelas resultantes: 445, 200, 79 candles, respectivamente. d=0/1 somente testes.

Na entrada t: FFD(t)=soma_k wk*log(close[t-1-k]). Acrescentar uma coluna
orientada pela direção proposta: side*FFD(t). Não adicionar nível bruto separado.
Exigir continuidade M1 de t-L até t inclusive; depois de lacuna reiniciar janela.
Critérios antigos e labels inalterados. Nenhum preenchimento de preços/retornos.

Aplicar [regra de elegibilidade](afml-eligibility.md): interseção das três
configurações e features antigas antes de qualquer comparação. Mesmas identidades
em todos os modelos de cada partição. Buffer comum max(241,445,200,79)=445 minutos,
calculado no código dos históricos efetivos. Expurgo conservador entrada+72h;
fronteira direita igual ao baseline. Mínimo de 100 linhas por partição; abortar
se faltar suporte, sem relaxar elegibilidade. Unicidade recalculada no treino comum.

## Modelo e seleção

Reusar Baseline: logística C=1, max_iter=1000, random_state=0, scaler ponderado
ajustado no treino, sem balanceamento de classe. Escolher melhor d pela menor
log-loss interna; empate exato favorece menor d. Sempre relatar externamente
controle, constante e melhor d interno. Pipeline adaptativo usa melhor d somente
se vencer controle internamente; caso contrário reutiliza controle. Nenhuma família
é excluída neste experimento. Permutação e SFI não alteram seleção/modelos.
Refazer scaler, unicidade e modelos no passado autorizado antes do mês externo.

## Diagnósticos somente internos

Permutar famílias do controle e de cada representação na validação interna.
SFI: ajustar cada coluna isoladamente no treino e medir todas as métricas na
validação interna; comparar com constante do mesmo treino. Ausência de sinal
isolado não descarta interações. Relatar estabilidade entre os três folds, sem
usar resumo de folds para alterar seleções anteriores ou posteriores.
Redundância: correlação de Pearson no treino entre cada coluna nova orientada e
cada feature antiga; registrar maior correlação absoluta e nome da feature.

Estacionariedade/memória: usar somente índices únicos do treino interno, na maior
sequência M1 contínua (empate: primeira), até 5000 observações iniciais. Mínimo 100;
se não houver, registrar indisponível. Sem concatenar lacunas ou duplicar long/short.
Aplicar ADF (statsmodels 0.14.6) com intercepto, maxlag=1 e autolag=None ao log-preço
fechado anterior e a cada FFD não orientada. Relatar estatística, p e críticos;
correlação FFD/log-preço nas mesmas observações como proxy descritiva de memória.
Não escolher d por ADF. ADF/correlação não demonstram previsibilidade e não resumem
todos os regimes; nenhuma alegação de significância a partir de candidatos sobrepostos.

## Registro e conclusão

Guardar todas as métricas internas, SFI e permutações; log-loss primária, Brier,
AP, ROC-AUC, suporte e precisão/recall em 0.3/0.4/0.5 externos. Relatar por mês
exclusões adicionais, classes e filtros de fronteira. Comparação usa mesmas linhas.
Preservar previsões dos modelos externos, parâmetros ajustados, pesos/scalers,
hashes de inputs/código/protocolo, versões e tempo em output/afml_v1, fora do Git.
Versionar relatório agregado; baselines anteriores inalterados.

Conclusão descritiva: ganho consistente somente se melhor d interno superar
controle em log-loss nos três meses externos; relatar também constante e fallback.
Sem alegação de lucro. Mesmo ganho consistente requer dados novos, bid/ask, custos,
tratamento operacional de censura e simulação causal antes de validação econômica.

## Referências consultadas

- López de Prado, AFML (2018), cap. 5, §§5.5–5.6; descrição e fórmula em
  [MLFinLab](https://random-docs.readthedocs.io/en/latest/implementations/frac_diff.html)
  e [Mlfin.py](https://mlfinpy.readthedocs.io/en/stable/FractionalDifferentiated.html).
- [ADF, statsmodels 0.14.6](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html).
- Documentação atual NumPy, scikit-learn e statsmodels consultada via chub.
