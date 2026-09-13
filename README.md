# FXNN — pesquisa de machine learning para Forex

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

## Base anual disponível — EUR/USD, 2025

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
