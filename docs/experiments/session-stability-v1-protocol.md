# session_stability_v1 — estabilidade e observabilidade, zero fits

Pré-registro após session_controls_v1, HEAD inicial 25c050e. Diagnóstico
exploratório autorizado por Léo; protocolo/configuração/código serão commitados
antes de calcular qualquer diagnóstico real novo. Sem seleção ou nova busca.

## Contrato e segurança

Somente session_dataset_v1 e fontes HistData EURUSD M1 bid 2022–2023 verificadas.
TP50/SL20, TP antes de 4.320 minutos abertos, domingo 17h–sexta 17h Nova York
com DST histórico. Fechamento semanal pausa relógio; gaps intrassessão não.
Até 14 ausências toleradas, censura ao completar 15. Sem fill/candles sintéticos,
novos labels, features, filtros, máscaras, arquitetura ou alteração de pesos.
Janelas por observações, OHLC só até t−1. Não selecionar vencedoras.
2024 fechado; nenhum 2025, #6–#9, estratégia, merge ou alegação de lucro.

Ledger canônico permanece byte a byte igual: 103/1.000, SHA-256
3e9ed64b3307b346e0108e8710ceb8031d93645b4504065f5de6ef76f058a2d1.
ZERO fits de pesquisa, inclusive constantes, scalers e auxiliares. Runner
bloqueia chamadas Python fit/partial_fit e métodos de escrita do FitLedger;
protege ledger/entradas congeladas contra abertura para escrita. Estatísticas
descritivas não substituem nem modificam modelos exportados. Suíte histórica
obrigatória contém ajustes apenas sintéticos em fixtures/ledgers temporários;
o runner novo e seus testes não precisam de ajuste algum.

Config fixa hashes de todos os artefatos anteriores, código existente, famílias,
fontes e referências. Git inicialmente limpo nos dois checkouts. Conferir hashes
antes/depois, cadeia e bytes do ledger; fontes somente 2022–2023. Destino novo
output/session_stability_v1. Sem dados/modelos/previsões volumosos no Git.

## A. Distribuição: 18 pares, 28 features, sem testes de hipótese

Para cada fold Q2/Q3/Q4, fases inner (train→validation) e refit (refit→test),
preservar splits persistidos/recalculados pelo loader de sessão. Três universos
separados: temporal, CUSUM 0.0005, CUSUM 0.001, treino e avaliação no mesmo
universo. Internos Q3/Q4 repetem externos Q2/Q3: aliases explícitos, não replicações.

Cinco famílias originais: movement, volatility, position, path, context;
lista e índices completos na configuração. Todas as features serão reportadas.
Para cada treino calcular duas referências separadas: pesos originais de
unicidade média em minutos abertos (normalizados para média 1) e pesos uniformes.
Avaliação sempre não ponderada. Três estatísticas antecipadas:

1. (média avaliação − média treino)/desvio populacional treino.
2. Desvio populacional avaliação/desvio populacional treino.
3. Fração avaliação estritamente fora de [q05, q95] do treino; registrar também
   fração do próprio treino fora do intervalo, sem presumir 10% quando há empates.

Quantis: inversa da CDF empírica ponderada, primeiro valor cuja soma acumulada
de pesos alcança q, inclusive na referência uniforme. Nenhum bin aprendido no
teste. Registrar médias, desvios e quantis de referência em unidades originais.
Desvio treino zero → estatísticas normalizadas null com motivo, sem epsilon
arbitrário; referência de caudas ainda válida. Grupo vazio → null com motivo.
Sem limiar de drift significativo, p-valores ou intervalos de confiança.

## B. Contribuições de logísticas congeladas

Temporal em todas as avaliações; CUSUM original/equivalente nas mesmas entradas
de cada h. Total 42 avaliações de modelos (6 fases × [1+3+3]). Reabrir modelos,
scalers e previsões NPZ sem pickle; conferir hashes, contratos de treino, pesos,
identidades e ligação ao ledger. Não abrir MLP para novos diagnósticos.

Para cada linha: c_g = Σ_j∈g coef_j·(X_j−mean_j)/scale_j;
logit = intercepto + Σ_g c_g. Reconstruir numericamente logit/probabilidade,
comparando produto matricial e previsão persistida (rtol/atol 1e-12).
Guardar erro máximo, intercepto, suportes, identidade e modelo de origem.

