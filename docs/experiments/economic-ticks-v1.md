# economic_ticks_v1 — execução econômica causal

## Proveniência e escopo

Etapa #9, posterior ao fechamento metodológico de #6–#8 e aquisição #19.
Pré-registro executado: `ac0dc96e6c5b9027caa7ff35d3fa8ee4973ce20b`.
As correções prospectivas anteriores constam do histórico e não consumiram dados
nem ajustes desta etapa. Código, configuração e contrato científico permanecem
idênticos ao pré-registro. Relatório acrescenta somente evidência observada.

Desenvolvimento: UTC2022–2023; carteiras externas contínuas de abril a dezembro2023.
Confirmação2024 permanece fechada neste registro intermediário. Abertura exige
modelos finais, replay, revisão completa e CI do release, seguida de congelamento.
Não há ordens reais nem execução de2025.

## Fonte e cobertura

Foram processados60.631.004 registros de fonte em24 meses, com60.494.176 grupos
elegíveis segundo o contrato e zero grupos de preços distintos no mesmo timestamp.
A grade contém748.920 oportunidades e692.209 barras observadas. Rótulos:
83.575 TP,280.618 SL e384.727 indisponíveis. Os rótulos são candidatos hipotéticos
sobrepostos; não constituem retorno de carteira.

A execução registrou14.440 eventos de qualidade/ausência e7.926 reinícios.
Counts de linhas com `reset_reason` não são contagens de reinícios. Fonte íntegra
por hash não prova cobertura econômica suficiente.

### Cobertura por trimestre

Contagem somente leitura dos arquivos já produzidos. Não foram recalculados features, sigma, rótulos ou modelos. Os hashes dos três arquivos foram conferidos contra os manifests antes e depois da leitura. Nenhuma oportunidade ou barra de2024 foi aceita pelo script.

| Campo registrado | 2023Q2 | 2023Q3 | 2023Q4 |
|---|---:|---:|---:|
| Grade integral de oportunidades | 93.600 | 93.600 | 93.720 |
| Modelo logístico disponível, segundo operational-support | 93.600 | 93.600 | 93.720 |
| Features válidas | 28.721 | 70.436 | 88.970 |
| Volatilidade válida / sigma presente | 31 | 49.627 | 82.332 |
| Sinal não nulo + features válidas + volatilidade válida | 31 | 49.256 | 81.777 |
| Probabilidades operacionais disponíveis | 31 | 49.256 | 81.777 |
| Probabilidades ≥0,5 | 0 | 0 | 0 |
| Rótulos diagnosticáveis até o limite do trimestre | 4 | 33.547 | 52.135 |
| Desses: SL / TP | 4 / 0 | 25.833 / 7.714 | 40.902 / 11.233 |

### O que os campos demonstram em Q2

As93.569 oportunidades sem probabilidade também registram `volatility_valid=false` e `sigma=null`. Entre elas,64.879 têm features/histórico indisponíveis; outras28.690 já têm features válidas, mas ainda não têm volatilidade válida. Dessas28.690,28.473 possuem sinal primário não nulo e217 possuem sinal zero. Portanto, a indisponibilidade de Q2 não é ausência do modelo: seus inputs causais completos aparecem somente em31 linhas.

O campo `valid_returns` registra zero em93.466 linhas, entre1 e99 em103 e pelo menos100 em31. As31 oportunidades completas estão entre2023-04-07 00:44 e01:14 UTC. Seus rótulos são4 SL,12 `censored:quote_absence` e15 `entry_expired`. Apenas os4 SL entram no diagnóstico supervisionado do trimestre.

`reason=insufficient_history` aparece nas93.569 linhas sem sigma. Esse rótulo amplo não significa que todas também tenham features indisponíveis: o código conserva esse motivo quando o histórico para features já é suficiente, mas a volatilidade ainda não foi validada. O JSON detalha os indicadores separadamente para não confundir as duas condições.

### Estado de reinício e barras observadas

Em Q2 e Q3 todas as oportunidades carregam `reset_reason=missing_15_open_minutes`. Esse campo registra o último motivo de reset e persiste em decisões posteriores, inclusive quando os inputs voltam a ficar disponíveis. Portanto,93.600 linhas com esse valor não representam93.600 eventos de reset. Em Q4,36.346 linhas carregam esse último motivo e57.374 carregam `invalid_bar`; isso tampouco é uma contagem de57.374 barras inválidas.

