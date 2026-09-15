# Sequential bagging v1 — pré-registro da etapa 8

## Pergunta e população

Comparar bootstrap uniforme e sequencial com reposição, mantendo modelo,
quantidade de sorteios e orçamento iguais. O alvo é a classificação unilateral
`dynamic` da etapa 7: take profit antes da barreira adversa versus demais saídas
observáveis. Isso não mede lucro líquido. Não há seleção retrospectiva de
vencedoras, novo rótulo, nova feature, otimização externa, OOB ou acesso a 2024–2025.

A configuração vinculante é `configs/sequential_bagging_v1.json`. A origem é a
etapa 7, head `106c2d3d8de62ee7f3285f817787280dd1255569`, PR #22, merge
`9ded952a727ba539dd1c29ce6f5cae207849bf5a`. Os hashes completos de dataset,
manifest, relatórios, configurações, protocolo e auditoria estão na configuração.
Antes de reservar orçamento, verificar esses vínculos, versões, fontes congeladas,
encadeamento/prefixos do ledger e todos os modelos/referências utilizados. As
fontes originalmente vinculadas devem continuar idênticas; módulos novos são
permitidos, sem alterar módulos congelados. O loader próprio da etapa 8 usa a
configuração 7 para verificar a origem, nunca passa a configuração 8 ao loader 7.

Manter as 28 features e máscaras causais da etapa 7. Usar os três folds externos,
suas fases inner/refit e universos temporal, CUSUM 0.0005 e CUSUM 0.001. Recalcular
as partições com horizonte informacional completo de 4320 minutos abertos e
buffer de 1941 barras observadas. Os quatro passados distintos podem compartilhar
cache, sem fazer um fit novo para uma identidade já terminal. Não excluir nem
retunar Q2: a origem contém apenas três negativos temporais e nenhum evento CUSUM
nesse período. A seleção inner de Q2 não fornece threshold utilizável para Q3.

## Amostragem e identidade

Para cada passado/população: dois master seeds (0, 1), três membros por seed,
dois esquemas e exatamente K=512 sorteios por membro. Ordenar por `entry_indices`
originais únicos antes de qualquer operação; permutar X, y, todos os intervalos e
identidades juntos. IDs repetidos são erro; intervalos iguais com IDs distintos
são eventos distintos. Salvar a lista original de source rows, permutação local,
inversa local, source rows canônicas, IDs canônicos e os IDs/source rows de cada
sorteio. Duplicatas causadas pela reposição são preservadas.

O intervalo de amostragem é semiaberto, da entrada até
`last_information_bar_end`, no relógio de minutos em que FX está programado para
abrir. Não substituir esse fim pelo término realizado nem pelo horizonte de
expurgo. Uma abertura com hit imediato ocupa um minuto; uma ausência/timeout
preserva o último intervalo informacional conhecido. Fins de semana não
contribuem minutos fechados. Fins realizados e horizontes informacionais completos
permanecem no contrato de fit, separados do intervalo de amostragem.

Se os endpoints comprimidos produzem segmentos de duração d_j, c_j é a
concorrência dos sorteios já feitos. Para candidato i, calcular:

    u_i = sum(d_j / (c_j + 1), j no intervalo i) / D_i
    p_i = u_i / sum(u)

No bootstrap uniforme, p_i=1/N. Gerar 512 uniforms PCG64 e selecionar pelo CDF
normalizado, com busca à direita e último endpoint exatamente 1. O seed deriva
do SHA256 do material canônico de identidade/intervalos/relógio/versões da
amostragem, população, master e membro, usando os primeiros 16 bytes como inteiro
big endian. O esquema não entra no seed: os dois esquemas usam os mesmos uniforms.
X, y, hashes de resultados, manifestos e configuração global não entram nesse
material. Nenhuma dependência indireta dos resultados pode alterar o sorteio.
O contrato do trace/cache também vincula SHA256 do módulo sampler, protocolo e
política numérica explicitamente; esses vínculos não entram no seed.

Guardar por membro os uniforms, sorteios, probabilidades escolhidas, distribuição
raw de unicidade por ocorrência e multiplicidades vinculadas aos IDs. Para o
esquema sequencial, guardar todas as probabilidades: arquivo chunk contíguo
`.probabilities.f64`, little-endian float64, shape [512,N] e ordem canônica,
acompanhado de contrato, tamanho e SHA256. O uniforme registra a distribuição
analítica 1/N. Calcular também a distribuição raw na população completa, cada
evento uma vez, construindo concorrência por diferenças nos endpoints e cumsum.
Reportar distribuição, repetições, cobertura e concorrência. Uma média de pesos
normalizados igual a um não é tamanho amostral efetivo.

