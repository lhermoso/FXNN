# cusum_v1 — parada por suporte interno (#5)

**Resultado inconclusivo sobre previsibilidade. Comparação encerrada antes de qualquer ajuste**, conforme [pré-registro](cusum-v1-protocol.md). CUSUM reduz densidade e concorrência, mas o universo resultante não sustenta os pisos registrados. Nenhum limiar foi escolhido; não houve probabilidades nem avaliação externa. Controle temporal preservado como referência, sem alegar vitória empírica sobre CUSUM.

Pré-registro: `f5cd246`. Código executado: `94150fa27008784307fdb8465ea210421dc08429`. Desenvolvimento 2022–2023; confirmação 2024 fechada e 2025 não utilizado. Arquivos originais e resultados anteriores preservados. [Relatório agregado completo](cusum-v1.json) contém hashes, versões, suporte, cobertura, censura e overlap de treino/validação/refit por fold.

## Suporte que determinou a parada

Pisos: ≥1.000 candidatos conclusivos com features válidas, ≥100 positivos e ≥100 negativos em cada conjunto interno. Folds e expurgo/buffer 4320+241 minutos preservados. Validação interna de 2023Q2 = jan–mar/2023; 2023Q3 = abr–jun; 2023Q4 = jul–set. Não confundir nome do fold com período interno.

| Fold | Universo interno | Linhas | Positivos | Negativos | Piso |
|---|---|---:|---:|---:|---|
| 2023Q2 | temporal | 57057 | 11989 | 45068 | passa |
| 2023Q2 | 0.0005 | 5228 | 1117 | 4111 | passa |
| 2023Q2 | 0.001 | 1874 | 402 | 1472 | passa |
| 2023Q2 | interseção | 1002 | 228 | 774 | passa |
| 2023Q3 | temporal | 12446 | 799 | 11647 | passa |
| 2023Q3 | 0.0005 | 624 | 40 | 584 | falha |
| 2023Q3 | 0.001 | 207 | 15 | 192 | falha |
| 2023Q3 | interseção | 84 | 7 | 77 | falha |
| 2023Q4 | temporal | 38577 | 6359 | 32218 | passa |
| 2023Q4 | 0.0005 | 2517 | 413 | 2104 | passa |
| 2023Q4 | 0.001 | 864 | 141 | 723 | falha |
| 2023Q4 | interseção | 393 | 67 | 326 | falha |

Todos os treinos/refits individuais passaram. 2023Q3 falhou nas duas amostragens e na interseção; 2023Q4 falhou em h=0,001 e na interseção. Preflight verificou todos os conjuntos internos antes de ajustar qualquer fold. Não executar somente 2023Q2, reduzir pisos ou procurar novos limiares.

| Fold | Interseção retida | Excluídos de h=0,0005 | Excluídos de h=0,001 |
|---|---:|---:|---:|
| 2023Q2 | 1002 | 4226 | 872 |
| 2023Q3 | 84 | 540 | 123 |
| 2023Q4 | 393 | 2124 | 471 |

## Redundância e cobertura

695.263 candles de desenvolvimento; 483.367 aberturas elegíveis por histórico; 2.983 resets por lacunas. Contagens abaixo não usam suporte externo para selecionar limiar.

| h | Eventos no fechamento | Sem próxima abertura contínua | Excluídos por aquecimento | Aberturas elegíveis | Densidade nas aberturas elegíveis |
|---|---:|---:|---:|---:|---:|
| 0.0005 | 52411 | 73 | 8447 | 43891 | 9.08% |
| 0.001 | 17853 | 18 | 2443 | 15392 | 3.18% |

Cada abertura autoriza long e short antes de conhecer labels. Diagnósticos abaixo são da validação interna de cada fold. Unicidade bruta calculada sobre intervalos reais dos labels conclusivos elegíveis, não sobre pesos normalizados (cuja média seria 1).

