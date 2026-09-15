# Sequential bagging v1 — resultado da etapa 8

Comparação exploratória uniforme/sequencial, sem seleção de seed ou alegação de lucro.
Ledger: **161 → 291/1.000**; 130 fits novos, teto 156.
Execução: 1632.9s; amostragem única: 1547.2s; traces de probabilidades: 37,969,035,264 bytes.

## Interpretação

A comparação registrada não mostrou melhoria consistente da amostragem sequencial nas duas seeds. No universo temporal, ambas receberam `mixed_or_unfavorable`: a média não ponderada entre folds de ΔBrier foi +0,032523 (seed 0) e +0,007591 (seed 1). Essa média inclui Q2 com apenas três eventos negativos, portanto não representa a média por observação e não deve ser interpretada como estimativa estável de generalização. Nas duas populações CUSUM, a conclusão conjunta é indisponível porque Q2 não tem observações conclusivas. Não se escolheu seed, população ou vencedora.


## Externos — todos modelos e seeds

Decisão disponível refere-se ao modelo e ao threshold operacional; com N=0 não existe avaliação conclusiva neste fold. Threshold indisponível não equivale a rejeitar todos os sinais.

| Fold | População | Modelo | N | Positivos | LL | Brier | Threshold | Decisão |
|---|---|---|---:|---:|---:|---:|---:|---|
| 2023Q2 | 0.0005 | full | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.0005 | sequential_0 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.0005 | sequential_1 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.0005 | uniform_0 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.0005 | uniform_1 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.0005 | weighted_constant | 0 | 0 | — | — | 0.500000 | disponível |
| 2023Q2 | 0.0005 | weighted_logistic | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.001 | full | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.001 | sequential_0 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.001 | sequential_1 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.001 | uniform_0 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.001 | uniform_1 | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | 0.001 | weighted_constant | 0 | 0 | — | — | 0.500000 | disponível |
| 2023Q2 | 0.001 | weighted_logistic | 0 | 0 | — | — | 0.300000 | disponível |
| 2023Q2 | temporal | full | 3 | 0 | 0.301980 | 0.067941 | 0.300000 | disponível |
| 2023Q2 | temporal | sequential_0 | 3 | 0 | 0.527892 | 0.168351 | 0.300000 | disponível |
| 2023Q2 | temporal | sequential_1 | 3 | 0 | 0.396805 | 0.107379 | 0.300000 | disponível |
| 2023Q2 | temporal | uniform_0 | 3 | 0 | 0.304171 | 0.069307 | 0.300000 | disponível |
| 2023Q2 | temporal | uniform_1 | 3 | 0 | 0.350326 | 0.088277 | 0.300000 | disponível |
| 2023Q2 | temporal | weighted_constant | 3 | 0 | 0.308795 | 0.070580 | 0.500000 | disponível |
| 2023Q2 | temporal | weighted_logistic | 3 | 0 | 0.231903 | 0.042852 | 0.300000 | disponível |
| 2023Q3 | 0.0005 | full | 2174 | 574 | 0.577076 | 0.194292 | — | empty_validation |
| 2023Q3 | 0.0005 | sequential_0 | 2174 | 574 | 0.581523 | 0.196192 | — | empty_validation |
| 2023Q3 | 0.0005 | sequential_1 | 2174 | 574 | 0.579843 | 0.195434 | — | empty_validation |
| 2023Q3 | 0.0005 | uniform_0 | 2174 | 574 | 0.580718 | 0.195901 | — | empty_validation |
| 2023Q3 | 0.0005 | uniform_1 | 2174 | 574 | 0.586116 | 0.198213 | — | empty_validation |
| 2023Q3 | 0.0005 | weighted_constant | 2174 | 574 | 0.577256 | 0.194328 | — | empty_validation |
| 2023Q3 | 0.0005 | weighted_logistic | 2174 | 574 | 0.573194 | 0.192746 | — | empty_validation |
| 2023Q3 | 0.001 | full | 714 | 192 | 0.584641 | 0.197588 | — | empty_validation |
| 2023Q3 | 0.001 | sequential_0 | 714 | 192 | 0.581491 | 0.196111 | — | empty_validation |
| 2023Q3 | 0.001 | sequential_1 | 714 | 192 | 0.594907 | 0.201121 | — | empty_validation |
| 2023Q3 | 0.001 | uniform_0 | 714 | 192 | 0.583855 | 0.197469 | — | empty_validation |
| 2023Q3 | 0.001 | uniform_1 | 714 | 192 | 0.587771 | 0.199031 | — | empty_validation |
| 2023Q3 | 0.001 | weighted_constant | 714 | 192 | 0.582350 | 0.196666 | — | empty_validation |
| 2023Q3 | 0.001 | weighted_logistic | 714 | 192 | 0.578962 | 0.195356 | — | empty_validation |
| 2023Q3 | temporal | full | 42201 | 11450 | 0.583955 | 0.197485 | — | no_validation_positives |
| 2023Q3 | temporal | sequential_0 | 42201 | 11450 | 0.589732 | 0.199979 | — | no_validation_positives |
| 2023Q3 | temporal | sequential_1 | 42201 | 11450 | 0.595144 | 0.201581 | — | no_validation_positives |
| 2023Q3 | temporal | uniform_0 | 42201 | 11450 | 0.587435 | 0.198813 | — | no_validation_positives |
| 2023Q3 | temporal | uniform_1 | 42201 | 11450 | 0.586396 | 0.198363 | — | no_validation_positives |
| 2023Q3 | temporal | weighted_constant | 42201 | 11450 | 0.584653 | 0.197739 | — | no_validation_positives |
| 2023Q3 | temporal | weighted_logistic | 42201 | 11450 | 0.581849 | 0.196631 | — | no_validation_positives |
| 2023Q4 | 0.0005 | full | 4078 | 1128 | 0.592826 | 0.201292 | 0.300000 | disponível |
| 2023Q4 | 0.0005 | sequential_0 | 4078 | 1128 | 0.604526 | 0.205196 | 0.300000 | disponível |
| 2023Q4 | 0.0005 | sequential_1 | 4078 | 1128 | 0.608967 | 0.206607 | 0.300000 | disponível |
| 2023Q4 | 0.0005 | uniform_0 | 4078 | 1128 | 0.607459 | 0.205605 | 0.300000 | disponível |
| 2023Q4 | 0.0005 | uniform_1 | 4078 | 1128 | 0.598096 | 0.203395 | 0.300000 | disponível |
| 2023Q4 | 0.0005 | weighted_constant | 4078 | 1128 | 0.590153 | 0.200265 | 0.500000 | disponível |
| 2023Q4 | 0.0005 | weighted_logistic | 4078 | 1128 | 0.596733 | 0.202507 | 0.300000 | disponível |
| 2023Q4 | 0.001 | full | 1335 | 372 | 0.594346 | 0.202029 | 0.300000 | disponível |
| 2023Q4 | 0.001 | sequential_0 | 1335 | 372 | 0.600373 | 0.204118 | 0.300000 | disponível |
| 2023Q4 | 0.001 | sequential_1 | 1335 | 372 | 0.606967 | 0.206365 | 0.300000 | disponível |
| 2023Q4 | 0.001 | uniform_0 | 1335 | 372 | 0.601705 | 0.204560 | 0.300000 | disponível |
| 2023Q4 | 0.001 | uniform_1 | 1335 | 372 | 0.597015 | 0.202879 | 0.300000 | disponível |
| 2023Q4 | 0.001 | weighted_constant | 1335 | 372 | 0.592605 | 0.201368 | 0.500000 | disponível |
| 2023Q4 | 0.001 | weighted_logistic | 1335 | 372 | 0.598904 | 0.203492 | 0.300000 | disponível |
| 2023Q4 | temporal | full | 76144 | 20386 | 0.582020 | 0.196449 | 0.300000 | disponível |
| 2023Q4 | temporal | sequential_0 | 76144 | 20386 | 0.588457 | 0.198634 | 0.300000 | disponível |
| 2023Q4 | temporal | sequential_1 | 76144 | 20386 | 0.593656 | 0.200768 | 0.300000 | disponível |
| 2023Q4 | temporal | uniform_0 | 76144 | 20386 | 0.594964 | 0.201273 | 0.300000 | disponível |
| 2023Q4 | temporal | uniform_1 | 76144 | 20386 | 0.593332 | 0.200315 | 0.300000 | disponível |
| 2023Q4 | temporal | weighted_constant | 76144 | 20386 | 0.581051 | 0.196075 | 0.500000 | disponível |
| 2023Q4 | temporal | weighted_logistic | 76144 | 20386 | 0.584482 | 0.197275 | 0.300000 | disponível |

