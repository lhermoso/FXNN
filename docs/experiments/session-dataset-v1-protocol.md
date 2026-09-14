# Reconstrução session_dataset_v1

Decisão de Léo em 14/09/2026, registrada antes de gerar os novos rótulos.
Substitui a política de lacunas somente nesta versão; experimentos anteriores
e arquivos originais permanecem intactos. Não ajusta modelos (zero fits).

## Contrato

- Originais HistData EURUSD bid M1 normalizados em UTC, hashes conferidos contra
  inventário registrado. Somente desenvolvimento 2022–2023. Sem preços ou labels
  de 2024, sem execução de 2025.
- Mercado semanal: domingo 17h até sexta 17h America/New_York. Timestamps e
  labels UTC, conversão histórica de DST (21h ou 22h UTC). Convenção semanal,
  não calendário universal de corretoras; feriados extraordinários não modelados.
  Quotes fora dessa janela são preservados na fonte e excluídos desta versão,
  com contagem explícita.
- Long e short em toda abertura observada dentro da sessão. TP 50 pips, SL
  20 pips, prazo 4.320 minutos de mercado aberto. Fim de semana pausa o prazo;
  ausência de cotação durante sessão aberta não pausa.
- Ignorar até 14 minutos ausentes consecutivos de sessão. Sem OHLC sintético,
  interpolação ou preenchimento. Censurar operação ainda aberta ao completar
  15 minutos ausentes, independentemente de quando retorna a próxima cotação.
  Se TP/SL ocorreu antes, manter resultado. Fim do arquivo censura imediatamente.
- Detectar barreiras no OHLC observado. Se ambas são tocadas no mesmo candle
  sem precedência conhecida na abertura, ambíguo. Gap contra stop executa na
  abertura observada, podendo perder mais de 20 pips; TP limitado ao alvo.
  TP intrabar no último minuto do prazo fica boundary por exigir menos de 72h;
  SL no mesmo minuto é negativo. Timeout usa último fechamento observado;
  pode estar até 14 minutos de sessão defasado. Registrar essa defasagem.
- Positivo = TP primeiro antes do prazo; negativo = SL ou timeout. Censura,
  ambiguidade e boundary ficam no arquivo completo de candidatos, fora de X/y.
  Não calcular hard negatives/post_stop_target nesta reconstrução.
- Features: mesmas 28 fórmulas causais, agora janelas de 5/15/60/240
  OBSERVAÇÕES, não minutos corridos. São necessários 241 candles observados
  anteriores; gaps grandes reiniciam aquecimento. Pequenos gaps e fechamento
  semanal não reiniciam. Só preços anteriores à abertura entram em X.
- Preservar máscaras CUSUM separadas h=0.0005 e h=0.001. Acumulador reinicia
  apenas em gaps grandes; sinal no fechamento permite próxima abertura
  observada, inclusive depois de gap curto/fim de semana. Sem ranking ou fits.
- Mesmas fronteiras trimestrais do protocolo pai. Expurgo usa o vencimento
  completo de 72h abertas e buffer que cobre 241 candles observados anteriores
  à fronteira. Avaliação exclui horizontes que alcançam o fim do trimestre.

## Artefatos e validação

Salvar localmente dataset.npz (X/y, identidades, prazos, máscaras e partições),
candidates.npz (inclusive excluídos), manifest.json (hashes/config/schema) e
report.json (cobertura mensal, trimestral, classes e causas de exclusão).
Sem dados volumosos no Git. Gravar apenas em diretório novo, sem sobrescrever.
Verificar leitura integral dos arrays sem pickle, alinhamento, finitude de X,
disjunção temporal, prazo e hashes. Testes sintéticos: 14/15 minutos, fim de
semana/DST, referência escalar independente, causalidade e expurgo.

Comparar cobertura com auditoria histórica multiyear-v1-data.md, por mês UTC,
sem confundir mudança de universo/relógio com melhoria preditiva. Mais amostras
não demonstra sinal ou lucro. A hipótese de ignorar preços não observados é
explícita; ausência de registro não prova ausência de toque intragap.

Referência: López de Prado, AFML, snippets 3.2–3.4. Ausência de uma observação
não impõe censura no código do livro. Limite de 15 minutos e calendário semanal
são decisões deste projeto. Modelos antigos não são controles compatíveis;
treinamento posterior requer protocolo próprio.