## Estabilidade e complexidade

Nenhuma matriz N×M é permitida na produção. M≤2N−1 segmentos. Um prefixo rápido
só pode fornecer uma diferença quando seu limite conservador de erro satisfaz a
tolerância. Cancelamento, inclusive de resultado ainda positivo, encaminha a
consulta a uma árvore de somas positivas: árvore O(M), até 2h+2 nós por intervalo,
no máximo h+1 níveis, com h=ceil(log2 M). Não há fallback de soma direta que possa
crescer até N×M. O custo registrado é O(K(M+N log M)), memória O(M+N), além do
trace de disco O(KN). Vetorização por nível é engenharia, sem mudar o objetivo.

Com epsilon=2^-52 e gamma(n)=n epsilon/(1−n epsilon), rejeitar n epsilon≥0.5.
Usar bound da árvore gamma(3h+8)/(1−gamma(3h+8)) vezes |u|, arredondado para cima.
Aceitar somente bound≤1e−14+1e−12 max(|u|−bound,0). Validar finitude,
positividade e limites teóricos. Falha numérica interrompe antes do fit daquele
membro; não fazer clipping, mudar tolerância, K, seed ou modelo. Fixtures usam
Decimal de 80 dígitos e uma matriz densa independente pequena como oráculos.

## Modelos, orçamento e falhas

Cada ocorrência recebe peso um tanto no StandardScaler quanto na regressão
logística. Aprender scaler e modelo somente no passado do membro. As linhas
repetidas são observações repetidas; não aplicar os pesos de unicidade do helper
congelado da etapa 7. Usar um helper próprio. Parâmetros logísticos são idênticos
à etapa 7, incluindo C=1 e random_state=0. Não há busca de hiperparâmetros.

Máximo: 3 membros ×2 seeds ×2 esquemas ×3 populações ×4 passados=144 fits,
mais 12 controles logísticos de treino completo com pesos unitários. Constante e
logística ponderada da etapa 7 são referências verificadas, sem novos fits.
Ledger canônico inicial: 161 fits, SHA256
`9e861f81cc713f3b583ca4a82df2beebced78fac3a7868725bd862daaefbd6ec`.
Reserva máxima 156, acumulado máximo 317, dentro do limite global de 1000.
`BoundStageLedger` confere contagem e SHA256 dos bytes exatos sob o mesmo flock
da reserva; run concorrente, inclusive de zero fits, invalida o prefixo esperado.

Ausência de uma classe no bootstrap torna esse membro indisponível, sem fit,
redraw ou substituição. Os demais membros planejados continuam. A média do
ensemble só existe com os três membros disponíveis, divisor exatamente três.
Preservar probabilidades dos membros disponíveis e razão de indisponibilidade do
ensemble. Falhas de convergência consomem o fit iniciado e ficam terminais. Cache
une contratos completos, incluindo arrays, identidades, params, fontes, runtime e
sorteio; sucesso/falha/indisponibilidade não criam aliases que tentem outro fit.

Reservar fit antes de scaler/modelo, exportar estado em arrays sem pickle,
conferir inferência exportada, persistir NPZ e relatório individual e somente
então registrar sucesso. Erro de storage ou ledger aborta o run e impede qualquer
fit posterior. Preservar tentativas, arquivos parciais e fits consumidos. Em erro,
tentar relatório de falha e fechar run em finally mesmo se esse relatório falhar.
Um fit iniciado sem terminal bloqueia novos runs e requer auditoria; não reiniciar
silenciosamente. O ledger terminal é autoridade, não a existência de um arquivo.

## Predições e inferência

Inferir em todas as oportunidades com sinal primário e features causalmente
válidas, usando a máscara de evento do universo. Censura, fim da janela e rótulo
futuro não removem probabilidades. A máscara de métricas é separada e exige o
rótulo observável do conjunto de avaliação. Salvar oportunidades, causas,
probabilidade disponível, decisão disponível, aceitação/rejeição e membros.

Para cada modelo/ensemble/referência: grid completo de thresholds com confusion,
precision, recall e F1 em cada fold/fase; apenas o inner seleciona threshold por
máximo F1, desempate pelo maior threshold. O refit externo herda essa seleção,
sem escolha externa. Sem classes/suporte no inner, manter decisão indisponível,
`accepted=-1`, sem transformar em falsa rejeição. Probabilidades continuam
utilizáveis quando o modelo existe. Grids externos são apenas diagnósticos.

