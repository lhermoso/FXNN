# Volatility barriers v1 — pré-registro da etapa 6

## Autorização, hipótese e decisão

Léo autorizou a sequência completa em 15/09/2026: “esta tudo autorizado, faca
tudo o que for preciso”. Este experimento usa exclusivamente EURUSD 2022–2023.
2024 permanece fechado até congelamento do pipeline econômico; 2025 não será
consumido. Código, configuração e este protocolo devem estar commitados antes
dos novos labels e fits. Cada diretório de saída é exclusivo, sem sobrescrita.

Hipótese: distâncias fixas 50/20 pips podem definir dificuldades diferentes
conforme volatilidade. Avaliar barreiras adaptativas como **outra tarefa**,
sem presumir melhora. Evidência anterior permanece negativa/inconsistente;
não há contribuição preditiva estável nem lucro demonstrado. Esta experiência
não identifica causalmente regime, pesos e seleção por observabilidade.

Comparar cada tarefa com sua própria constante. Nunca ordenar tarefas por
log-loss absoluto. Por decisão anterior aos resultados, a tarefa dinâmica
continua em #7 para investigar meta-labeling, mesmo se pior. Falha técnica
torna esse ramo indisponível; não trocar para tarefa fixa após ver resultados.
Nenhuma nova escala, feature, família ou threshold será buscada.

## Volatilidade diária causal e finita

Manter calendário semanal domingo 17h–sexta 17h America/New_York, com DST;
nenhum candle sintético. Gaps de até 14 minutos abertos são tolerados; 15 ou
mais reiniciam histórico. Ausência durante sessão aberta não pausa relógio.

No endpoint observado `j`, retorno diário simples:

`r[j] = close[j] / close[a] - 1`,

onde `a` é um endpoint observado exatamente 1.440 minutos **abertos** antes
de `j`. Ambos pertencem ao mesmo segmento sem reset. Endpoint exato ausente
invalida aquele retorno; não interpolar, preencher nem escolher vizinho.

Na entrada `i`, usar somente endpoints `j ∈ [i−500, i)`, dentro do segmento
da entrada. Peso `w[j] = q**(i−1−j)`, `q = 1−2/101`; pelo menos 100 retornos
válidos. Variância ponderada sem viés:

`sum(w * (r−mean_w)**2) / (sum(w)−sum(w*w)/sum(w))`.

Span 100 significa idade em endpoints intradiários observados, **não 100 dias
independentes**. Retornos diários se sobrepõem; truncamento 500 e mínimo 100
são escolhas fixas de desenho, sem otimização ou alegação de poder estatístico.

Implementação por convoluções finitas em cada segmento. Quando cancelamento
dos momentos ameaça variância (`numerator <= 64*eps*(abs(C)+B²/A)`), ou houver
valor não finito recuperável, recalcular a janela corrente em duas passagens,
centrada em seu primeiro retorno válido. Nunca centrar em histórico remoto,
nem transformar variância negativa em zero silenciosamente. Sigma zero,
não finito ou histórico insuficiente ficam indisponíveis, com motivo.
Preços de entrada do estimador precisam ser positivos e finitos.

`v[i] = close[i−1] * sigma[i]`. Converter distância float para preço com
`Decimal(str(distance))`, sem arredondamento a pips. Nenhuma informação do
candle de entrada, salvo abertura para centrar as barreiras, entra na estimação.
Sigma não é acrescentado às features.

## Duas tarefas, oportunidades e labels

1. Fixa: TP 0,0050 / SL 0,0020.
2. Dinâmica: TP `2,5*v[i]` / SL `v[i]`.

Distâncias congeladas na entrada para long e short. Razão 2,5:1 é razão de
distâncias, não retorno monetário líquido garantido. Universo de cada tarefa
contém todas aberturas observadas, dois lados, inclusive futuros censurados.
Elegibilidade comum exige sigma válido e barreiras positivas em ambas tarefas
e lados; retenção para modelagem também exige as 28 features causais originais.
Não usar vencedoras retrospectivas nem recuperar lado oposto conclusivo.

Horizonte: 4.320 minutos abertos. Mesma precedência de sessão congelada:
SL gap executa na abertura; TP gap fica limitado ao alvo; TP/SL intrabar
simultâneos são ambíguos. TP intrabar terminando exatamente no horizonte é
`boundary`; SL nesse candle é negativo. Timeout observado é negativo no label
binário, não prova de perda econômica. Censurados, ambíguos e boundary não
viram classe negativa. Final de arquivo não inventa ausência observada futura.

Persistir três endpoints diferentes: saída realizada, fim da informação usada
e horizonte conservador de expurgo. Hit na abertura inclui conservadoramente
seu candle no fim da informação; timeout com preço stale inclui a ausência até
deadline. Pesos desta etapa usam saída realizada, conforme convenção anterior;
#8 pré-registrará a convenção de informação para amostragem. Nada altera os
endpoints dos experimentos históricos.

Persistir features causais de todas aberturas, closes textuais e IDs originais
localmente para replay/meta-labeling posterior. Nunca publicar esses arquivos,
modelos ou previsões volumosas no Git. Relatórios agregados são publicáveis.

## Partições, modelos e orçamento

Usar os três folds originais Q2/Q3/Q4 de 2023, internos e refits expansivos.
Expurgar pelo horizonte completo e usar buffer de **1.941 candles observados**
antes da borda de treino. Prova: `j≥i−500`, `j−a≤1440`, portanto `a≥i−1940`.
Persistir mínimo anchor real e testar a proveniência. Nenhum random split.

