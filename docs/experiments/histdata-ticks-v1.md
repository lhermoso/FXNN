# histdata_ticks_v1 — resultado da aquisição (#19)

**24/24 meses adquiridos e verificados; isso não demonstra cobertura suficiente
para simulação econômica.** Foram 60.631.004 registros de origem, 60.623.822
normalizados e 7.182 isolados por retrocesso de timestamp. Nenhum fit nesta issue.

Pré-registro código/configuração/protocolo: `971af1ef37fc5798182466380301618ea7c24025`,
anterior ao primeiro ZIP. Piloto janeiro/2022 seguido pelos demais 23 meses fixos.
Cada mês concluiu na primeira tentativa; nenhuma adaptação ao resultado.
Aquisição real confirmou formato de milissegundos pré-registrado e bid/ask
no mesmo registro. Timezone aplicado conforme FAQ: EST fixo UTC−5.

[Protocolo](histdata-ticks-v1-protocol.md) · [Evidência e hashes](histdata-ticks-v1-evidence.json).
Artefatos locais: `/Users/leohermoso/FXNN/data/histdata_ticks_v1/EURUSD`.
ZIPs, CSVs, formulários/HTTP, auditorias e quarentenas permanecem fora do Git.
Manifesto completo `manifest-002.json`; retomada `manifest-003.json` verificou
todos os hashes/tamanhos e CRCs, sem novas chamadas de download.

## Problemas preservados

- Outubro/2022: 4.624 linhas fora de ordem, cobrindo os 60 minutos UTC de
  2022-10-31 00:00 a 00:59.
- Outubro/2023: 2.558 linhas fora de ordem, cobrindo os 60 minutos UTC de
  2023-10-30 00:00 a 00:59.
- Dois registros com timestamp igual ao maior timestamp anterior foram mantidos
  e sinalizados. Nenhuma duplicata exata consecutiva detectada. Este diagnóstico
  não é uma busca global de duplicatas nem prova prioridade executável entre ties.
- Nenhuma cotação cruzada/não finita/não positiva ou volume negativo detectado
  nas linhas elegíveis; nenhum timestamp inválido. Não corrige os retrocessos.
- Zero registros reservados UTC≥2024 neste conjunto. Proteção de fronteira foi
  testada com fixture sentinela, sem preços de 2024/2025 em auditoria/modelagem.

Não corrigimos esses horários nem inferimos horário de verão a partir das datas.
120 minutos distintos contêm registros inválidos e **permanecem incertos mesmo
que outros ticks válidos coexistam**. Consumidor deve usar `quarantine.jsonl`
com timestamp UTC, sequência e motivos; usar apenas `ticks.csv` apagaria essa
incerteza. ZIP conserva todas as linhas originais. Sem preenchimento ou mistura
com o M1 histórico. Qualidade do feed precisa de protocolo próprio antes de #9.

## Cobertura descritiva

Mês é definido na origem EST; último trecho pode cair no mês UTC seguinte.
Dias UTC abaixo significam somente presença de alguma cotação, não dia completo.
Maior intervalo inclui finais de semana e possíveis faltas, sem classificação.
Não calculamos proporção de minutos de mercado cobertos, reconstrução M1 ou
comparação com o M1 histórico; estes números não demonstram continuidade útil
para janelas de features ou horizontes de labels.

| Mês EST | Linhas válidas | Inválidas | Dias UTC com quotes | Maior intervalo (h) |
|---|---:|---:|---:|---:|
| 202201 | 1,405,943 | 0 | 27 | 48.001 |
| 202202 | 1,738,863 | 0 | 25 | 48.001 |
| 202203 | 2,703,982 | 0 | 28 | 49.004 |
| 202204 | 2,072,552 | 0 | 25 | 48.069 |
| 202205 | 2,644,082 | 0 | 28 | 48.067 |
| 202206 | 2,535,438 | 0 | 27 | 48.075 |
| 202207 | 2,993,113 | 0 | 27 | 48.070 |
| 202208 | 3,539,349 | 0 | 28 | 48.067 |
| 202209 | 4,494,304 | 0 | 26 | 48.068 |
| 202210 | 4,885,692 | 4,624 | 27 | 48.002 |
| 202211 | 4,438,606 | 0 | 27 | 49.002 |
| 202212 | 3,493,032 | 0 | 26 | 48.019 |
| 202301 | 2,977,382 | 0 | 28 | 48.002 |
| 202302 | 2,401,122 | 0 | 25 | 49.001 |
| 202303 | 2,269,166 | 0 | 27 | 50.000 |
| 202304 | 1,303,430 | 0 | 26 | 69.067 |
| 202305 | 1,566,300 | 0 | 28 | 51.000 |
| 202306 | 1,413,820 | 0 | 25 | 51.000 |
| 202307 | 1,535,263 | 0 | 27 | 51.067 |
| 202308 | 2,237,719 | 0 | 28 | 48.065 |
| 202309 | 1,721,099 | 0 | 25 | 48.008 |
| 202310 | 2,210,189 | 2,558 | 28 | 48.074 |
| 202311 | 1,940,836 | 0 | 27 | 49.002 |
| 202312 | 2,102,540 | 0 | 25 | 49.022 |

`audit.json` local detalha suporte por dia, primeiro/último timestamp e spread
mínimo/máximo/médio em unidade de preço (pip EURUSD = 0,0001). Estatísticas de
spread são condicionadas às linhas válidas; não são custos totais de execução.
Não incluem comissão, slippage, swaps, liquidez ou garantias de preenchimento.

## Verificação e ledger

9 testes sintéticos novos; suíte completa: **157 testes passaram**.
`compileall` e `git diff --check` passaram. Revisão independente de aderência,
revisão final e CI do SHA final são gates de integração, registrados no PR.

O primeiro fingerprint local foi obtido após aquisição piloto, não antes.
Prefixo canônico de 103 fits/219 linhas coincide com hash prévio informado pelo
orquestrador: `3e9ed64b3307b346e0108e8710ceb8031d93645b4504065f5de6ef76f058a2d1`.
Depois da aquisição, prefixo permanece intacto; ledger possui 141 fits devido
à execução independente #6, hash `430161fa2aa56aa0a653f527f0b3467bee19b972b4a2591345d1a3e271f4e1d7`.
Script de aquisição não importa modelos/ledger e não escreve nele. Nenhum fit,
rótulo ou resultado econômico derivado destes ticks nesta issue.

Disponibilidade de bid/ask não resolve validade de execução, cobertura ou
previsibilidade. Próxima etapa exige pré-registro próprio de agregação, observabilidade,
features/labels e eventual treino; não transferir conclusões do M1 antigo.
