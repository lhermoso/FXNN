# Correção de publicação após execução de desenvolvimento

## Cronologia e limite da correção

O pré-registro científico executado permanece
`ac0dc96e6c5b9027caa7ff35d3fa8ee4973ce20b`. Dados, dez ajustes e nove meses de
carteiras foram processados com esses bytes. A execução das carteiras levou
3424,91s e atingiu pico RSS1098465280bytes. Depois de publicar o manifest com
nove checkpoints completos, o CLI falhou ao gravar o agregado:
`TypeError: Object of type Fraction is not JSON serializable`.

`Account` mantém valores financeiros em `Fraction`. O consumidor do CLI
`atomic_json` não converte esses valores. O mesmo defeito afeta o JSON de stdout
nas fases de carteira e replay. Trata-se de falha de publicação após processamento;
não é resultado científico ausente, fit mal sucedido ou motivo para repetir ajustes.
A reserva permaneceu íntegra, não envenenada, não selada e `UNOPENED`.

A correção é posterior à observação dos resultados de desenvolvimento e será
registrada antes de publicar os agregados recuperados e antes de abrir2024.
Não se apresenta como código científico pré-registrado retroativamente.
Revisão independente de diagnóstico/impacto aprovou esta abordagem limitada;
implementação, replay, CI e revisão completa do release continuam obrigatórios.

## Representação exata e identidade

O novo operador `scripts/publish_economic_portfolios.py` delega cálculos e
verificação de carteiras exclusivamente ao `portfolio_segment` congelado.
Aplica depois o conversor **já pré-registrado** `economic_account.serializable`:
`Fraction(n,d)` vira `{"numerator":n,"denominator":d}`. O leitor congelado
`economic_report._exact` reconstrói a mesma fração. Não há conversão monetária
por float, arredondamento, mudança de cenário, seleção ou recálculo de modelos.

O operador rejeita chaves de dicionário não textuais e números não finitos.
Compara a avaliação completa do portfólio antes e depois do round-trip JSON.
Os testes comparam também relatórios, Markdown e CSV, inclusive valores como1/3,
`null`, todos cenários e trimestres. `replay_verified` permanece o indicador
original; resultados de run e replay não são byte-idênticos nesse metadado.

Todos caminhos científicos originais permanecem byte-idênticos ao pré-registro:
S, F, calendário, source/labels/features, barreiras, pesos, parâmetros, threshold,
capital, custos e políticas de incerteza não mudam. Essa preservação não depende
de esconder um arquivo da lista `science_paths`: o novo executável será publicado,
testado e revisado no SHA de release e explicitamente vinculado a R/P.

O recibo original de validação do release inclui `publication_adapter` com
`repository_relative_path="scripts/publish_economic_portfolios.py"` e seu
`artifact` (path absoluto, bytes, SHA-256). O congelador existente inclui o hash
desse recibo em `R.reports.receipt_validation` e no pacote P. Antes de qualquer
processamento **ou replay** confirmatório, o operador autentica P, S, R, recibos,
caminho canônico, hash do executável e o Git blob desse caminho em `R.sha`.
Não aceita recibo fornecido pelo operador nem HEAD posterior como substituto.
A revisão completa anterior à abertura deve verificar essa vinculação adicional;
o congelador original não interpreta o campo do novo publicador.

## Recuperação e durabilidade

O destino é o `aggregate-<fase>.json` do diretório canônico já registrado na
intenção de dados. Aliases são rejeitados. Um lock de publicação exclusivo
cobre comparação do destino, preservação de parcial e publicação atômica.
O arquivo `.pending` deixado pela falha é renomeado para um nome forense único,
com fsync do arquivo e diretório, antes de qualquer nova escrita no caminho
`.pending`. Na retomada, todos parciais forenses existentes recebem fsync de
arquivo e diretório antes de nova escrita ou retorno bem-sucedido, mesmo se o
agregado já existir. Erros de abertura/aquisição do lock também entram no
tratamento de falha observada. Nenhum checkpoint, modelo, trilha ou registro do ledger é apagado.

Destino existente só permite retomada com bytes idênticos, seguida de fsync do
arquivo e diretório. Destino divergente permanece intocado e envenena o supervisor;
erros observados de publicação também impedem progressão silenciosa.
Interrupções de processo mantêm recuperação pelo contrato idêntico. Replay não
publica agregado, não cria lock de publicação e não escreve arquivos de carteira
ou estado. Os replays científicos seguem dentro dos módulos congelados.

Não executar simultaneamente o publicador novo e os quatro comandos antigos
listados abaixo: o CLI original não usa o lock de publicação novo.

## Comandos operacionais de substituição

Substituir somente `development-portfolios`, `confirmation-portfolios`,
`replay-development` e `replay-confirmation` do CLI original:

```sh
.venv/bin/python scripts/publish_economic_portfolios.py development \
  --output output/economic_ticks_v1 \
  --preregistered-sha ac0dc96e6c5b9027caa7ff35d3fa8ee4973ce20b
.venv/bin/python scripts/publish_economic_portfolios.py development --replay \
  --output output/economic_ticks_v1 \
  --preregistered-sha ac0dc96e6c5b9027caa7ff35d3fa8ee4973ce20b
```

Depois de congelamento verificado e abertura autorizada pelo guard, usar
`confirmation` no lugar de `development`. O publicador não oferece comando de
fit, aquisição, abertura, freeze ou fechamento. Esses passos, e ambos comandos
`*-report`, continuam no CLI congelado. Seus consumidores de carteira normalizam
as frações internamente; a nova representação é compatível com as comparações
exatas de `release_freeze` e `complete`.

## Evidência executada e gates restantes

Esta correção não fecha #9, não abre2024 e não satisfaz por si só T1–T5.
A recuperação foi executada em79,554s no commit
`f5fb6d8fb9675270fab20825578bdb5ec1e9a16b`, após479 testes, revisão de
implementação aprovada e CI efetivo. Preservou bytes de ledger/estado/manifest,
modelos e probabilidades; parcial original permaneceu idêntico por hash.
Replay integral das12 carteiras/nove meses passou em3416,184s, sem novos fits,
com ledger, estado e manifest idênticos. Relatórios reconstruídos do replay
coincidiram em JSON, Markdown e CSV. Evidência no [relatório](economic-ticks-v1.md).
Revisão completa e CI do release que vinculará esses agregados continuam gates
anteriores ao congelamento. A confirmação continua obrigatória quando os testes
técnicos passarem, inclusive com desenvolvimento economicamente negativo.