Populações separadas: temporal, CUSUM 0,0005 e CUSUM 0,001; máscaras causais
originais. Em cada tarefa/população, logística C=1, lbfgs, máximo 1.000 iterações,
seed 0 e parâmetros completos da configuração; constante própria ponderada.
Scaler e unicidade são calculados exclusivamente no treino local; pesos no
relógio aberto, média normalizada 1, sem interpretação como amostra efetiva.
Logística exige ambas classes; não balancear nem fabricar classe ausente.
Constante exige treino não vazio. Falha numérica/convergência consome fit e
deixa comparação indisponível, sem retry. Sem MLP, busca ou novo feature.

Quatro passados únicos × duas tarefas × três populações × duas famílias:
**48 fits máximos**, ledger canônico de 103 para no máximo 151/1.000.
Cache exige contrato idêntico: tarefa, família, parâmetros, identidades,
X/y/starts/ends/info_ends, pesos, features, versões e fontes. Reuso de passado
idêntico não é novo fit. Qualquer diferença impede reuso.

## Relatórios e interpretação pré-fixada

Reportar LL, Brier, AP, ROC-AUC, thresholds 0,3/0,4/0,5, precisão/recall e todos
denominadores; métricas indefinidas têm motivo. Nenhum threshold selecionado
nesta etapa. Comparação logística menos sua constante em cada tarefa/população.
Critério descritivo: LL menor nos três externos **e** média do ΔBrier ≤ 0.
Caso contrário: misto/desfavorável; suporte/fits indisponíveis: inconclusivo
técnico. Q2 nunca excluído. Sensibilidade por exclusão de semana é descritiva,
não intervalo de confiança ou p-valor. Internos posteriores reutilizam períodos
já vistos; nenhuma alegação de independência ou holdout intocado.

Para cada tarefa/população/fold/fase e treino/avaliação, reportar candidatos,
elegibilidade, outcomes, exclusões, retidos, positivos/negativos e prevalência
com denominador. Duração por outcome: contagem, média, desvio padrão populacional,
mínimo, q05/q50/q95 e máximo, em minutos abertos e horas corridas. Ineligíveis
sem label têm duração vazia; censurados nunca apresentados como trades completos.
Mesmas estatísticas para TP/SL em preço/pips, sigma e volatilidade em preço,
sobre candidatos causalmente elegíveis, incluindo futuros inconclusivos.
Quantis descritivos interpolados linearmente; vazio produz count 0/null/motivo.

Regimes descritivos: q1/3 e q2/3 pela CDF empírica inversa entre timestamps
únicos causalmente elegíveis do **treino de candidatos**, incluindo futuros
inconclusivos, após máscara, expurgo e buffer. Low ≤ q1; middle q1 < sigma ≤ q2;
high > q2. Empates e bandas vazias ficam explícitos, sem reparos. Aplicar cortes
congelados a treino e avaliação; ineligíveis em bucket próprio. Sem treino
causal: regimes indisponíveis. Repetir estatísticas por regime e pelos oito
trimestres calendários fixos de 2022–2023. Regimes não entram em X nem seleção.

## Integridade, falhas e replay

Ledger histórico e código congelado permanecem intactos. `StageLedger` herda
locks e todos guards de `FitLedger`; substitui etapa/seed somente em `_append`
antes do hash, nunca depois. Guardar prefixo canônico e hashes de entrada,
configuração, protocolo, código, arquivos e runtime. Fit é registrado antes
de scaler/modelo. Cache terminal é instalado antes de executar; alias de falha
ou execução incompleta não pode refazer contrato, mesmo após erro de gravação.

Sucesso exige export/modelo e JSON exclusivos verificados antes de registrar
`finish_fit(succeeded)`. Falha de armazenamento/ledger aborta execução inteira;
arquivos parciais ficam preservados e não concedem sucesso. Treinos numericamente
falhos, com terminal registrado, permitem contratos independentes planejados.
Runner tenta fechamento aborted em `finally`, mesmo se `failure.json` falhar.
Falha do ledger exige auditoria antes de qualquer nova pesquisa; nunca reiniciar
experimento ou restaurar orçamento. Erro posterior ao fit não autoriza refit.

Replay somente leitura exige contrato, hashes, versões, prefixo canônico,
registro de fit sucedido, identidade e modelo válidos. Relatório completo exige
run terminal completed vinculando seu hash. Run aborted permite apenas replay
parcial explicitamente identificado de fits individualmente válidos; órfãos
são rejeitados. Reconstruir previsões salvas, métricas e conclusão sem novos fits.

Fixtures independentes: variância escalar, scanner minuto a minuto, alterações
atuais/futuras, lag ausente, gaps 14/15, DST, mínimo 99/100, sigma zero/quase
constante, barreiras/terminal, buffer, regimes treino-only, export sem pickle,
cache/guards e falhas injetadas em todas fronteiras de persistência. Executar
unittest completo, compileall, diffcheck, revisão independente e CI significativo
no SHA integrado. Billing/quota/runner não dispensam check.

## Referências e diferenças deliberadas

[AFML, implementação/documentação de volatilidade diária](https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/util/volatility.py),
Snippet 3.1, motiva barreiras proporcionais à volatilidade. Nosso lag em minutos
abertos, janela finita e política de gaps são adaptações explícitas; não alegamos
reprodução literal. [Triple barrier/meta-labeling](https://mlfinpy.readthedocs.io/en/doc-staging/Labelling.html)
orienta separação entre direção e aceitação posterior.
[NumPy convolve](https://numpy.org/doc/stable/reference/generated/numpy.convolve.html)
e documentação NumPy/scikit-learn via chub foram consultadas antes de escrever
código. Nenhuma nova dependência instalada. Runtime registrado: Python 3.13.5,
NumPy 2.4.6, scikit-learn 1.8.0; quatro limites BLAS/OMP fixados em uma thread
antes de fits e replay.
