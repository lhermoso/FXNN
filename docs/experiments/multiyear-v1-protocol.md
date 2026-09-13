# Reserva temporal multiyear_v1

Fixada por Léo em 13/09/2026, antes de gerar/examinar labels de 2022–2024.

| Período UTC | Papel |
|---|---|
| 2022-01-01 ≤ entrada < 2024-01-01 | Desenvolvimento: 2022–2023 |
| 2024-01-01 ≤ entrada < 2025-01-01 | Confirmação histórica reservada: 2024 |
| 2025 | Exploratório; resultados já examinados |

Regras valem pelo timestamp UTC da entrada, não apenas pelo nome do arquivo
anual (que usa EST fixo). Não escolher outro ano de confirmação após olhar
resultados, nem mover meses entre conjuntos em função de desempenho.

## Condições antes de abrir confirmação

- Desenvolvimento usa somente 2022–2023, com treino anterior à validação,
  transformações/seleção dentro do fold e expurgo dos horizontes de labels.
- Nenhum treino, seleção de modelo, calibração ou threshold usa dados de 2025
  para prever 2024. O conhecimento dos experimentos anteriores de 2025 já
  influenciou a pesquisa; 2024 não é uma confirmação prospectiva independente.
- Antes de gerar/examinar labels ou métricas de 2024, versionar protocolo
  operacional completo: universo, política de lacunas, fronteiras dos folds
  internos, features, modelos, orçamento de tentativas, seeds, custos quando
  aplicáveis, métricas, critérios de aceitação e regra de seleção final.
- Reajuste final só usa passado anterior a 2024. Remover labels de treino cujo
  horizonte alcance confirmação; buffer deve cobrir maior histórico efetivo.
  Candles anteriores podem aquecer features causais sem labels futuros.
- Confirmação é uma avaliação única do procedimento congelado. Falha é
  registrada; revisões posteriores tornam 2024 exploratório e exigem nova
  confirmação. Não testar candidatos repetidamente nesse ano.
- Esta reserva não autoriza executar modelagem imediatamente: protocolo
  específico de cada experimento ainda deve ser registrado. Na reserva inicial
  nenhum label novo foi gerado; a auditoria posterior da #4 está relatada em
  [multiyear-v1-data.md](multiyear-v1-data.md).

Auditoria técnica de cobertura de todos os anos é permitida antes dos labels:
timestamps, duplicatas, integridade e confronto de disponibilidade entre fontes.
Não selecionar janelas por retorno, barreiras, taxa de acerto ou lucro.

## Cobertura e validade econômica

[Triagem de lacunas](../data-coverage.md) ainda não fornece calendário histórico
completo do provedor. Até resolvê-lo, manter censura existente; não preencher
minutos nem liberar operações através de fechamentos por inferência.

HistData M1 é bid-only. Serve para pesquisa preditiva sob essa limitação;
classificação não demonstra lucro. Validação econômica exige bid/ask históricos
do período avaliado e regras de execução: compra entra no ask/sai no bid;
venda entra no bid/sai no ask; incluir comissão, swaps, slippage e posições
sobrepostas. Ticks ajudam a resolver sequência intraminuto. Arquivos parciais
não validam um ano inteiro, e séries de provedores distintos não serão coladas.

Confirmação prospectiva exigirá período que ocorra após congelar o procedimento;
suas datas ainda não foram fixadas. Não chamar retrospectivamente todo 2026 de
futuro: parte do ano já transcorreu na data desta decisão.

## Fechamento de dados da #4 — contrato operacional v1

Contrato executável: `configs/multiyear_v1.json`; implementação em
`fxnn/protocol.py` e auditoria `python -m fxnn.data_audit`. Esta seção completa
as regras de dados. Os contratos específicos de CUSUM, volatilidade e regra
primária deverão ser registrados antes de executar cada etapa. A confirmação
continua bloqueada até o congelamento do pipeline completo na #9.

### Fonte e política conservadora

HistData EURUSD M1 bid de 2022 e 2023 é a fonte única de desenvolvimento.
Arquivos são unidos em ordem e filtrados pelo timestamp UTC da entrada;
não interpolar preços nem inserir Dukascopy. Preservar ZIP, CSV, hashes,
manifestos, status do provedor e quarentena. Integridade de 2024 pode ser
verificada; seus preços não entram no rotulador desta auditoria.

Não há calendário histórico de sessões confirmado. Toda ausência de M1,
incluindo fim de semana candidato, feriado ou quarentena, interrompe sequência:

- Na primeira abertura observada após lacuna, reiniciar estado de filtros.
- Features exigem 241 minutos consecutivos anteriores e continuidade até a
  abertura de entrada; nunca consultar a próxima lacuna para aceitar entrada.
- CUSUM futuro reinicia ambos os acumuladores; não calcular retorno através
  da lacuna nem transportar evento anterior para a reabertura.
- Trade ainda aberto ao faltar candle recebe `censored`; não vira perda,
  timeout ou saída presumida. Trade encerrado antes da ausência permanece válido.