Reportar LL, Brier, AUC quando definida, precision/recall/F1, cobertura de
probabilidades e decisões, volume filtrado, diversidade par a par dos membros e
sensibilidade pareada semanal. Comparar sequencial versus uniforme dentro de
cada seed, também controles unitário completo e referências ponderadas. Alegar
melhora consistente somente se LL for menor nos três externos e média de ΔBrier
for ≤0 em ambos os seeds. Mostrar todos os resultados, inclusive indisponíveis,
negativos e discordância entre seeds; não selecionar o melhor externo.

## Persistência, execução e replay

Estimar antes do run todos os traces 512×N×8 planejados (sem descontar aliases),
64 MiB por fit planejado, predições/oportunidades/arrays auxiliares e metadados.
Exigir espaço livre > estimativa restante + max(16 GiB,20% da estimativa), antes
da reserva e antes de cada artefato. Isso é verificação, não reserva física de
disco contra processos concorrentes. Todos os caminhos novos são exclusivos;
flush, fsync, close e SHA256 precedem aceitação do artefato. Nunca sobrescrever
run parcial ou reiniciar a mesma identidade.

Executar somente após commit de pré-registro, árvore Git limpa e
OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=VECLIB_MAXIMUM_THREADS=1:

    .venv/bin/python -m fxnn.bootstrap_research
    .venv/bin/python -m fxnn.bootstrap_research --verify

Defaults: origem `output/meta_dataset_v1` do worktree7 e modelos
`output/meta_primary_v1` do worktree7; destino `output/sequential_bagging_v1`.
Flags --source, --source-models e --output selecionam diretórios, sem substituir
os hashes vinculantes. `--verify` é somente leitura: verificar fontes/config/
protocolo/runtime/prefixos/terminal, reconstruir todos os sorteios e traces,
carregar somente modelos com contrato e terminal válidos, reproduzir arrays,
thresholds, métricas, pares e conclusão. Zero fits e zero writes de ledger.
Registrar SHA256 do relatório no terminal completed e salvar snapshot do ledger.
Um snapshot final ausente é falha de finalização; não fabricar segundo terminal.

## Fixtures e viabilidade prévia — apenas sintéticas

Oráculo de três eventos: após B, probabilidades (5/14,3/14,6/14); após B,C,
(5/11,3/11,3/11). Oráculo denso independente 12×30 com intervalos:
[0,3), [2,4), [4,6), [0,10), [0,10), [3,7), [6,12), [10,15), [14,20),
[20,25), [25,30), [0,30). Inclui sobreposição parcial/total, adjacência e repetição.
Monte Carlo usa exatamente essa fixture, 100 seeds (0–99) e 512 sorteios, sem fits
nem assertiva de superioridade. Diferença média de unicidade sequencial−uniforme:
−0.0000310180; fração positiva 0.40. O resultado negativo é preservado.

Benchmark determinístico: PCG64(20260915), N=100000, starts inteiros em [0,750000),
seguido de durations em [1,4321), ends=starts+durations; uniforms PCG64(0),512.
Execução sintética local do algoritmo com guards: 36.7247 s, RSS 99041280 bytes,
trace 409600000 bytes; write 0.0818 s, fsync 0.0016 s, hash 0.2025 s. Houve
51200000 consultas de árvore; máximo 11 níveis observados. Ambiente macOS arm64,
Python 3.13.5, NumPy 2.4.6. Hash do trace:
`fda34e7dfffe015bfd0bf34f78f61569cef6bd2252cd1e06c8ce449165cff2a6`.
Esses números medem fixture sintética, não resultado científico. Um protótipo
anterior sem os guards teve outro tempo; ele não representa esta implementação.
Execução e replay reais podem levar dezenas de minutos; não trocar algoritmo ou
protocolo por causa dessa duração.

## Referências e documentação consultada

AFML, capítulo 4, motivação de sequential bootstrap por unicidade média
([referência mantida](https://mlfinpy.readthedocs.io/en/stable/Sampling.html#sequential-bootstrapping)); a
implementação e os oráculos acima especificam a adaptação de intervalos deste
experimento. A etapa 7 preserva a adaptação de meta-labeling do capítulo 3.
Documentação de NumPy e scikit-learn consultada via `chub search`/`chub get`
antes da implementação (numpy/package e scikit-learn/package); runtime congelado
NumPy 2.4.6 e scikit-learn 1.8.0. Scaler e logística recebem ocorrências sem
sample_weight, PCG64 é explicitamente instanciado, e NPZ é carregado com
allow_pickle=False. Exportar estado permite replay sem desserializar estimador.
