# economic_ticks_v1 — execução econômica causal

## Proveniência e escopo

Etapa #9, posterior ao fechamento metodológico de #6–#8 e aquisição #19.
Pré-registro executado: `ac0dc96e6c5b9027caa7ff35d3fa8ee4973ce20b`.
As correções prospectivas anteriores constam do histórico e não consumiram dados
nem ajustes desta etapa. Código, configuração e contrato científico permanecem
idênticos ao pré-registro. Relatório acrescenta somente evidência observada.

Desenvolvimento: UTC 2022–2023; carteiras externas contínuas de abril a dezembro de 2023.
Confirmação UTC 2024 executada uma única vez após modelos finais, replay,
revisão completa, CI e congelamento. Estado terminal e recibo de encerramento:
`COMPLETED`; recibo SHA-256 `d8218b2c2e123eb9168a0cf2e655416c0bbe36e7a36f0ed0056ad39268ffe1c1`.
Não há ordens reais nem execução de 2025.

## Fonte e cobertura

Foram processados 60.631.004 registros de fonte em 24 meses, com 60.494.176 grupos
elegíveis segundo o contrato e zero grupos de preços distintos no mesmo timestamp.
A grade contém 748.920 oportunidades e 692.209 barras observadas. Rótulos:
83.575 TP, 280.618 SL e 384.727 indisponíveis. Os rótulos são candidatos hipotéticos
sobrepostos; não constituem retorno de carteira.

A execução registrou 14.440 eventos de qualidade/ausência e 7.926 reinícios.
Contagens de linhas com `reset_reason` não são contagens de reinícios. Fonte íntegra
por hash não prova cobertura econômica suficiente.

### Cobertura por trimestre

Contagem somente leitura dos arquivos já produzidos. Não houve recálculo de features, sigma, rótulos ou modelos. Os hashes dos três arquivos foram conferidos contra os manifests antes e depois da leitura. Nenhuma oportunidade ou barra de 2024 foi aceita pelo script.

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

As 93.569 oportunidades sem probabilidade também registram `volatility_valid=false` e `sigma=null`. Entre elas, 64.879 têm features/histórico indisponíveis; outras 28.690 já têm features válidas, mas ainda não têm volatilidade válida. Dessas 28.690, 28.473 possuem sinal primário não nulo e 217 possuem sinal zero. Portanto, a indisponibilidade de Q2 não é ausência do modelo: seus inputs causais completos aparecem somente em 31 linhas.

O campo `valid_returns` registra zero em 93.466 linhas, entre 1 e 99 em 103 e pelo menos 100 em 31. As 31 oportunidades completas estão entre 2023-04-07 00:44 e 01:14 UTC. Seus rótulos são 4 SL, 12 `censored:quote_absence` e 15 `entry_expired`. Apenas os 4 SL entram no diagnóstico supervisionado do trimestre.

`reason=insufficient_history` aparece nas 93.569 linhas sem sigma. Esse rótulo amplo não significa que todas também tenham features indisponíveis: o código conserva esse motivo quando o histórico para features já é suficiente, mas a volatilidade ainda não foi validada. O JSON detalha os indicadores separadamente para não confundir as duas condições.

### Estado de reinício e barras observadas

Em Q2 e Q3 todas as oportunidades carregam `reset_reason=missing_15_open_minutes`. Esse campo registra o último motivo de reset e persiste em decisões posteriores, inclusive quando os inputs voltam a ficar disponíveis. Portanto, 93.600 linhas com esse valor não representam 93.600 eventos de reset. Em Q4, 36.346 linhas carregam esse último motivo e 57.374 carregam `invalid_bar`; isso tampouco é uma contagem de 57.374 barras inválidas.

| Barras existentes no dataset, por início UTC | Q2 | Q3 | Q4 |
|---|---:|---:|---:|
| Observadas | 64.941 | 84.025 | 91.955 |
| Válidas | 64.941 | 84.025 | 91.954 |
| Inválidas | 0 | 0 | 1 |
| Grade de oportunidades menos barras observadas | 28.659 | 9.575 | 1.765 |

Essas diferenças são contagens do dataset existente. Não estabelecem sozinhas corrupção do fornecedor, falha de download, ausência de um mês ou uma causa física das lacunas. A regra implementada limpa o histórico ao completar 15 minutos abertos sem observação; os campos acima mostram o estado resultante, sem criar uma hipótese nova para explicar a fonte.

