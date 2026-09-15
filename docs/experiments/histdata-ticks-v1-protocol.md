# histdata_ticks_v1 — aquisição bid/ask de desenvolvimento (#19)

Pré-registro de 2026-09-15, antes da primeira aquisição de ZIP/auditoria real.
Código, fixtures e configuração são registrados no mesmo commit. Nenhum fit,
rótulo, seleção, simulação econômica ou escrita no ledger é necessário.

## Universo e reserva

Fonte única: HistData Generic ASCII tick, EURUSD, todos os 24 meses EST de
janeiro/2022 a dezembro/2023. Configuração: `configs/histdata_ticks_v1.json`.
Piloto operacional opcional somente janeiro/2022, seguido pelos demais meses
fixos; nenhum mês será escolhido por qualidade, retorno ou resultado de modelo.
Não misturar M1 antigo ou outro feed, não comprar dados.

Desenvolvimento por **UTC [2022-01-01, 2024-01-01)**. Dezembro/2023 EST pode
conter registros UTC de 2024: parser valida timestamp antes de converter preços;
registros fora do intervalo vão para `reserved.jsonl` somente com sequência,
timestamp e motivo. Preços reservados não aparecem em CSV, quarentena ou
estatísticas. ZIP original permanece preservado, sem inspeção desses preços.
Timestamp inválido impede verificar elegibilidade: somente timestamp, sequência
e motivo vão à quarentena; preços permanecem exclusivamente no ZIP.

## Fonte verificada sem payload

- [FAQ oficial](https://www.histdata.com/f-a-q/): Generic ASCII tick fornece
  `DateTime,Bid,Ask,Volume`; EST fixo, sem horário de verão. Bid/ask pertencem ao
  mesmo registro; não inverter lados. Volume não será usado como feature.
- [Formulário janeiro/2022](https://www.histdata.com/download-free-forex-historical-data/?/ascii/tick-data-quotes/eurusd/2022/1):
  `file_down`, POST `/get.php`, `date=2022`, `datemonth=202201`, `platform=ASCII`,
  `timeframe=T`, `fxpair=EURUSD`, token `tk`. Captura de página não contém preços.
- `chub search HistData` não retornou documentação; busca curl não retornou
  documentação relevante. Usados FAQ/form oficiais e manual local do curl.
  Não há ID chub pertinente para `get`/`annotate`.

Formato de timestamp esperado: `YYYYMMDD HHMMSSmmm`, com milissegundos.
Essa precisão é hipótese técnica explícita antes de ler arquivo real; formato
inesperado não será inferido silenciosamente. Nenhuma linha válida implica
falha de aquisição utilizável, preservando ZIP e diagnóstico. Eventual mudança
exige emenda técnica registrada antes de reauditar; nunca escolher ordem de
preços por plausibilidade. CSV sem cabeçalho, quatro campos separados por vírgula.

## Download, limites, retomada

`scripts/download_histdata_ticks.py` usa stdlib e curl via argv, sem shell.
`--disable` desativa configuração pessoal do curl. Somente URLs canônicas HTTPS
`www.histdata.com`; **não seguir redirects**. HTTP diferente de 200, incluindo
3xx, vira falha específica registrada. Essa política pode rejeitar mudança
legítima da fonte; nesse caso relatar falha, não declarar fonte indisponível.
Cada mês permite no máximo duas tentativas totais, inclusive interrupções.
Página: 60 segundos/2 MiB; arquivo: 300 segundos/2 GiB. Conteúdo ZIP descompactado:
8 GiB no total; somente `DAT_ASCII_EURUSD_T_YYYYMM.csv` e opcional `.txt`, nomes
únicos, tamanhos positivos, sem criptografia, CRC integral. Nunca extrair caminhos.

Diretório novo `data/histdata_ticks_v1/EURUSD`, separado das pesquisas históricas.
Lock exclusivo bloqueia concorrência. Tentativas `attempt-NNN` são imutáveis;
falha preserva páginas, resposta HTTP, corpo recebido e `failure.json`.
Um processo interrompido pode deixar lock: conferir ausência de escritor ativo
antes de remover somente esse lock. Não apagar/alterar tentativas.

`completed.json` registra configuração, mês, tentativa e SHA-256/tamanho de todos
os arquivos. Retomada verifica identidades, todos os hashes/tamanhos e ZIP/CRC;
adulteração falha fechada, sem sobrescrever. Falhas esgotadas não baixam de novo.
`manifest-NNN.json` consolidado imutável lista todos os 24 meses como concluídos,
pendentes (piloto) ou falhos. Se execução inteira interromper, retomada consulta
os registros mensais; manifesto consolidado só é finalizado no fim do comando.
Dados e diagnósticos completos são locais, ignorados por `data/`; Git recebe
somente código, protocolo, configuração, testes e agregado compacto sem preços.

## Parser e observabilidade

Leitura streaming, sem ordenar, preencher, arredondar preços ou deduplicar.
`Decimal` valida bid/ask finitos positivos, ask >= bid e volume finito >= 0;
CSV conserva texto original dos preços. Ordem não decrescente é comparada ao
maior timestamp elegível já encontrado, mesmo se sua cotação era inválida.

Normalizado `ticks.csv`: timestamp UTC, timestamp EST original, bid, ask, volume,
`source_sequence` (linha original 1-based), flags. Timestamps simultâneos são
válidos e preservados, inclusive duplicata exata consecutiva; segundo registro
e seguintes recebem flag e cópia na quarentena. Não alegar prioridade executável
entre ticks com mesmo timestamp. Duplicata aqui é diagnóstico, não correção.

`quarantine.jsonl` preserva timestamp UTC/EST, sequência, motivos, flags e linha
original para cotações inválidas de desenvolvimento. Minuto com inválido continua
incerto mesmo se possui ticks válidos. Consumidores futuros precisam ler esta
quarentena; normalizado sozinho não demonstra cobertura perfeita. Timestamp
inválido gera incerteza não localizada e exige tratamento conservador futuro.
Registros simultâneos copiados são explicitamente marcados como retidos no CSV;
não confundir quantidade de flags com quantidade de exclusões.

`audit.json`: contagens fonte/válidas/inválidas/reservadas, motivos, datas UTC e
suporte diário, primeiro/último, spread mínimo/máximo/médio em unidade de preço,
maior intervalo entre timestamps sem classificação. Não assumir que intervalo
corresponde a dado ausente ou fechamento; sem reamostragem ou calendário inferido.
Não produzir quantis aproximados nem inventar distribuição intraminuto.

## Validação e resultado

Fixtures sintéticas independentes verificam formulário/decoys, HTTP/redirect,
CRC/tamanhos/nomes, milissegundos/EST verão, passagem UTC para 2024 com preços
sentinela nunca lidos, inválidos, repetidos, ordenação, hashes e limite mensal.
Executar suíte completa, compileall e diff-check; revisão independente e CI no
SHA final antes da integração. Ledger canônico somente leitura antes/depois;
atividade simultânea de outras issues não será atribuída a esta aquisição.

Resultado descreve disponibilidade e qualidade da fonte. Isso não demonstra
capacidade preditiva, executabilidade histórica ou lucro. Nenhum fit consumido.