| Barras existentes no dataset, por início UTC | Q2 | Q3 | Q4 |
|---|---:|---:|---:|
| Observadas | 64.941 | 84.025 | 91.955 |
| Válidas | 64.941 | 84.025 | 91.954 |
| Inválidas | 0 | 0 | 1 |
| Grade de oportunidades menos barras observadas | 28.659 | 9.575 | 1.765 |

Essas diferenças são contagens do dataset existente. Não estabelecem sozinhas corrupção do fornecedor, falha de download, ausência de um mês ou uma causa física das lacunas. A regra implementada limpa o histórico ao completar15 minutos abertos sem observação; os campos acima mostram o estado resultante, sem criar uma hipótese nova para explicar a fonte.

### Rótulos e cauda de avaliação

Q3 registra49.256 oportunidades com inputs completos:25.833 SL,7.714 TP,14.601 censuras por ausência de cotação,836 entradas expiradas e272 entradas bloqueadas por ausência de cotação. As primeiras probabilidades desse trimestre aparecem em2023-07-31 23:47 UTC; a última em2023-09-29 20:59 UTC.

Q4 registra81.777 oportunidades com inputs completos:40.902 SL,11.233 TP,24.003 censuras por ausência de cotação,35 censuras `out_of_order`,1.021 entradas expiradas,395 entradas bloqueadas por ausência e4.188 com `evaluation_end`. Essas4.188 últimas preservam a probabilidade embora o rótulo esteja indisponível pela cauda de avaliação. Há4.321 oportunidades com `calendar_eligible=false` no total; nem todas possuem os demais inputs completos.

A máscara de diagnóstico exige probabilidade disponível, rótulo0/1 e `information_end_ms<=fim_do_trimestre`. A classificação TP-primeiro permanece separada de lucro e da disponibilidade de execução do portfólio. Todos os denominadores são mantidos; não há exclusão de Q2 nem alteração de thresholds, warmup, parâmetros ou modelos.


## Modelos pré-registrados

Oito ajustes novos no desenvolvimento e dois finais; dez de14 slots reservados.
Todos têm terminal bem-sucedido. Reuso de contratos idênticos evitou quatro
ajustes, sem trocar dados, modelos, seed ou parâmetros. Ledger global301/1.000;
a reserva permanece aberta até conclusão da avaliação, sem autorização para
usar slots restantes em variantes.

Os dois modelos finais usam364.061 exemplos:83.575 positivos e280.486 negativos,
após expurgo e buffer anteriores a2024. Threshold0,5 e calibração identidade
permanecem fixos.

| Externo | Labels | Brier constante | Brier logística | LL constante | LL logística |
|---|---:|---:|---:|---:|---:|
| 2023Q2 | 4 | 0.021649864 | 0.006674151 | 0.159158615 | 0.085138171 |
| 2023Q3 | 33,547 | 0.183932351 | 0.176326004 | 0.563242088 | 0.537994561 |
| 2023Q4 | 52,135 | 0.173857725 | 0.171181051 | 0.538380664 | 0.531953538 |

Q2 oferece somente quatro negativos, insuficientes para comparação geral.
Q3/Q4 apresentam melhora descritiva de LL/Brier neste alvo específico.
Nenhuma das131.064 probabilidades externas disponíveis alcança0,5. O modelo
está disponível nos três folds; falta de probabilidade por linha é outra condição.
Melhora classificatória não demonstra execução rentável.

## Resultado econômico de desenvolvimento

As12 carteiras processaram todas280.920 oportunidades externas, com continuidade
nos nove checkpoints mensais. O filtro realizou **zero operações** em todas
políticas/custos e trimestres: PnL e drawdown iguais a zero, sem custos de execução.
G4 e G5 falham pelo requisito de PnL filtrado estritamente positivo.
**Promoção rejeitada para esta configuração.**

O primário estrito P0 entrou duas vezes; uma saída por stop e uma exposição
inconclusiva por lacuna. A incerteza permaneceu até o final, bloqueando novas
entradas. PnL e drawdown conclusivos são nulos nos três custos. Não contabilizar
isso como zero nem liquidar retrospectivamente numa cotação conveniente.

P1 é contrafactual: executou3240/3300/3842 entradas emS0/S1/S2, todas com saída,
mas houve1106/1111/1085 liquidações após incerteza. PnL e drawdown conclusivos
permanecem indisponíveis. PnL de cenário é preservado no CSV; não é limite
inferior nem resgata a evidência P0. Alterações de custos mudam também ocupação
por efeitos das saídas: não são os mesmos trades com uma taxa subtraída depois.