### Rótulos e cauda de avaliação

Q3 registra 49.256 oportunidades com inputs completos: 25.833 SL, 7.714 TP, 14.601 censuras por ausência de cotação, 836 entradas expiradas e 272 entradas bloqueadas por ausência de cotação. As primeiras probabilidades desse trimestre aparecem em 2023-07-31 23:47 UTC; a última em 2023-09-29 20:59 UTC.

Q4 registra 81.777 oportunidades com inputs completos: 40.902 SL, 11.233 TP, 24.003 censuras por ausência de cotação, 35 censuras `out_of_order`, 1.021 entradas expiradas, 395 entradas bloqueadas por ausência e 4.188 com `evaluation_end`. Essas 4.188 últimas preservam a probabilidade embora o rótulo esteja indisponível pela cauda de avaliação. Há 4.321 oportunidades com `calendar_eligible=false` no total; nem todas possuem os demais inputs completos.

A máscara de diagnóstico exige probabilidade disponível, rótulo 0/1 e `information_end_ms<=fim_do_trimestre`. A classificação TP-primeiro permanece separada de lucro e da disponibilidade de execução do portfólio. Todos os denominadores são mantidos; não há exclusão de Q2 nem alteração de thresholds, warmup, parâmetros ou modelos.


## Modelos pré-registrados

Oito ajustes novos no desenvolvimento e dois finais; dez de 14 slots reservados.
Todos têm terminal bem-sucedido. Reuso de contratos idênticos evitou quatro
ajustes, sem trocar dados, modelos, seed ou parâmetros. Ledger global 301/1.000;
a reserva foi selada antes de 2024. O encerramento durável preservou 301 fits globais e fechou a execução, sem novo ajuste.
Os quatro slots não usados não autorizam variantes ou novos ajustes.

Os dois modelos finais usam 364.061 exemplos: 83.575 positivos e 280.486 negativos,
após expurgo e buffer anteriores a 2024. Threshold 0,5 e calibração identidade
permanecem fixos.

| Externo | Labels | Brier constante | Brier logística | LL constante | LL logística |
|---|---:|---:|---:|---:|---:|
| 2023Q2 | 4 | 0.021649864 | 0.006674151 | 0.159158615 | 0.085138171 |
| 2023Q3 | 33,547 | 0.183932351 | 0.176326004 | 0.563242088 | 0.537994561 |
| 2023Q4 | 52,135 | 0.173857725 | 0.171181051 | 0.538380664 | 0.531953538 |

Q2 oferece somente quatro negativos, insuficientes para comparação geral.
Q3/Q4 apresentam melhora descritiva de LL/Brier neste alvo específico.
Nenhuma das 131.064 probabilidades externas disponíveis alcança 0,5. O modelo
está disponível nos três folds; falta de probabilidade por linha é outra condição.
Melhora classificatória não demonstra execução rentável.

## Resultado econômico de desenvolvimento

As 12 carteiras processaram todas as 280.920 oportunidades externas, com continuidade
nos nove checkpoints mensais. O filtro realizou **zero operações** em todas
políticas/custos e trimestres: PnL e drawdown iguais a zero, sem custos de execução.
G4 e G5 falham pelo requisito de PnL filtrado estritamente positivo.
**Promoção rejeitada para esta configuração.**

O primário estrito P0 entrou duas vezes; uma saída por stop e uma exposição
inconclusiva por lacuna. A incerteza permaneceu até o final, bloqueando novas
entradas. PnL e drawdown conclusivos são nulos nos três custos. Não contabilizar
isso como zero nem liquidar retrospectivamente numa cotação conveniente.

P1 é contrafactual: executou 3240/3300/3842 entradas em S0/S1/S2, todas com saída,
mas houve 1106/1111/1085 liquidações após incerteza. PnL e drawdown conclusivos
permanecem indisponíveis. PnL de cenário é preservado no CSV; não é limite
inferior nem resgata a evidência P0. Alterações de custos mudam também ocupação
por efeitos das saídas: não são os mesmos trades com uma taxa subtraída depois.

No P0, valores de funding condicional aparecem também na coluna de accrual
registrado do agregado; não são débitos adicionais no caixa conhecido. O funding
condicional deve ser lido separadamente e nunca subtraído duas vezes.

