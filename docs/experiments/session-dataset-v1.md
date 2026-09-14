# session_dataset_v1 — dataset reconstruído

Pré-registro `06408bf`; código executado `e006d04`. Somente 2022–2023, zero fits novos. Ledger global permanece 48/1.000. Confirmação 2024 fechada.

## Resultado

- Candles originais: 695.263. Dentro da sessão semanal: 692.087; fora da janela: 3.176, preservados na fonte.
- Candidatos long/short: 1.384.174. Sem candles ou entradas sintéticas.
- Dataset utilizável: **1.105.737 linhas × 28 features**, contra 558.224 antes (+547.513; +98,1%).
- Positivos: 304.546; negativos: 801.191.
- Censurados: 222.062 (16,04% dos candidatos), contra 630.711 (45,36%) no universo histórico de 1.390.526 candidatos.
- Ambíguos: 47; boundary: 1. Conclusivos sem histórico válido: 56.327.
- 2.194 gaps curtos tolerados; 744 gaps longos reiniciam histórico. Fechamento semanal não conta como gap.
- 936 timeouts entre todos os candidatos; apenas um usa fechamento defasado, por um minuto aberto.

Calendário: domingo 17h–sexta 17h Nova York, convertido historicamente para UTC (DST). Janela semanal de referência; não modela feriados de cada corretora. Prazo: 4.320 minutos abertos. Gaps de até 14 minutos ignorados; a partir de 15, censura. Features contam candles observados, sem fill.

## Cobertura por trimestre de entrada

Contagens abaixo abrangem cada trimestre inteiro, antes do expurgo de fim de trimestre. Não misturar com suporte externo dos folds.

| Período | Retidos antes | Retidos agora | Censurados antes | Censurados agora |
|---|---:|---:|---:|---:|
| 2022Q1 | 71.494 | 180.614 | 84.848 | 2.093 |
| 2022Q2 | 91.490 | 164.556 | 65.707 | 13.954 |
| 2022Q3 | 112.157 | 172.784 | 49.562 | 8.548 |
| 2022Q4 | 105.554 | 180.583 | 50.198 | 2.737 |
| 2023Q1 | 58.126 | 106.879 | 77.404 | 43.006 |
| 2023Q2 | 12.878 | 15.396 | 101.393 | 97.519 |
| 2023Q3 | 40.350 | 113.556 | 107.258 | 44.820 |
| 2023Q4 | 66.175 | 171.369 | 94.341 | 9.385 |

**2023Q2 continua com cobertura ruim.** Pequenos gaps explicavam grande perda global, mas lacunas longas permanecem nesse período. A reconstrução não recupera preços que nunca foram observados.

## Avaliação externa após expurgo

| Fold | Linhas | Positivos | Negativos | CUSUM 0.0005 | CUSUM 0.001 |
|---|---:|---:|---:|---:|---:|
| 2023Q2 | 14.964 | 1.105 | 13.859 | 742 | 236 |
| 2023Q3 | 106.339 | 24.568 | 81.771 | 5.267 | 1.733 |
| 2023Q4 | 164.679 | 50.567 | 114.112 | 8.651 | 2.834 |

## Uso e artefatos locais

Local: `/Users/leohermoso/FXNN-trading-clock/output/session_dataset_v1/`.

- `dataset.npz`: X/y, timestamps UTC, índices originais, direção (-1 short / +1 long), info_ends, máscaras CUSUM e índices train/validation/refit/test por fold.
- `candidates.npz`: todos os candidatos, inclusive censurados/ambíguos; preços, outcomes, elegibilidade e retenção separados de X.
- `manifest.json`: contrato, schema, hashes de fonte/código/artefatos e versões.
- `report.json`: cobertura mensal, folds, histórico e diagnóstico.

Ler arrays com `np.load(path, allow_pickle=False)`. O loader histórico `research.load_dataset` não é compatível com este contrato; não usar seus splits de 72h corridas para esta versão. Nenhum scaler ou seletor foi ajustado. Nenhum campo de resultado entrou em X.

Reprodução em checkout limpo do código registrado (destino novo obrigatório):

```sh
.venv/bin/python -m fxnn.session_dataset --output output/session_dataset_v1_reproduction
```

## Validação

118 testes passaram; compileall e git diff --check passaram. Casos sintéticos cobrem 14/15 minutos, calendário/DST, causalidade, expurgo, rotulação contra referência escalar independente e exportação. Todos os arrays gravados foram relidos sem pickle e comparados. As 1.105.737 identidades/rótulos/prazos/máscaras foram confrontadas com o arquivo completo de candidatos. Hashes dos originais e ledger permaneceram iguais.

Mais linhas não prova previsibilidade nem lucro. Universo, calendário e histórico mudaram: modelos/controles antigos não são diretamente comparáveis. Bid-only, ausência de custos e risco intragap continuam limitações. Hard negatives após stop não foram calculados nesta reconstrução.

Hashes dos datasets:

- `dataset.npz`: `510c32501f75071c616d79d7406bc772b9e0d75c3aa10f1d6e084ca43baa05d5` (124134017 bytes).
- `candidates.npz`: `e5f2e3ae8250f22048acc18b6c13d6458d0dbfb7130a639c262d81d16c7dfd6b` (8929030 bytes).