| Fold | Universo | Unicidade bruta média | Concorrência máx. | Concorrência média ativa | Censura dos candidatos amostrados | Cobertura retida / todos candidatos temporais |
|---|---|---:|---:|---:|---:|---:|
| 2023Q2 | temporal | 0.004974 | 1226 | 281.44 | 47.47% | 36.88% |
| 2023Q2 | 0.0005 | 0.054483 | 87 | 20.43 | 43.29% | 3.38% |
| 2023Q2 | 0.001 | 0.139691 | 29 | 7.70 | 41.21% | 1.21% |
| 2023Q3 | temporal | 0.010134 | 422 | 104.19 | 77.45% | 9.98% |
| 2023Q3 | 0.0005 | 0.186567 | 25 | 4.88 | 78.51% | 0.50% |
| 2023Q3 | 0.001 | 0.454913 | 10 | 2.14 | 78.17% | 0.17% |
| 2023Q4 | temporal | 0.005541 | 1112 | 224.85 | 63.73% | 23.56% |
| 2023Q4 | 0.0005 | 0.084950 | 61 | 12.73 | 57.69% | 1.54% |
| 2023Q4 | 0.001 | 0.210625 | 22 | 5.08 | 55.34% | 0.53% |

Redução de concorrência é observada; independência estatística não é demonstrada. Na validação abr–jun, censura continua próxima de 78% nos eventos, e a cobertura retida sobre todos candidatos temporais cai para 0,50%/0,17%. Esses diagnósticos de populações distintas não são comparação de scores preditivos.

## Métricas, orçamento e rastreabilidade

Log-loss, Brier, AP, ROC-AUC, thresholds 0,3/0,4/0,5 e pesos de treino: **não estimados**, pois a guarda impediu todo ajuste. Não há seleção, refit, resultados externos ou previsões reais para publicar. Caminho de modelos foi verificado com fixtures sintéticas: quatro ajustes internos na mesma interseção, três refits nas mesmas identidades externas; controle no universo temporal completo relatado separadamente.

Orçamento reservado no protocolo: no máximo 21 ajustes, incluindo constantes. Consumo anterior **0**, execução **0**, cumulativo **0/1.000**. Ledger persistente contém origem, execução iniciada e parada concluída; nenhuma tentativa de fit. Reexecução do identificador é rejeitada, inclusive com outro diretório de saída.

Comando executado uma vez: `.venv/bin/python -m fxnn.cusum_research --initialize-ledger`. Artefatos locais (SHA-256):

- `output/cusum_v1/report.json`: `096eb95e732e358edf0c2132385fe418c0b12f1054cbbf97ddeb4e072702d44d`.
- `output/cusum_v1/preflight.json`: `d772c29ff3c131d7aec332d2f8ea7d62fedd905730a3e19c222d82b180c1784a`.
- `/Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl`: `7d8788de40381c53b9ad7cc1612d278d87cdeed253ed64f17b346b054be02a49`.

Versões: Python 3.13.5, NumPy 2.4.6, scikit-learn 1.8.0.

Validação técnica: 82 testes sintéticos, compileall e git diff --check passaram antes da execução. Revisão independente e CI precisam aprovar o SHA final do PR separadamente. Nenhum merge automático.

Após revisão, evidência publicada passou a ser cópia **byte a byte** do relatório
original, acompanhada do [snapshot integral do ledger](cusum-v1-ledger.jsonl) e
[manifesto de hashes](cusum-v1-evidence.json). Exportação sem treino:

```bash
.venv/bin/python -m fxnn.cusum_evidence \
  --report output/cusum_v1/report.json \
  --ledger /Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl \
  --destination docs/experiments
```

O helper valida cadeia do ledger e vínculo ao hash do relatório, preserva o prefixo
histórico da execução e recusa substituir evidência divergente. Aceita caminhos
explícitos: auditoria independente pode usar os dois arquivos publicados em outra
máquina, sem dados de mercado. O runner científico mantém ledger canônico fixado
no pré-registro; portabilidade desse caminho é limitação operacional conhecida.
Permitir outro ledger vazio nesta execução permitiria contornar orçamento/histórico.
Não houve reexecução científica após revisão. Testes adicionais cobrem conclusão
em três folds, exportação reproduzível e hashes publicados; suíte final: 85 testes.

## Limites e decisão

Encerrar comparação registrada como **inconclusiva por suporte interno**. Não inferir ausência universal de sinal nem recomendar nova grade a partir destes resultados. Bid-only, ausência de custos/calendário confirmado, censura seletiva e labels sobrepostos impedem alegação de lucro. 2024 permanece reservado; #6–#9 não foram executadas.