No P0, valores de funding condicional aparecem também na coluna de accrual
registrado do agregado; não são débitos adicionais no caixa conhecido. O funding
condicional deve ser lido separadamente e nunca subtraído duas vezes.

Todos cenários/trimestres: [agregado gerado](economic-ticks-v1-development-aggregates.md)
e [CSV completo](economic-ticks-v1-development-aggregates.csv), incluindo bloqueios,
contadores, turnover, exposição e PnL de cenário. Arquivos são cópias byte-idênticas
do publicador congelado de relatórios; somente agregados entram no Git.

## Publicação, replay e estado de confirmação

O processamento econômico terminou, mas o CLI original falhou ao serializar
frações exatas no agregado. A [correção de publicação](economic-ticks-v1-publication-recovery.md)
é explicitamente posterior aos resultados: commits
`65a279cc50633e9b655ae8ecdad65ef6a1922a8c` e
`f5fb6d8fb9675270fab20825578bdb5ec1e9a16b`. Os62 caminhos científicos originais,
S e F permaneceram idênticos; não houve retreino ou mudança de decisão.

Após revisão independente e CI no SHA corrigido, recuperação levou79,554s e
preservou os bytes de ledger, estado canônico, manifest das nove carteiras,
relatórios de modelos, exports e probabilidades. O parcial de1221bytes foi
preservado com SHA-256
`42c8119c4c663de4f227fd2b15ac60fed57f85fdf4bb9df48975834bb4d41cd5`.

Replay independente dos modelos e probabilidades passou em47,011s, sem novos
fits nem alteração do ledger. Replay integral das12 carteiras nos nove meses
passou em3416,184s: manifest, estado canônico e ledger byte-idênticos. Relatório
JSON, Markdown e CSV reconstruídos a partir desse replay também ficaram idênticos.
Suíte da correção:479 testes, compilação e diff-check; revisão de implementação
aprovada após correção de duas falhas de durabilidade; CI executou os três
checks obrigatórios no SHA corrigido. Isso não substitui revisão completa do
release nem constitui aprovação da abertura de2024.

Confirmação permanece `UNOPENED`. Quando T1–T5 passarem, será executada uma vez
com modelos já disponíveis e pacote completo congelado, mesmo com rejeição de
promoção no desenvolvimento. Não há busca de threshold para produzir operações.

## Recursos e artefatos locais

Construção dos dados:2304,77s, pico RSS793.231.360bytes. Modelos de desenvolvimento
com exportação e verificação operacional:123,05s, pico RSS1.180.958.720bytes.
Modelos finais:28,89s, pico RSS799.768.576bytes. Carteiras e tentativa inicial de
publicação:3424,91s, pico RSS1.098.465.280bytes. São medições desta execução;
não garantias gerais de desempenho.

Dados, índices, modelos e trilhas permanecem fora do Git em
`output/economic_ticks_v1/` da worktree de execução.

| Artefato | SHA-256 |
|---|---|
| Fonte de desenvolvimento | `941e2945dc11e0014a48f6f94ac39b56112e9abe5851d0b4719737ffed24a925` |
| Modelos de desenvolvimento | `e014db3c6925f9142017be02addcf76c362048c9fb25414db794a66b623e3bdc` |
| Modelos finais | `21924365115ccd4d3d84c41710b58652fdc18b99e017ed892fdb031ba48bb152` |
| Predições operacionais | `a338132332ce10be624e35fe80b40d33bd4d60ec29620160f36358b5e40227a9` |
| Manifest dos nove meses | `5bf1ec579e2777601e80af10dbdcc0d970fa0bc921756f3f6a9ca2e26d3e8c86` |
| Agregado recuperado | `679e05ebf1c0feb8164ac373c4b041bf230ed6eb712e73287bc087109a5a0957` |
| Relatório de desenvolvimento | `dc1b0b5d3218cf1f6473dbc4b3952a8f852fb74bd6a29bf570e8f65b8b4c04fe` |
| Ledger após dez fits, antes do fechamento | `076211f9566ea51f25b5617d052061ae4d2bca5601fbf6a820957b3474b9ce60` |

Protocolo: [contrato científico](economic-ticks-v1-protocol.md),
[execução computacional](economic-ticks-v1-computation.md) e
[bindings](economic-ticks-v1-bindings.json).