## Conclusão registrada, sem eleição de vencedores

```json
{
  "both_seeds_required": true,
  "inference": "inconclusive_under_dependence_and_informed_design",
  "per_seed": {
    "0.0005": {
      "0": {
        "mean_brier_delta": null,
        "status": "technically_unavailable_or_empty_comparison"
      },
      "1": {
        "mean_brier_delta": null,
        "status": "technically_unavailable_or_empty_comparison"
      }
    },
    "0.001": {
      "0": {
        "mean_brier_delta": null,
        "status": "technically_unavailable_or_empty_comparison"
      },
      "1": {
        "mean_brier_delta": null,
        "status": "technically_unavailable_or_empty_comparison"
      }
    },
    "temporal": {
      "0": {
        "mean_brier_delta": 0.032523323968770265,
        "status": "mixed_or_unfavorable"
      },
      "1": {
        "mean_brier_delta": 0.007591320205388501,
        "status": "mixed_or_unfavorable"
      }
    }
  },
  "profit_claim": false,
  "seed_selection": false
}
```

## Cobertura e amostragem

Os CSVs preservam cada fold/fase/população/seed/membro solicitado, inclusive aliases e indisponibilidades. Deduplicação ocorre somente nas contagens e custos de fits/artefatos. Referências ponderadas da etapa 7 não consomem novos fits; controle full usa pesos unitários.
Unicidade raw é média por ocorrência sorteada, com duplicatas; não é peso normalizado nem tamanho amostral efetivo. Probabilidades e decisões têm máscaras distintas: threshold indisponível não equivale a rejeição.
Métricas individuais de membros não estão no JSON científico congelado: o agregador registra disponibilidade, suporte, contratos e diversidade, sem inventar scores ou ler predições individuais.
Monte Carlo sintético pré-registrado: Δunicidade sequencial−uniforme −0,0000310180, fração positiva 0,40 em 100 seeds. Esse resultado negativo pertence à fixture sintética, separado dos resultados reais.