Todos os cenários/trimestres: [agregado gerado](economic-ticks-v1-development-aggregates.md)
e [CSV completo](economic-ticks-v1-development-aggregates.csv), incluindo bloqueios,
contadores, turnover, exposição e PnL de cenário. Arquivos são cópias byte-idênticas
do publicador congelado de relatórios; somente agregados entram no Git.

## Publicação, replay e estado de confirmação

O processamento econômico terminou, mas o CLI original falhou ao serializar
frações exatas no agregado. A [correção de publicação](economic-ticks-v1-publication-recovery.md)
é explicitamente posterior aos resultados: commits
`65a279cc50633e9b655ae8ecdad65ef6a1922a8c` e
`f5fb6d8fb9675270fab20825578bdb5ec1e9a16b`. Os 62 caminhos científicos originais,
S e F permaneceram idênticos; não houve retreino ou mudança de decisão.

Após revisão independente e CI no SHA corrigido, recuperação levou 79,554 s e
preservou os bytes de ledger, estado canônico, manifest dos nove checkpoints mensais das 12 carteiras,
relatórios de modelos, exports e probabilidades. O parcial de 1221 bytes foi
preservado com SHA-256
`42c8119c4c663de4f227fd2b15ac60fed57f85fdf4bb9df48975834bb4d41cd5`.

Replay independente dos modelos e probabilidades passou em 47,011 s, sem novos
fits nem alteração do ledger. Replay integral das 12 carteiras nos nove meses
passou em 3416,184 s: manifest, estado canônico e ledger byte-idênticos. Relatório
JSON, Markdown e CSV reconstruídos a partir desse replay também ficaram idênticos.
Suíte da correção: 479 testes, compilação e diff-check; revisão de implementação
aprovada após correção de duas falhas de durabilidade; CI executou os três
checks obrigatórios no SHA corrigido. Isso não substitui revisão completa do
release nem constitui aprovação da abertura de 2024.