- TP/SL fixos 50/20, horizonte estritamente menor que 72h e ambiguidades
  preservam scanner anterior. Fechamento real não implica caminho conhecido.
- Nenhuma seleção ex ante baseada em conhecer censura futura. Métricas sobre
  conclusivos são condicionais; auditoria mantém denominador de todas as entradas.

Essa política sacrifica cobertura e mantém viés de seleção reconhecido;
não resolve execução econômica. Distinguir fechamento real de falha continuará
pendente para #9. Aqui o fechamento metodológico é **exploratório com bloqueio**.

### Partições congeladas

Treino expansivo inicia em 2022-01-01 UTC. Intervalos de avaliação são
fechados à esquerda e abertos à direita.

| Fold | Validação interna | Avaliação externa exploratória |
|---|---|---|
| 2023Q2 | 2023-01-01 até 2023-04-01 | 2023-04-01 até 2023-07-01 |
| 2023Q3 | 2023-04-01 até 2023-07-01 | 2023-07-01 até 2023-10-01 |
| 2023Q4 | 2023-07-01 até 2023-10-01 | 2023-10-01 até 2024-01-01 |

Treino interno termina antes da validação; refit termina antes da avaliação.
Informação conservadora = entrada +4320 minutos. Exigir fim dessa informação
estritamente anterior à fronteira menos buffer de 241 minutos. Avaliação exige
fim de informação estritamente anterior ao seu término. Histórico maior em
nova transformação exige novo buffer pré-registrado; nunca reduzir os 241.
As fronteiras suportam virada de ano e não dependem do nome do CSV.

### Suporte e parada

Cada treino interno, validação interna e refit exige ≥1.000 candidatos
conclusivos com features válidas, incluindo ≥100 exemplos de **cada** classe.
Pisos são operacionais, não cálculo de poder estatístico: overlap permanece.
Ausência de suporte interrompe a comparação inteira daquela etapa; registrar
fold e todas as contagens. Não pular fold, escolher meses melhores, reduzir piso,
replicar classe rara ou trocar universo depois de inspecionar resultados.

Suporte externo é relatado somente após produzir previsões; insuficiência torna
conclusão inconclusiva e não decide ajuste/seleção. A auditoria de dados pode
contar labels externos exploratórios, mas nunca labels reservados de 2024.
`require_training_support` não acessa labels externos. Próximos runners devem
chamar essa guarda antes de qualquer ajuste; runners históricos ficam intactos.

### Orçamento global e regra de seleção

Máximo **1.000 ajustes de modelo** somados às etapas #5–#9, incluindo treino
interno, refit, controles, membros de ensemble, seeds e confirmação. Auditoria
determinística de labels consome zero ajustes. Registrar cada tentativa antes
de iniciá-la em ledger local com ID, etapa, fold, parâmetros, seed, hashes,
status e resultado; falha numérica também consome ajuste. Não repetir resultado
negativo, aumentar teto ou usar rerun para substituir tentativa desfavorável.

Limites cumulativos, sem produto cartesiano entre etapas:

- #5: até dois limiares CUSUM; labels/features/logística congelados.
- #6: um estimador causal de volatilidade, até duas escalas de barreiras.
- #7: uma regra primária determinística, até três thresholds.
- #8: dois esquemas, até 20 membros, seeds 0/1/2; no máximo 720 ajustes
  nos três folds (2 esquemas ×3 seeds ×20 membros ×2 ajustes ×3 folds).
- #9: uma configuração final e uma abertura de confirmação; orçamento restante
  cobre eventual calibração/custos após protocolo próprio. Sem busca de FFD.

Seleção de variantes ocorre exclusivamente por menor log-loss interna sobre
identidades comuns definidas antes de treinar; empate favorece controle simples,
depois ordem fixa da grade. Thresholds 0,3/0,4/0,5 são relatados; escolha de
threshold econômico depende do contrato da #9 e nunca de resultado externo.

Comparação controlada conserva universo de avaliação e relata constante,
log-loss, Brier, AP, ROC-AUC, suporte e cobertura. Considerar ganho classificatório
consistente somente se candidato superar controle em log-loss em todos os três
folds e não piorar Brier médio. Resultado misto preserva controle como conclusão
da hipótese; não autoriza nova busca. Isso é conclusão exploratória do procedimento,
não seleção de hiperparâmetros pelo teste nem prova de lucro. Tarefas com labels
diferentes não competem por log-loss bruta. Critério econômico permanece bloqueado
até fonte bid/ask, calendário e custos adequados serem registrados na #9.

### Execução autorizada nesta etapa

Versionar este contrato antes de executar a auditoria real:

```bash
.venv/bin/python -m fxnn.data_audit --protocol configs/multiyear_v1.json \
  --output output/multiyear_v1/data_audit.json
```

Gera labels de desenvolvimento em memória, somente para contagens, sem modelos
nem arquivos de trades novos. Saída agregada local é exclusiva (não sobrescreve),
com hashes de código/configuração/insumos e versões. Relatório resumido versionado
registra inclusive insuficiências. Confirmação 2024 e experimentos anteriores
não são executados nem sobrescritos.
