# universe_v1 — auditoria de ingestão

Auditoria sem treino. Todos os rótulos conclusivos salvos foram reconciliados
por identidade, outcome e horários de entrada/saída com o rotulador atual.
Contagens reconstruídas coincidem com summary.json original.

| Mês UTC | Candidatos | Censurados | Conclusivos | Positivos antes | Excluídos por histórico | Elegíveis | Positivos depois |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-01 | 63208 | 19767 | 43441 | 27.00% | 7424 | 36017 | 27.15% |
| 2025-02 | 57462 | 24262 | 33200 | 23.29% | 7878 | 25322 | 22.23% |
| 2025-03 | 60456 | 17264 | 43192 | 25.28% | 8091 | 35101 | 23.69% |
| 2025-04 | 63224 | 13347 | 49877 | 27.32% | 9181 | 40696 | 26.20% |
| 2025-05 | 63032 | 17119 | 45913 | 27.84% | 7896 | 38017 | 27.34% |
| 2025-06 | 60574 | 19844 | 40730 | 24.64% | 9334 | 31396 | 23.84% |
| 2025-07 | 66080 | 27743 | 38337 | 24.99% | 8621 | 29716 | 23.96% |
| 2025-08 | 60282 | 29938 | 30344 | 22.85% | 8359 | 21985 | 21.98% |
| 2025-09 | 63078 | 32314 | 30764 | 22.38% | 8725 | 22039 | 21.44% |
| 2025-10 | 65664 | 36196 | 29468 | 19.00% | 8014 | 21454 | 20.29% |
| 2025-11 | 57574 | 38665 | 18909 | 12.72% | 6415 | 12494 | 10.99% |
| 2025-12 | 63294 | 43358 | 19936 | 12.79% | 5956 | 13980 | 13.43% |

Neste arquivo: zero ambíguos, boundary e timeouts. Positivos = take_profit;
negativos = stop_loss. Percentuais usam denominador da respectiva etapa.
Cada candle gera dois candidatos. Censura é exclusão de label; aquecimento
é exclusão posterior entre conclusivos, sem dupla contagem.

| Mês externo | Elegíveis antes da fronteira | Excluídos por horizonte à direita | Avaliados | Positivos |
|---|---:|---:|---:|---:|
| 2025-07 | 29716 | 4871 | 24845 | 24.47% |
| 2025-08 | 21985 | 445 | 21540 | 22.21% |
| 2025-09 | 22039 | 1631 | 20408 | 23.15% |

Total: 424,111 conclusivos; 95,894 exclusões por histórico; 328,217 elegíveis antes dos splits.

Não foi detectado desalinhamento nos cenários sintéticos testados.
Testes cobrem ordenação, direções opostas, exclusões por aquecimento/lacunas,
hash/configuração, duplicatas, subconjuntos e inconsistências de label/tempo.
Isso não demonstra valor preditivo nem elimina viés de seleção por censura.

Mudança funcional na ingestão: direção inválida agora gera ValueError explícito.
Critérios de validade e arrays para dados válidos permanecem iguais.

[Regra prévia para comparação de candidatos](afml-eligibility.md).
Outubro–dezembro: somente contagens, sem modelagem.

Reprodução, escolhendo caminho novo para preservar resultados:

```bash
.venv/bin/python -m fxnn.audit --output output/universe_v1.json
```

[Contagens completas e hashes](universe-v1.json). Dados brutos permanecem fora do Git.