Todas as cinco famílias: média, desvio populacional e quantis 5/50/95 das
contribuições, total e por classe observada (0/1), no treino completo ponderado,
treino uniforme e avaliação trimestral uniforme. Associação descritiva = média
c_g em y=1 menos média em y=0. Mudança de sinal descreve instabilidade observada;
não exige significância nem implica mecanismo. Reportar todas, inclusive nulas.
Treinos cumulativos não serão fragmentados retrospectivamente por resultado.

Remover cada família individualmente do logit da avaliação, preservando
intercepto/coeficientes/scaler. Calcular ΔLL e ΔBrier = loss removida − original;
positivo significa que remoção prejudica score naquele conjunto. LL em logits
via logaddexp; Brier via sigmoid. Conferir loss original com score persistido.
Zero padronizado é média ponderada daquele treino. Não combinar remoções,
retreinar, inverter sinais, escolher subconjunto ou avaliar estratégia resultante.
LL/Brier não são aditivos por família; deltas não são decomposição exata da
loss. Correlações impedem atribuição exclusiva/causal.

## C. Seleção por observabilidade

Schema inspecionado: candidates.npz contém outcomes/valid/conclusive/retained,
identidades, horizonte e máscaras, mas não X. Reconstruir mesmas features com
session_features/orient_features e fontes verificadas; não chamar rotulador.
Conferir exatamente X nas 1.105.737 linhas retidas, histórico válido e máscaras
CUSUM em todos os candidatos. Histórico inválido não recebe X imputado: valores
indisponíveis permanecem NaN em memória e nunca entram nas comparações.

Quatro trimestres únicos avaliados em 2023 (Q1 interno e Q2/Q3/Q4 externos),
três universos separados. Candidatos: início dentro do trimestre e info_ends
estritamente anterior ao fim, idêntico ao corte da avaliação. Registrar contagem
antes do corte e removidos pelo horizonte. Não usar duração realizada no corte.

Tabela completa por outcome × histórico válido/inválido: censored, take_profit,
stop_loss, timeout, ambiguous, boundary, mesmo que zero. Retidos = conclusivos
com histórico válido; verificar identidades contra avaliação de cada universo.
Taxa de censura sobre todos após corte e sobre conclusivos+censurados válidos
serão separadas. Ambíguos/boundary/histórico inválido não somem no denominador.

Comparação principal: conclusivos válidos vs censurados válidos, sem atribuir
y aos censurados. Para cada uma das 28 features, média/desvio e as mesmas três
estatísticas de A, em referência ao passado de treino daquele trimestre/universo,
ponderado e uniforme. Acrescentar diferença de médias censurados−conclusivos
em unidades de desvio do treino. Referência Q1=train Q2; Q2/Q3/Q4=refit respectivo.
Nenhum cálculo de prevalência ausente, classificador de censura ou reponderação.
Diferenças são observáveis antes da entrada, associação com observabilidade
futura; não efeito causal de censura nem prova de que dados ausentes são aleatórios.

## Verificação e entrega

Testes sintéticos: referência isolada do teste, quantis ponderados/empates,
variância zero/vazios, reconstrução em grupos completos e disjuntos, remoções
individuais, pareamento, histórico inválido sem imputação e corte estrito do
horizonte; guardas contra treinamento/escrita. Suíte completa unittest e
 git diff --check antes do commit de protocolo/config/código.

Executar uma vez; reler relatório persistido e reproduzir integralmente seus
agregados em processo novo, sem nova especificação ou fits. Comparar hashes dos
insumos/fontes/ledger antes/depois. Resultados e evidência agregada em segundo
commit. Falha técnica será preservada/documentada; correção não pode mudar
estatísticas ou explorar configurações após observar resultados.

Relatório responde: mudanças de distribuição; associações familiares instáveis;
diferenças conclusivos/censurados; mecanismos sustentados/enfraquecidos/ainda
indistinguíveis. Separar observação, inferência limitada e especulação. Não
excluir Q2; Q4 também negativo antes. Drift não prova perda preditiva. Muitas
linhas sobrepostas não são precisão estatística. Externos vistos permanecem
exploratórios; internos repetidos não replicam. Possível ausência de diagnóstico
claro deve ser reportada, sem ampliar busca para fabricar explicação.
