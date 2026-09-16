# FXNN — machine learning research for Forex

**[English](#english) · [Português](#português)**

---

<a id="english"></a>

# English

Protocol: [methodology](docs/methodology.md), [decisions](docs/decisions.md)
and [roadmap](docs/roadmap.md). Retrospective labeling and causal prediction are
separate stages. Classification results do not represent executable profitability.

## Environment and baseline

Python 3.13. The labeler uses the standard library; research adds NumPy and scikit-learn.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python -m unittest discover -s tests -v
```

After downloading and labeling the yearly dataset with the commands below:

```bash
.venv/bin/python -m fxnn.research --output output/research_v1
```

Implements 28 causal features, uniqueness, temporal purging and logistic regression.
Family-wise selection happens in the inner validation. July–September are external
evaluations; October–December stay out of the initial modeling. The JSON report
includes code/data hashes, parameters and metrics; predictions stay in the local CSV.
A non-empty experiment directory is refused in order to preserve history.
Raw data, environment and bulky outputs are ignored by Git.

First result: [research_v1](docs/experiments/research-v1.md). Predictive gain was
not consistent across months; there is still no validated strategy.

## Available dataset — EUR/USD, 2022–2025

Four yearly HistData M1 files available locally, with records in all 12 months of
each year. Total: 1,439,606 normalized candles.

| Year | Candles | Quarantined rows | Gaps |
|---|---:|---:|---:|
| 2022 | 372,745 | 120 | 1,111 |
| 2023 | 322,518 | 120 | 1,871 |
| 2024 | 372,379 | 0 | 1,601 |
| 2025 | 371,964 | 120 | 966 |

2022–2024 downloaded on 2026-09-13 with the existing downloader. Each year has a
`data/histdata/EURUSD/EURUSD_<year>_m1_bid_utc.csv`, the original ZIP, a manifest
with hashes, a gap report and quarantine. To reproduce, run
`python3 scripts/download_histdata.py --year <year>` for each desired year.
Ingestion validation checks CRC, OHLC, temporal ordering and presence of all 12 months.

2023 has lower coverage, especially between March and July; presence of all
12 months does not mean a complete series. Gaps include market closes and possible
data failures, still unclassified and unfilled. 2022 and 2023 each had 60 duplicated
timestamps: all 120 occurrences of each year were isolated. The new years have not
been labeled yet, nor used in the existing experiments, which remain restricted to 2025.

### Initial research dataset — 2025

HistData M1, with all 12 months of 2025. Normalized file:
`data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv`.
Download/reproduce and validate:

```bash
python3 scripts/download_histdata.py --year 2025
```

The original ZIP, the provider report, a manifest with hashes/counts, the gap list
and quarantine stay in the same folder. The history is **bid-only**; no ask,
historical spread or traded volume. Timestamps converted from fixed EST
(UTC−5, no daylight saving), per the provider FAQ, to UTC.

The 2025 file showed 60 repeated timestamps, with 120 rows in hour 19 of
October 26 in source time. All occurrences were isolated in quarantine; no time
shift was inferred and no version of the prices was chosen. Remaining gaps are
recorded and not filled. Covering 12 months does not mean every minute is usable.

This CSV is compatible with the initial labeler:

```bash
python3 -m fxnn data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv --pip-size 0.0001 --bar-minutes 1 --verify-samples 2048 --output output/eurusd_2025
python3 -m scripts.validate_run data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv --output output/eurusd_2025
```

The command above still uses prices from a single series, without costs, and an
O(N log N) scanner; it does not represent an executable backtest. Three days bound
the duration of each trade; **one year is the initial minimum of history**, not three days.

Source/format: https://www.histdata.com/f-a-q/.
Alternative used after widespread HTTP 503 failures on the Dukascopy feed.

## Dukascopy history

Reproducible yearly attempt: `python3 scripts/download_year.py --year 2025`.
Uses daily M1 bid/ask files and saves per-file progress in JSONL. An existing
partial cache does not constitute a complete yearly dataset. Do not automatically
mix prices from different providers to fill gaps.

Reproducible EUR/USD download, with standard Python and `curl`:

```bash
python3 scripts/download_dukascopy.py --start 2025-01-01 --end 2025-02-01
```

Dates in UTC: start inclusive, end exclusive. Files in
`data/dukascopy/EURUSD/`: raw hourly BI5, compressed tick CSVs, M1 candles with
separate bid and ask OHLC, and a manifest with status/SHA-256 of each hour.
Re-running reuses already downloaded and valid files. Run one download at a time
for the same destination. The script is specific to EUR/USD (scale 100000).

Empty hours, unavailable hours and HTTP errors are recorded; they are not filled
and not automatically treated as market close. Definitive failures produce partial
output and an error code. Check the manifest before using the series.
Volumes are quoted bid/ask amounts, not traded volume.

**These bid/ask files do not yet feed directly into the OHLC labeler below.**
Adapting the labeling to executable prices is the next stage: a buy enters at the
ask and exits at the bid; a sell enters at the bid and exits at the ask. Ticks
preserve the observed sequence to resolve which barrier was hit first.

Format verified at https://www.dukascopy.com/wiki/en/development/data-export/.
The public endpoint used has **hourly** files and milliseconds since the start of
the hour; the daily S3 file described in the documentation uses a different time
base. Months in the URL are zero-based. The `chub` catalog was queried with no
results for Dukascopy/forex; documentation was obtained directly from the provider.

## Initial OHLC labeler

Prototype in Python 3.11+, with no external dependencies. Evaluates buy and sell
at the open of each candle. Defaults: TP 50 pips, SL 20 pips, duration strictly
under 72 calendar hours. It does not train ML yet, nor execute orders.

## Data and execution

CSV of a single pair, with OHLC prices and the candle **open** time in UTC:

```csv
timestamp,open,high,low,close
2026-01-05T00:00:00+00:00,1.1000,1.1010,1.0990,1.1000
2026-01-05T00:01:00+00:00,1.1000,1.1050,1.0990,1.1040
```

```bash
python3 -m fxnn historico.csv --pip-size 0.0001 --bar-minutes 1 --tp 50 --sl 20 --max-hours 72
python3 -m unittest discover -s tests -v
```

`--pip-size` is explicit: use the pip size of the instrument/source, not the size
of the last digit of the quote. `--bar-minutes` states the candle resolution.
There is no automatic data download. The command writes/overwrites files in the
`output/` folder; change the destination with `--output`.

Outputs:

- `all_trades.csv`: every entry with a conclusive label, losses included.
- `selected_trades.csv`: winners selected without overlap.
- `hard_negatives.csv`: SL first, followed by TP within the original deadline.
- `summary.json`: parameters, counts and raw pips of the selected set.
- `validation.json`: independent audit, generated by `scripts.validate_run`.

**Ambiguous cases are discarded from all output CSVs.** Censored and uncertain
cases at the deadline boundary are also discarded. Only counts remain in the
summary. The original history file stays preserved.

Column `label`: 1 = TP first and within the deadline; 0 = SL first or deadline
expired without TP. Zero means failure of the criterion, not necessarily a
monetary loss in the timeout case.

## Labeling rules

- `take_profit`: TP hit before SL, with an upper duration bound < deadline.
- `stop_loss`: SL hit first.
- `ambiguous`: high/low touch both within the same candle; sequence unknown.
  Discarded.
- `boundary`: TP appears in the last allowed candle; OHLC does not prove a
  duration strictly shorter than the deadline. Discarded.
- `timeout`: the deadline ends without touching the barriers; exit at the close.
- `censored`: data ends or a candle is missing before the trade resolves.
  Discarded.

### Hard negatives: stop before target

An entry that loses 20 pips and only afterwards reaches +50 pips has `label=0` and
outcome `stop_loss`. The later gain does not change execution or the trade's PnL.
`post_stop_target_status=reached` identifies this subtype; the later timestamp goes
in `target_after_stop_time`. The search uses the original entry's deadline and stops
at gaps. `not_reached` means complete observation with no target; `censored` means
history was missing to determine the subtype, although the SL is already a certain
negative. `boundary` means the target is in the last candle, with an uncertain exact time.

If the SL happens at the open and the TP later in the same candle, the order is known.
If both appear only in the intrabar high/low, the order is ambiguous and the entry
is discarded. A target reached after 72 hours does not create a hard negative.

Entries use the open. Intrabar exits use the end of the candle as an upper time
bound, avoiding assuming precision that does not exist. A touch counts as a hit.
Price gap at the next open: the stop executes at that open (it may lose more than
20 pips); the TP executes at the target, assuming a limit order. In that case the
open determines the event order before the candle's high/low.

Any temporal gap censors pending trades, including the weekend close. Deliberately
conservative policy until the source calendar is integrated. It does not allow
crossing gaps by assuming the barriers stayed untouched.

## Overlap removal

With fixed TP and SL, the planned R:R is always 50/20 = 2.5; it does not
distinguish winners. Initial objective: maximize the sum of raw pips; tie-break:
minimize total time exposed. With a fixed TP, this is equivalent to maximizing the
number of compatible winners. Buy and sell compete for the same capacity: one
position at a time, on this single pair.

Interval dynamic programming solves the global set. Picking a single trade from
each conflict group can eliminate several successive trades that, together, yield
more. Intervals are [entry, exit): a new entry can occur exactly at the exit time.
Remaining ties are deterministic.

A high/low index finds the first touch without walking every candle of each trade:
labeling O(N log N), memory O(N). Prices stay Decimal. Selection costs O(W log W),
with W winners. The simple O(N×H) scanner remains as an independent reference,
including for post-stop classification.

## Validation with EUR/USD 2025

TP 50 / SL 20 / deadline <72h, M1 base of 371,964 candles:

- 743,928 entries evaluated (buy and sell per candle).
- 424,111 labels exported: 100,777 positives and 323,334 negatives.
- 35,264 negatives with SL before TP.
- 508 winners in the non-overlapping set.
- 319,817 candidates discarded due to gaps/end of series; no ambiguous ones in this
  specific parameter set. Ambiguous scenarios are covered by tests.

The full run took approximately 12 seconds on this machine. Comparison of 4,096
randomly drawn labels against the slow reference; additional audit of all 508
selected and 512 hard negatives. The optimal non-overlapping count was verified by
an independent algorithm for equal rewards. Randomized and edge-case tests cover
timeout, gaps, TP/SL ties, direction and the strict bound.

The large discard follows from the conservative policy of stopping at any missing
minute, weekends included. It is not equivalent to allowing positions open for
three days across gaps; the calendar and the data policy need to be handled before
simulating that exposure.

## Limits for the ML stage

Results deliberately use the future to create labels. Selection is retrospective,
neither an executable strategy nor an expected-return estimate. It does not include
spread, commission, swaps, position sizing or intrabar slippage. The sum of pips is
not a portfolio financial return. A future backtest needs those costs and executable prices.

Do not train only with the selected winners: that removes negatives and introduces
selection bias. Use conclusive labels from both classes and exclude inconclusive ones,
build features only with data available before the entry and split train/test
chronologically, purging labels that cross boundaries. The global selection also
depends on the future; do not use it as a prior filter of a predictive evaluation.

Output fields, PnL, duration, outcome and post-stop target are future **labeling**
information, never input features. When splitting train/test, account for the extra
horizon used to determine hard negatives. The labeling stage does not train models.
The `fxnn.research` command, described above, runs the first baseline following these controls.

## Neural network experiment

MLP 28 → 32 → 16 → 1, three fixed seeds, epoch selection on the inner temporal
validation. All features are kept in order to compare with the full logistic model.
[Prior protocol](docs/experiments/neural-v1-protocol.md).

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.neural --output output/neural_v1
```

The average of the three networks is the main prediction; individual results are
also preserved. It does not use random validation, nor pick the seed by the test.

[Result neural_v1](docs/experiments/neural-v1.md): the network lost to the logistic
model in the three external months; preserve that result before new attempts.

## Audit and fractional differentiation

[Ingestion audit](docs/experiments/universe-v1.md) reconciles labels and monthly
counts. [afml_v1](docs/experiments/afml-v1.md) compares the logistic model with
causal FFD of log-prices, choosing d only in the inner validation and using the
same candidates across all representations. SFI and permutation are diagnostics.
FFD improved July/August and worsened September: no consistent gain.

```bash
.venv/bin/python -m fxnn.audit --output output/universe_v1.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.afml --output output/afml_v1
```

Existing outputs are protected against overwriting. Commands are for reproduction;
do not repeat the search after looking at results. The AFML protocol must be committed.

Development audit for 2022–2023 completed without training: [result and per-fold
support](docs/experiments/multiyear-v1-data.md). Executable contract in
`configs/multiyear_v1.json`; `.venv/bin/python -m fxnn.data_audit` applies the
multi-year calendar, purging and class floors. The 2024 confirmation remains reserved.

---

<a id="português"></a>

# Português

Protocolo: [metodologia](docs/methodology.md), [decisões](docs/decisions.md)
e [roadmap](docs/roadmap.md). Rotulação retrospectiva e previsão causal são etapas
separadas. Resultados de classificação não representam rentabilidade executável.

## Ambiente e baseline

Python 3.13. Rotulador usa biblioteca padrão; pesquisa adiciona NumPy e scikit-learn.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python -m unittest discover -s tests -v
```

Depois de baixar e rotular a base anual pelos comandos abaixo:

```bash
.venv/bin/python -m fxnn.research --output output/research_v1
```

Implementa 28 features causais, unicidade, expurgo temporal e regressão logística.
Seleção por famílias ocorre na validação interna. Julho–setembro são avaliações
externas; outubro–dezembro ficam fora da modelagem inicial. Relatório JSON inclui
hashes de código/dados, parâmetros e métricas; previsões ficam no CSV local.
Diretório de experimento não vazio é recusado para preservar histórico.
Dados brutos, ambiente e outputs volumosos são ignorados pelo Git.

Primeiro resultado: [research_v1](docs/experiments/research-v1.md). Ganho preditivo
não foi consistente entre meses; ainda não existe estratégia validada.

## Base disponível — EUR/USD, 2022–2025

Quatro arquivos anuais HistData M1 disponíveis localmente, com registros nos
12 meses de cada ano. Total: 1.439.606 candles normalizados.

| Ano | Candles | Linhas em quarentena | Lacunas |
|---|---:|---:|---:|
| 2022 | 372.745 | 120 | 1.111 |
| 2023 | 322.518 | 120 | 1.871 |
| 2024 | 372.379 | 0 | 1.601 |
| 2025 | 371.964 | 120 | 966 |

2022–2024 baixados em 13/09/2026 pelo downloader existente. Cada ano tem CSV
`data/histdata/EURUSD/EURUSD_<ano>_m1_bid_utc.csv`, ZIP original, manifesto
com hashes, relatório de lacunas e quarentena. Para reproduzir, execute
`python3 scripts/download_histdata.py --year <ano>` para cada ano desejado.
Validação de ingestão verifica CRC, OHLC, ordem temporal e presença dos 12 meses.

2023 tem cobertura menor, especialmente entre março e julho; presença dos
12 meses não significa série completa. Lacunas incluem fechamentos de mercado
e possíveis falhas de dados, ainda sem classificação e sem preenchimento.
2022 e 2023 tiveram 60 timestamps duplicados cada: todas as 120 ocorrências
de cada ano foram isoladas. Os novos anos ainda não foram rotulados nem usados
nos experimentos existentes, que continuam restritos a 2025.

### Base inicial de pesquisa — 2025

HistData M1, com os 12 meses de 2025. Arquivo normalizado:
`data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv`.
Baixar/reproduzir e validar:

```bash
python3 scripts/download_histdata.py --year 2025
```

Arquivo original ZIP, relatório do provedor, manifesto com hashes/contagens,
lista de lacunas e quarentena ficam na mesma pasta. O histórico é **bid-only**;
sem ask, spread histórico ou volume negociado. Horários convertidos de EST fixo
(UTC−5, sem horário de verão), conforme FAQ do provedor, para UTC.

Arquivo 2025 apresentou 60 timestamps repetidos, com 120 linhas na hora 19h de
26/10 no horário da fonte. Todas as ocorrências foram isoladas em quarentena;
não foi inferido deslocamento de horário nem escolhida uma versão dos preços.
Lacunas restantes ficam registradas e não são preenchidas. Cobrir 12 meses não
significa que todos os minutos sejam utilizáveis.

Esse CSV é compatível com o rotulador inicial:

```bash
python3 -m fxnn data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv --pip-size 0.0001 --bar-minutes 1 --verify-samples 2048 --output output/eurusd_2025
python3 -m scripts.validate_run data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv --output output/eurusd_2025
```

O comando acima ainda usa preços de uma única série, sem custos, e scanner
O(N log N); não representa backtest executável. Três dias limitam duração de cada
operação; **um ano é o mínimo inicial do histórico**, não três dias.

Fonte/formato: https://www.histdata.com/f-a-q/.
Alternativa usada após falhas HTTP 503 generalizadas no feed Dukascopy.

## Histórico Dukascopy

Tentativa anual reproduzível: `python3 scripts/download_year.py --year 2025`.
Usa arquivos diários M1 bid/ask e salva progresso por arquivo em JSONL. Cache
parcial existente não constitui base anual completa. Não misturar automaticamente
preços de provedores diferentes para preencher lacunas.

Download reproduzível de EUR/USD, com Python padrão e `curl`:

```bash
python3 scripts/download_dukascopy.py --start 2025-01-01 --end 2025-02-01
```

Datas em UTC: início inclusivo, fim exclusivo. Arquivos em
`data/dukascopy/EURUSD/`: BI5 brutos por hora, ticks CSV compactados, candles M1
com OHLC bid e ask separados e manifesto com status/SHA-256 de cada hora.
Reexecução reaproveita arquivos baixados e válidos. Execute um download por vez
para o mesmo destino. O script é específico para EUR/USD (escala 100000).

Horas vazias, indisponíveis e erros HTTP ficam registrados; não são preenchidos
nem automaticamente considerados fechamento de mercado. Falhas definitivas
produzem saída parcial e código de erro. Verifique manifesto antes de usar série.
Volumes são quantidades cotadas de bid/ask, não volume negociado.

**Esses arquivos bid/ask ainda não entram diretamente no rotulador OHLC abaixo.**
Adaptar rotulação para preços executáveis é etapa seguinte: compra entra no ask
e sai no bid; venda entra no bid e sai no ask. Ticks preservam sequência observada
para resolver qual barreira foi atingida primeiro.

Formato conferido em https://www.dukascopy.com/wiki/en/development/data-export/.
O endpoint público utilizado tem arquivos **horários** e milissegundos desde
início da hora; arquivo diário do S3 descrito na documentação usa outra base de
tempo. Meses na URL começam em zero. Catálogo `chub` consultado sem resultados
para Dukascopy/forex; documentação foi obtida diretamente do provedor.

## Rotulador OHLC inicial

Protótipo em Python 3.11+, sem dependências externas. Avalia compra e venda na
abertura de cada candle. Valores padrão: TP 50 pips, SL 20 pips, duração
estritamente inferior a 72 horas corridas. Ainda não treina ML nem executa ordens.

## Dados e execução

CSV de um único par, com preços OHLC e horário **de abertura** do candle em UTC:

```csv
timestamp,open,high,low,close
2026-01-05T00:00:00+00:00,1.1000,1.1010,1.0990,1.1000
2026-01-05T00:01:00+00:00,1.1000,1.1050,1.0990,1.1040
```

```bash
python3 -m fxnn historico.csv --pip-size 0.0001 --bar-minutes 1 --tp 50 --sl 20 --max-hours 72
python3 -m unittest discover -s tests -v
```

`--pip-size` é explícito: use tamanho do pip do instrumento/fonte, não tamanho
do último dígito da cotação. `--bar-minutes` informa resolução dos candles.
Não há download automático de dados. Comando grava/substitui arquivos na pasta
`output/`; altere destino com `--output`.

Saídas:

- `all_trades.csv`: todas as entradas com rótulo conclusivo, incluindo perdas.
- `selected_trades.csv`: vencedoras selecionadas sem sobreposição.
- `hard_negatives.csv`: SL primeiro, seguido por TP dentro do prazo original.
- `summary.json`: parâmetros, contagens e pips brutos do conjunto selecionado.
- `validation.json`: auditoria independente, gerada por `scripts.validate_run`.

**Casos ambíguos são descartados de todos os CSVs de saída.** Casos censurados
e incertos no limite de prazo também são descartados. Apenas contagens permanecem
no resumo. Arquivo histórico original permanece preservado.

Coluna `label`: 1 = TP primeiro e dentro do prazo; 0 = SL primeiro ou prazo
expirado sem TP. Zero significa falha do critério, não necessariamente prejuízo
monetário no caso de timeout.

## Regras de rotulação

- `take_profit`: TP atingido antes do SL, com limite superior de duração < prazo.
- `stop_loss`: SL atingido primeiro.
- `ambiguous`: máxima/mínima tocam ambos no mesmo candle; sequência desconhecida.
  Descartado.
- `boundary`: TP aparece no último candle permitido; OHLC não comprova duração
  estritamente menor que prazo. Descartado.
- `timeout`: prazo termina sem tocar barreiras; saída no fechamento.
- `censored`: dados terminam ou há candle faltante antes de resolver operação.
  Descartado.

### Negativos difíceis: stop antes do alvo

Uma entrada que perde 20 pips e só depois chega a +50 pips tem `label=0` e
resultado `stop_loss`. O ganho posterior não altera execução nem PnL da operação.
`post_stop_target_status=reached` identifica esse subtipo; horário posterior fica
em `target_after_stop_time`. Busca usa prazo da entrada original e para em lacunas.
`not_reached` significa observação completa sem alvo; `censored` significa que
faltou histórico para determinar o subtipo, embora o SL já seja um negativo certo.
`boundary` significa alvo no último candle, com horário exato incerto.

Se SL acontece na abertura e TP depois no mesmo candle, ordem é conhecida.
Se ambos aparecem apenas na máxima/mínima intrabar, ordem é ambígua e entrada
é descartada. Um alvo alcançado depois de 72 horas não cria negativo difícil.

Entradas usam abertura. Saídas intrabar usam fim do candle como limite superior
de horário, evitando assumir precisão inexistente. Toque conta como atingimento.
Gap de preço na abertura seguinte: stop executado nessa abertura (pode perder
mais de 20 pips); TP executado no alvo, assumindo ordem limite. Nesse caso abertura
determina ordem do evento antes da máxima/mínima do candle.

Qualquer lacuna temporal censura operações pendentes, incluindo fechamento de
fim de semana. Política deliberadamente conservadora até integrar calendário da
fonte. Não permite atravessar lacunas assumindo que barreiras ficaram intactas.

## Remoção de sobreposições

Com TP e SL fixos, R:R planejado é sempre 50/20 = 2,5; não distingue vencedoras.
Objetivo inicial: maximizar soma de pips brutos; empate: minimizar tempo total
exposto. Com TP fixo, equivale a maximizar quantidade de vencedoras compatíveis.
Compra e venda disputam mesma capacidade: uma posição por vez, nesse único par.

Programação dinâmica de intervalos resolve conjunto global. Escolher uma única
operação de cada grupo de conflitos pode eliminar várias operações sucessivas
que, juntas, rendem mais. Intervalos são [entrada, saída): nova entrada pode
ocorrer exatamente no horário de saída. Empates restantes são determinísticos.

Índice de máximas/mínimas encontra primeiro toque sem percorrer todos os candles
de cada operação: rotulação O(N log N), memória O(N). Preços permanecem Decimal.
Seleção custa O(W log W), com W vencedoras. Scanner simples O(N×H) permanece como
referência independente, inclusive para classificação posterior ao stop.

## Validação com EUR/USD 2025

TP 50 / SL 20 / prazo <72h, base M1 de 371.964 candles:

- 743.928 entradas avaliadas (compra e venda por candle).
- 424.111 rótulos exportados: 100.777 positivos e 323.334 negativos.
- 35.264 negativos com SL antes de TP.
- 508 vencedoras no conjunto sem sobreposição.
- 319.817 candidatos descartados por lacunas/fim de série; nenhum ambíguo nesse
  conjunto específico de parâmetros. Cenários ambíguos estão cobertos por testes.

Execução completa levou aproximadamente 12 segundos nesta máquina. Comparação
de 4.096 rótulos sorteados com referência lenta; auditoria adicional de todas as
508 selecionadas e 512 negativos difíceis. Contagem ótima sem sobreposição
verificada por algoritmo independente para recompensas iguais. Testes aleatórios
e de casos-limite cobrem timeout, gaps, empate TP/SL, direção e limite estrito.

Grande descarte decorre de política conservadora de parar em qualquer minuto
faltante, inclusive finais de semana. Não equivale a permitir posições abertas
por três dias através de lacunas; calendário e política de dados precisam ser
tratados antes de simular essa exposição.

## Limites para etapa de ML

Resultados usam futuro deliberadamente para criar rótulos. Seleção é retrospectiva,
não estratégia executável nem estimativa de retorno esperado. Não inclui spread,
comissão, swaps, tamanho de posição ou slippage intrabar. Soma de pips não é retorno
financeiro de carteira. Futuro backtest precisa desses custos e preços executáveis.

Não treinar apenas com vencedoras selecionadas: isso remove negativos e introduz
viés de seleção. Usar rótulos conclusivos de ambas as classes e excluir inconclusivos,
criar features apenas com dados disponíveis antes da entrada e separar treino/teste
cronologicamente, expurgando rótulos que atravessam fronteiras. Seleção global também
depende do futuro; não usá-la como filtro prévio de uma avaliação preditiva.

Campos de saída, PnL, duração, resultado e alvo posterior ao stop são informações
futuras de **rotulação**, nunca features de entrada. Ao dividir treino/teste,
considerar o horizonte adicional usado para determinar negativos difíceis.
A etapa de rotulação não treina modelos. O comando `fxnn.research`, descrito acima,
executa o primeiro baseline seguindo esses controles.

## Experimento com rede neural

MLP 28 → 32 → 16 → 1, três seeds fixas, seleção de épocas na validação temporal
interna. Todas as features são mantidas para comparar com logística completa.
[Protocolo prévio](docs/experiments/neural-v1-protocol.md).

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.neural --output output/neural_v1
```

Média das três redes é previsão principal; resultados individuais também são
preservados. Não utiliza validação aleatória nem escolhe seed pelo teste.

[Resultado neural_v1](docs/experiments/neural-v1.md): rede perdeu para logística
nos três meses externos; preservar esse resultado antes de novas tentativas.

## Auditoria e diferenciação fracionária

[Auditoria de ingestão](docs/experiments/universe-v1.md) reconcilia labels e
contagens mensais. [afml_v1](docs/experiments/afml-v1.md) compara logística com
FFD causal de log-preços, escolhendo d somente na validação interna e usando
os mesmos candidatos em todas as representações. SFI e permutação são diagnósticos.
FFD melhorou julho/agosto, piorou setembro: sem ganho consistente.

```bash
.venv/bin/python -m fxnn.audit --output output/universe_v1.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  .venv/bin/python -m fxnn.afml --output output/afml_v1
```

Saídas existentes são protegidas contra sobrescrita. Comandos para reprodução;
não repetir busca após olhar resultados. O protocolo AFML precisa estar commitado.

Auditoria de desenvolvimento 2022–2023 concluída sem treino: [resultado e
suporte por fold](docs/experiments/multiyear-v1-data.md). Contrato executável em
`configs/multiyear_v1.json`; `.venv/bin/python -m fxnn.data_audit` aplica calendário
multianual, expurgo e pisos de classe. Confirmação 2024 permanece reservada.