A revisão completa pré-confirmação aprovou os oito critérios RELEASE-* no SHA
`cac434dd2a2cf9bcb38ec33bca6b0dcba0d3f951`, sem achados. CI do mesmo SHA
executou testes, compilação e diff-check: [run 35046993074](https://github.com/lhermoso/FXNN/actions/runs/35046993074).
Recibo original da revisão: SHA-256
`f5b4946f0c3cd46ef1f786fc5a9836a1bd3792be0ead989b58bcd586188f8bba`.
O congelamento original repetiu integralmente modelos, probabilidades, carteiras
e relatório de desenvolvimento; passou em 3481,30 s, antes da abertura.

Identidades congeladas:

- S: `844a7dab855042d997068c41ebbe0b47bfa6fe3707fdbe0b9d17b88eb754965a`.
- R: `cac434dd2a2cf9bcb38ec33bca6b0dcba0d3f951`.
- P: `c7aeb1e50de5abdcb33a56f35f1e2a43b590b25db910ca6aa759bc61f6e65aa1`, 43674 bytes.
- Publicador pós-resultados: `cfaf53ef12f9a5f156a21be76f37dec9ecfbf9df6df0196c2d5c7c6ac26ac31a`, 8642 bytes,
  ligado ao pacote pelo recibo original de validação e pelo blob Git de R.

O publicador foi autenticado antes da aquisição e novamente antes da execução
2024. A guarda durável passou de `UNOPENED` para `OPENING` antes do primeiro
payload e para `OPENED` após sua recepção. A revisão e CI precederam o acesso;
a rejeição no desenvolvimento não foi usada para dispensar a confirmação.
Apenas documentação e agregados são acrescentados após o release congelado;
O SHA final de publicação não se confunde com R.

## Confirmação única 2024: cobertura e modelos

Foram processados 20.674.272 registros de fonte nos 12 meses de 2024. O dataset
contém 377.280 oportunidades, 370.588 barras válidas e 20.611.767 grupos elegíveis,
sem grupos de preços distintos no mesmo timestamp. Registrou 4.969 eventos de
qualidade/ausência e 40 reinícios. Há 311.699 oportunidades operacionalmente
elegíveis antes dos bloqueios de carteira.

Rótulos: 47.223 TP, 160.582 SL e 169.475 indisponíveis, incluindo 96.479 censuras
por ausência de cotação, 5.540 entradas expiradas e 1.875 bloqueadas por ausência.
Mantêm-se 58.460 linhas com motivo geral de histórico insuficiente, 2.800 sem
sinal e 4.321 de cauda. Esses grupos não são removidos do denominador operacional.

| Campo | Q1 | Q2 | Q3 | Q4 | Ano |
|---|---:|---:|---:|---:|---:|
| Oportunidades | 93.660 | 93.600 | 95.040 | 94.980 | 377.280 |
| Features válidas | 90.983 | 89.604 | 91.151 | 92.288 | 364.026 |
| Volatilidade válida | 87.364 | 72.664 | 72.902 | 85.785 | 318.715 |
| Probabilidades disponíveis | 86.485 | 71.964 | 72.269 | 85.154 | 315.872 |
| p≥0,5, em todas as p disponíveis | 0 | 0 | 0 | 1 | 1 |
| Labels conhecidos até fim do ano, por trimestre da oportunidade | 56.996 | 43.969 | 46.656 | 60.184 | 207.805 |
| Labels conhecidos até fim de cada trimestre | 56.996 | 43.969 | 46.654 | 60.184 | 207.803 |

Os dois labels adicionais de Q3 são SL conhecidos em Q4; não estavam disponíveis
em setembro. A máscara anual original permite o resultado até fim de 2024.
A cauda mantém 4.173 probabilidades nas 4.321 oportunidades calendaricamente
inelegíveis. Nenhuma dessas probabilidades alcançou 0,5.

O modelo está disponível nas 377.280 oportunidades. Há 13.254 linhas com features
inválidas e 58.565 com sigma ausente. O código exclusivo `features_unavailable=0`
não significa observação completa: as 13.254 também têm lado zero e recebem
`no_primary_signal`, de prioridade maior. Esse código totaliza 16.513 linhas;
outras 44.895 recebem exclusivamente `volatility_unavailable`. São 61.408
probabilidades ausentes, sem ausência do modelo. `reset_reason` persiste após
recuperação e não deve ser contado como evento de reinício.

| Modelo congelado | Labels | Brier | Log-loss | ROC-AUC |
|---|---:|---:|---:|---:|
| Constante | 207.805 | 0.182358697928 | 0.559826817032 | 0.500000000000 |
| Logística | 207.805 | 0.177589263249 | 0.546481237543 | 0.574657857720 |

Melhora descritiva de scores do proxy S0 não demonstra ganho econômico.
Entre **todas as 315.872 probabilidades**, somente uma alcançou o threshold fixo:
2024-11-22 09:14 UTC, p=0,5104832162806134, rótulo SL. Não houve aceitação nas
108.067 probabilidades sem label métrico anual. Nenhum threshold alternativo,
recalibração, refit, seleção de modelo ou seed foi executado.

## Resultado econômico da confirmação

As 12 carteiras processaram 377.280 oportunidades cada, com 12 checkpoints mensais
contínuos e quatro relatórios trimestrais. O filtro executou uma entrada e uma
saída por stop em Q4, em todos os custos/políticas. Não houve exposição incerta
nem violação de capital no filtro. Q1–Q3 tiveram zero operações/PnL/DD.

| Custo | Entradas/saídas | PnL USD | DD USD exato | Comissão USD | Funding USD |
|---|---:|---:|---:|---:|---:|
| S0 | 1/1 | -2,95 | 7,05 | 0 | 0 |
| S1 | 1/1 | -2,97 | 7,025 | 0,07 | 0 |
| S2 | 1/1 | -3,10 | 7,08 | 0,14 | 0 |

Valores iguais em P0/P1 para o filtro. O Markdown gerado arredonda 7,025 para 7,02
por half-even; frações exatas permanecem nos artefatos. DD mede queda a partir
da máxima equity observada, não apenas perda final. Barreira e execução usam
fill efetivo: mudar slippage pode mudar timestamp/preço da saída. S1/S2 não são
apenas comissões subtraídas do mesmo fechamento S0.

Primário P0: S0/S1 tiveram duas entradas, um TP e uma exposição inconclusiva
até fim do ano. S2 teve uma entrada, sem saída e com exposição inconclusiva.
Todos os PnL/DD conclusivos do primário são indisponíveis; não são zero.
Funding condicional S1/S2 aparece no accrual registrado, mas não é débito
adicional no caixa conhecido nem deve ser descontado duas vezes.

Primário P1: 8.419/8.737/10.036 entradas em S0/S1/S2, todas com saída, incluindo
3.048/3.037/2.965 liquidações contrafactuais após incerteza. PnL de cenário é
negativo nos três custos, preservado no CSV. PnL/DD conclusivos continuam nulos:
a liquidação de cenário não recupera o caminho não observado nem constitui
limite inferior para P0. Custos alteram também ocupação e número de operações.

**G4/G5 falharam em P0 e P1. Promoção rejeitada no desenvolvimento e em 2024.**
O filtro não apresenta PnL estritamente positivo; comparação conclusiva com o
primário está indisponível. Ausência de violação de capital e DD pequeno no
único trade não satisfazem os demais critérios. Nenhum piso de operações foi
inventado depois do resultado, e zero operações em Q1–Q3 não foi omitido.

A execução completa com incerteza econômica no primário não se confunde com
falha técnica ou lifecycle `INCOMPLETE`. Tabelas completas e contadores:
[relatório agregado final](economic-ticks-v1-final-aggregates.md) e
[CSV final](economic-ticks-v1-final-aggregates.csv), cópias byte-idênticas do
relatório produzido pelo código científico registrado.

## Encerramento e decisão

O comando original de encerramento verificou as probabilidades dos modelos
finais e repetiu integralmente as 12 carteiras de 2024 e de desenvolvimento 2023.
Journals/checkpoints coincidiram; relatório completo reconstruído igual ao
publicado. A sincronização precedeu a transição terminal `COMPLETED`, sem
poison. Duração: 8892,97 s; pico RSS 1.157.251.072 bytes. Recibo original SHA-256:
`d8218b2c2e123eb9168a0cf2e655416c0bbe36e7a36f0ed0056ad39268ffe1c1`.

Modelos, probabilidades, manifests, agregados e relatório permaneceram
byte-idênticos. Ledger conservou o prefixo anterior e recebeu somente um
`run_finished`; nenhuma abertura adicional ou fit foi criado. Contagem final:
301 fits iniciados/encerrados e 10 runs iniciados/encerrados. Ledger final SHA-256:
`a7cac20a864602ad4ffd5a9dbb9587fbd8a93b3249cf78957d6a47a0780374f1`. P/S/R e publicador permaneceram idênticos ao pacote congelado.

Decisão: arquivar esta configuração sem promoção econômica.
Não há evidência para execução real; nenhum resultado de classificação foi
convertido em alegação de lucro. Isso não refuta universalmente CUSUM, redes ou
outras hipóteses. Pesquisa nova exige protocolo e confirmação próprios; 2024
foi consumido e não poderá servir de novo holdout para selecionar variantes.
Nenhuma execução de 2025 ocorreu nesta etapa.

## Recursos e artefatos locais

Construção dos dados: 2304,77 s, pico RSS 793.231.360 bytes. Modelos de desenvolvimento
com exportação e verificação operacional: 123,05 s, pico RSS 1.180.958.720 bytes.
Modelos finais: 28,89 s, pico RSS 799.768.576 bytes. Carteiras e tentativa inicial de
publicação: 3424,91 s, pico RSS 1.098.465.280 bytes. São medições desta execução;
não garantias gerais de desempenho.

Confirmação: aquisição/construção 1424,24 s, pico RSS 598.999.040 bytes;
predições 19,09 s, pico 447.266.816 bytes; carteiras/publicação 5514,02 s,
pico 1.095.761.920 bytes. Congelamento/replay 3481,30 s, pico 1.375.010.816 bytes.
Encerramento com replay das duas janelas: 8892,97 s, pico RSS 1.157.251.072 bytes.

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

| Artefato da confirmação | SHA-256 |
|---|---|
| Fonte de confirmação | `9c9cfe0b368be8a06cb37042c72fb2e8b835c59f622ac6543ff99567d9f2b74a` |
| Predições de confirmação | `83cc46b14c80f1e9130f26fcbcd956ce115a6b9c7a5529ac909fe5ce38e96a00` |
| Operacional 2024 | `da437f74c57edd8a9590399291b61f6837401a185ea78166c07a4ee220d85df7` |
| Manifest dos 12 meses | `b699e386c9199de63e06327534116a46a34052a9076cd9a30089f8a9e53ad0fb` |
| Agregado 2024 | `3651773b991476b72462606b3d055c6e6a2918a0fbd9f5fc25c9f8e3889e4192` |
| Relatório final JSON | `6b68a910c0310e285e338f0376b1ded342a48c89f69510c8562f2596263e447f` |

Protocolo: [contrato científico](economic-ticks-v1-protocol.md),
[execução computacional](economic-ticks-v1-computation.md) e
[bindings](economic-ticks-v1-bindings.json).
