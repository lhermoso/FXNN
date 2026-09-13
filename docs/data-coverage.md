# Cobertura EURUSD — triagem de 13/09/2026

Auditoria de timestamps, sem novos labels. Executar:

```bash
.venv/bin/python scripts/audit_gaps.py
```

Saída local `output/gap_triage_v1.json`, com hashes dos insumos e do script,
contagens mensais e decomposição de cada lacuna. Recusa sobrescrever saída.
Dados brutos e relatório detalhado permanecem fora do Git.

## Classificação conservadora

Minutos em quarentena são identificados pelos timestamps originais convertidos
de EST fixo para UTC. Dos demais, somente sábado 00:00 até domingo 20:00 UTC
recebe marcador **candidato a fechamento de fim de semana**. Essa janela estreita
é uma convenção de triagem, não calendário confirmado do provedor. Bordas de
sessão, feriados e outras ausências permanecem sem explicação; uma lacuna pode
conter minutos de várias categorias. Não classificar lacuna inteira como
fechamento só porque atravessa fim de semana.

| Ano | Minutos candidatos de fim de semana | Minutos em quarentena | Minutos não resolvidos pela triagem |
|---|---:|---:|---:|
| 2022 | 134.640 | 60 | 13.831 |
| 2023 | 134.640 | 60 | 64.057 |
| 2024 | 137.280 | 0 | 15.940 |
| 2025 | 137.280 | 60 | 14.854 |

Contagens cobrem somente lacunas internas entre primeiro e último candle;
não medem ausência nas bordas anuais. Um timestamp duplicado corresponde a um
minuto ausente após quarentena, embora duas linhas tenham sido isoladas.
Minutos não resolvidos não equivalem todos a falhas: incluem bordas de sessão
e feriados. Nenhuma dessas categorias altera censura do rotulador.

## 2023: evidência de falha de cobertura

Março–julho concentram 51.870 minutos não resolvidos pela triagem. Exemplo:
HistData passa de 03/04/2023 12:59 UTC diretamente para 16:00 UTC, lacuna de
180 minutos. Uma consulta independente à hora 14:00–14:59 UTC da Dukascopy
encontrou **14.457 ticks em todos os 60 minutos**, enquanto HistData tem zero
candles nessa hora. Essa hora tem evidência de ausência de cobertura HistData
com mercado ativo em outro feed, e não de fechamento geral do mercado.
Não extrapolar confirmação aos outros 120 minutos ou ao restante do ano.

Consulta inicial HTTP retornou 301. Seguindo redirecionamento com `curl -L`,
URL HTTPS retornou 200 e payload BI5 passou no decoder existente. Disponibilidade
do feed varia; um download bem-sucedido não demonstra cobertura anual.

Evidência local: `data/dukascopy/EURUSD_gap_audit/` contém BI5 e relatório
`probe_2023-04-03T14_follow_redirect.json`, com hashes e contagens. SHA-256 BI5:
`8f4fd0e4cdab2f12f1f765b64b1f572b6d825c55fd9683dc28001711d06f454e`.
Endpoint: <https://datafeed.dukascopy.com/datafeed/EURUSD/2023/03/03/14h_ticks.bi5>
(mês zero-based). Nenhum preço Dukascopy foi inserido na série HistData.
A tabela acima mantém a triagem original; evidência pontual explica 60 dos
64.057 minutos de 2023, restando 63.997 sem resolução individual.

## Pendências

- Obter calendário histórico aplicável à fonte, incluindo DST, feriados e
  bordas de sessão; só então promover candidatos a fechamentos confirmados.
- Confrontar demais lacunas suspeitas de 2023 com feed independente. Ausência
  em dois feeds, 404 ou arquivo vazio não prova fechamento.
- Fixar política de elegibilidade/censura antes da próxima modelagem. Dados
  bid/ask completos continuam necessários para validação econômica.

A [FAQ HistData](https://www.histdata.com/f-a-q/) confirma preços M1 baseados
em bid, timestamps EST sem DST e lacunas que podem refletir pausas normais.
Isso não fornece calendário histórico suficiente para resolver cada ausência.

## Decisão de fonte e alcance da #4

Inventário verificado em 13/09/2026:

| Fonte/formato | Disponibilidade verificada | Uso decidido |
|---|---|---|
| HistData Generic ASCII M1, EURUSD | ZIP/CSV 2022–2025 locais; hashes reconciliados | Desenvolvimento 2022–2023; confirmação histórica 2024 reservada |
| HistData Generic ASCII ticks | FAQ documenta bid e ask; cobertura local multianual não verificada | Alternativa futura, sem presumir disponibilidade dos anos |
| Dukascopy ticks | Download pontual em 2023 e arquivos parciais existentes | Confronto de integridade; não compor série de treino |

[FAQ HistData](https://www.histdata.com/f-a-q/) consultada nesta etapa: downloads
públicos gratuitos, M1 baseado em bid, ask no Generic ASCII tick, EST fixo sem DST.
Não há garantia/certificação de dados. Nenhuma licença de redistribuição foi
verificada: manter arquivos localmente, sem publicar dados brutos. Aquisição paga
não é necessária para este escopo e continua exigindo autorização específica.
[Exportador Dukascopy](https://www.dukascopy.com/swiss/english/marketwatch/historical/)
foi consultado; não comprova sozinho cobertura, licença de redistribuição ou
calendário histórico. Fonte econômica e custos seguem sem aprovação técnica.

[Manifesto compacto](experiments/multiyear-v1-sources.json) contém cobertura
observada, contagens mensais na timezone de origem e hashes SHA-256 dos ZIP/CSV.
Os quatro pares foram conferidos contra manifestos locais, sem calcular novos
labels da confirmação. Versões de código vêm do commit; dependências continuam
em `requirements-lock.txt`. Reprodução da aquisição existente:

```bash
.venv/bin/python scripts/download_histdata.py --year 2022
.venv/bin/python scripts/download_histdata.py --year 2023
.venv/bin/python scripts/download_histdata.py --year 2024
.venv/bin/python scripts/download_histdata.py --year 2025
```

Reaquisição pode retornar outra versão do provedor: comparar hashes e preservar
original antes de trocar insumos. Esses comandos não autorizam substituir
arquivos históricos já usados. A auditoria real usa somente arquivos existentes e rejeita divergência de
hash/linhas entre manifesto local e inventário versionado.

Política operacional escolhida: `censor_all_reset_all`, definida no
[protocolo](experiments/multiyear-v1-protocol.md). Classificação da lacuna serve
para diagnóstico; não altera execução do scanner. Calendário não resolvido e
bid/ask incompleto são bloqueios explícitos da #9, não impedimentos ocultos nem
suposta evidência econômica positiva. Confrontos adicionais não são necessários
para aplicar essa política conservadora à exploração.