## Diagnósticos de amostragem e diversidade

A unicidade raw média por ocorrência, em cada membro, variou de 0,799279 a 0,912946 no uniforme e de 0,864737 a 0,927818 no sequencial. São 108 slots por esquema, incluindo aliases, nos três folds, duas fases e três populações; os intervalos não são efeito pareado nem pesos normalizados. Duplicatas variaram de 0 a 15 por amostra uniforme e de 0 a 13 por amostra sequencial (512 draws). Esse diagnóstico descritivo real não modifica o Monte Carlo sintético pré-registrado negativo.

Diversidade entre membros: entre 108 pares solicitados por esquema, 84 possuem correlação e diferença absoluta média, e 24 estão indisponíveis. A correlação variou de −0,321899 a +0,586640 (uniforme) e de −0,535649 a +0,593951 (sequencial); a diferença absoluta média de probabilidades variou de 0,072179 a 0,170450 e de 0,061478 a 0,312387, respectivamente. Os intervalos cobrem todas as fases/populações, incluindo suportes muito pequenos, sem inferir vantagem a partir de diversidade.


## Integridade e limites

Replay científico: **verificado por evidência vinculada fornecida pelo root**.
Agregador confere terminal/hash e reconcilia slots; não substitui replay de modelos/sorteios/traces nem revisão/CI. Custos de fit incluem persistência; não há tempo CPU isolado registrado. Dependência temporal e desenho informado mantêm inferência inconclusiva. 2024/2025 não abertos.

[Métricas e diversidade](sequential-bagging-v1-metrics.csv) · [Thresholds](sequential-bagging-v1-thresholds.csv) · [Amostragem](sequential-bagging-v1-sampling.csv) · [Auditoria](sequential-bagging-v1-audit.json)

## Suplemento de validação após revisão — 15/09/2026

Revisão de aderência identificou duas lacunas no pré-registro implementado:
casos adversariais do oráculo numérico estavam incompletos; o benchmark original
não registrou hashes dos inputs nem todos os tempos por componente prometidos.
Os resultados científicos acima e o protocolo permanecem congelados. Este
suplemento é posterior à execução e ao replay, não evidência contemporânea
recuperada nem correção retroativa da cronologia.

Testes sintéticos adicionais usam Decimal com precisão 80 a partir dos inteiros
originais de duração e concorrência. Cobrem subtração positiva incorreta
(0,64 em lugar de 0,5, ainda dentro dos limites matemáticos), intervalos
sobrepostos de durações/concorrências diferentes, bordas de nós, padding e
4.101 candidatos que exigem fallback para a árvore. Erro real é comparado ao
limite informado e à tolerância registrada. Instrumentação observa contagens
reais de nós/níveis; uma mutação que ignora a proteção falha no oráculo.

[Benchmark suplementar](sequential-bagging-v1-benchmark-supplement.json),
executado às 20:47:54–20:49:11 UTC, registra hashes/shape/dtype dos inputs,
tempos separados, memória e limites de trabalho. Receita preservada: N=100.000,
K=512, PCG64(20260915), starts inteiros em [0,750000), seguidos de durações
em [1,4321); IDs arange(N); uniforms PCG64(0). Método instrumentado tem AST
idêntica ao original quando retiradas apenas as medições. Traces/sorteios
coincidem tanto com o benchmark original quanto com uma execução sintética
nova sem instrumentação. Nenhum fit ou dado real foi acessado.

Tempo instrumentado 39,7461 s; preparação de inputs 0,01592 s e de índice
0,06541 s. Nos 512 sorteios, construção da árvore 0,16004 s e consultas
36,52321 s; escrita/conversão do trace 0,74868 s, fsync 0,001256 s e hash
0,21432 s. Tempos são aninhados, com overhead de medição; não somar componentes
aos totais nem comparar como velocidade equivalente ao ensaio original.
Todas as 51,2 milhões de consultas prospectivas usaram árvore: máximo de
17 contribuições por candidato (limite 38) e 11 níveis (limite 19).
Peak RSS de 116.817.920 bytes cobre os dois passes sintéticos; trace de
409.600.000 bytes. Diagnóstico final tem contagens separadas no JSON.
