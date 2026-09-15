# Volatility barriers v1 — resultado da etapa 6

**Comparação inconclusiva.** A política causal diária ficou praticamente sem suporte em Q2/2023. Nenhuma contribuição preditiva estável ou lucro foi demonstrado. Q2 permanece no relatório, sem relaxar resets, diminuir o histórico ou procurar outra escala.

[Protocolo](volatility-barriers-v1-protocol.md) e código congelados em `55b9da02f69c26fb41f994c1cf39fde4f245e046` antes de labels/fits. Somente 2022–2023; 2024 e 2025 não consumidos.

## Universo e observabilidade

695.263 candles brutos; 3.176 fora do calendário semanal; 692.087 aberturas observadas, dois lados por abertura. As duas tarefas compartilham elegibilidade causal, mas retenção conclusiva depende de cada label.

| Tarefa | Candidatos | Elegíveis causais | Retidos | Positivos | Negativos | Censurados elegíveis | Ambíguos | Boundary |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed | 1384174 | 997364 | 945782 | 267205 | 678577 | 51534 | 47 | 1 |
| dynamic | 1384174 | 997364 | 969611 | 268472 | 701139 | 27006 | 747 | 0 |

386.810 candidatos por tarefa ficaram inelegíveis por histórico diário insuficiente. A redução de censura na tarefa dinâmica veio acompanhada de mais ambiguidades; não representa melhora classificatória nem econômica por si só.

Na série M1 observada, Q2 teve 383 gaps de pelo menos 15 minutos abertos: 319 de 60, 56 de 120, seis de 180, um de 63 e um de 1.264 minutos. Auditoria descritiva pós-execução dos timestamps congelados; não estabelece causa operacional das ausências. Resets frequentes impediram acumular lag diário e 100 retornos válidos. Só 16 aberturas de Q2 tiveram volatilidade válida; após conclusividade/expurgo, zero exemplos externos fixos e três dinâmicos temporais, todos negativos. Ambos CUSUM ficaram vazios nesse trimestre.

O mesmo desenho preservado produziu treinos idênticos em algumas bordas, permitindo reuso exato de contratos. Foram 38 fits novos, todos concluídos, abaixo do teto de 48; nenhuma tentativa foi apagada, repetida ou dispensada por orçamento.

## Externos: logística contra constante própria

LL/Brier menores são melhores. Comparar somente modelos dentro da mesma tarefa/população. `—` indica avaliação vazia. Três exemplos negativos em Q2 dinâmico não sustentam inferência de generalização.

| Tarefa | População | Externo | N | Positivos | LL logística | LL constante | ΔBrier |
|---|---|---|---:|---:|---:|---:|---:|
| fixed | temporal | 2023Q2 | 0 | 0 | — | — | — |
| fixed | 0.0005 | 2023Q2 | 0 | 0 | — | — | — |
| fixed | 0.001 | 2023Q2 | 0 | 0 | — | — | — |
| fixed | temporal | 2023Q3 | 78185 | 19331 | 0.559716 | 0.559961 | 0.000072 |
| fixed | 0.0005 | 2023Q3 | 4085 | 1069 | 0.570834 | 0.574877 | -0.001573 |
| fixed | 0.001 | 2023Q3 | 1367 | 369 | 0.578643 | 0.583194 | -0.001789 |
| fixed | temporal | 2023Q4 | 149126 | 45259 | 0.627120 | 0.618775 | 0.002955 |
| fixed | 0.0005 | 2023Q4 | 7935 | 2325 | 0.614403 | 0.607078 | 0.002684 |
| fixed | 0.001 | 2023Q4 | 2598 | 744 | 0.606411 | 0.599859 | 0.002468 |
| dynamic | temporal | 2023Q2 | 3 | 0 | 0.249896 | 0.313773 | -0.023636 |
| dynamic | 0.0005 | 2023Q2 | 0 | 0 | — | — | — |
| dynamic | 0.001 | 2023Q2 | 0 | 0 | — | — | — |
| dynamic | temporal | 2023Q3 | 85299 | 23745 | 0.590811 | 0.591623 | -0.000333 |
| dynamic | 0.0005 | 2023Q3 | 4393 | 1228 | 0.591095 | 0.592630 | -0.000635 |
| dynamic | 0.001 | 2023Q3 | 1441 | 405 | 0.591300 | 0.594003 | -0.001090 |
| dynamic | temporal | 2023Q4 | 153127 | 42858 | 0.596169 | 0.593153 | 0.001130 |
| dynamic | 0.0005 | 2023Q4 | 8192 | 2359 | 0.604054 | 0.600819 | 0.001247 |
| dynamic | 0.001 | 2023Q4 | 2669 | 760 | 0.600043 | 0.597474 | 0.001006 |

Q3 favoreceu logística descritivamente; Q4 a desfavoreceu nos seis pares. Cinco comparações completas ficaram inconclusivas por avaliação vazia em Q2; a dinâmica temporal teve padrão misto e suporte de Q2 insuficiente para conclusão substantiva. Nenhum par demonstra contribuição estável. Não usamos LL bruto para escolher tarefa.

## Diagnósticos, integridade e continuação

[CSV agregado](volatility-barriers-v1-support.csv) contém todos os treinos/avaliações por tarefa, fold, fase, população e regime, com suporte, outcomes, barreiras e durações médias. Regimes usam cortes do treino, timestamps únicos e incluem futuros inconclusivos; não entram em X nem seleção. Grupos vazios e ineligíveis permanecem visíveis.

O relatório integral local `output/volatility_dataset_v1/report.json` contém, além desses agregados, oito trimestres calendários e todas estatísticas pré-registradas: contagem, média, desvio padrão, mínimo, q05/q50/q95 e máximo por outcome/regime, duração aberta/corrida e barreiras em preço/pips. Seus 10,2 MB ficam fora do Git; hash e localização constam da [auditoria](volatility-barriers-v1-audit.json). Nenhum dado bruto, estado de modelo ou previsão individual foi publicado.

Rebuild em processo separado reproduziu **114 arrays e o relatório integral exatamente**. Replay dos modelos reproduziu **1.755.074 probabilidades**, métricas, sensibilidades por semana e conclusão, sem novos fits. Prefixo do ledger e fontes históricas preservados; 182 testes sintéticos, compileall e diff-check passaram no código pré-registrado. Revisões/CI do SHA final serão registradas no PR.

Ledger: **103 → 141/1.000**. SHA-256 final: `430161fa2aa56aa0a653f527f0b3467bee19b972b4a2591345d1a3e271f4e1d7`.

Decisão: encerrar #6 como comparação executada com limitação de suporte, sem promoção preditiva. Continuar #7 na tarefa dinâmica por política mecanística pré-registrada; se meta-labeling ficar tecnicamente indisponível, reportar isso, sem trocar para labels fixos. A aquisição bid/ask de #19 é pré-requisito independente de #9; qualquer mudança de fonte exige novo pré-registro de dados/labels/fits. Classificação condicionada à observabilidade continua distinta de lucro e exposição de carteira.
