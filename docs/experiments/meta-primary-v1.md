# Resultado — meta_primary_v1

## Conclusão

Meta-filtro não demonstrou contribuição preditiva estável. Logística melhorou LL/Brier descritivamente em Q3 e piorou ambas em Q4, nas três populações. Em Q3, probabilidades existem, mas decisão do filtro está indisponível: validação interna Q2 não tem positivos. Não houve empréstimo de threshold nem exclusão de Q2. Inferência continua inconclusiva; nenhuma simulação de carteira ou evidência de lucro nesta etapa.

[Protocolo](meta-primary-v1-protocol.md), [auditoria/hashes](meta-primary-v1-audit.json), [métricas completas](meta-primary-v1-metrics.csv) e [grade de thresholds](meta-primary-v1-thresholds.csv). Código, configuração e protocolo foram commitados em `175d1757acfd1086e343d90ceda52f4064652cbe` antes da projeção real e de qualquer fit. Somente 2022–2023; 2024/2025 não consumidos.

## Universo e execução

Fonte dinâmica 2,5v/v congelada da etapa 6. Regra de continuação compara closes anteriores i−1 e i−61; seleciona somente seu lado, sem consultar vencedor futuro. Rótulos TP/SL/timeout originais preservados; nenhum relabeling.

| Registro | Contagem |
|---|---:|
| Aberturas observadas preservadas | 692.087 |
| Sinais primários | 643.870 |
| Histórico primário insuficiente | 44.457 |
| Sem movimento entre endpoints | 3.760 |
| Sinais causalmente elegíveis | 495.866 |
| Rótulos conclusivos selecionados | 482.341 |
| TP / positivos | 130.246 |
| SL | 351.292 |
| Timeout observado | 803 |
| Ambíguos elegíveis | 424 |
| Censurados elegíveis | 13.101 |

482.341 conclusivos incluem 352.095 negativos. Outros 148.004 sinais são causalmente inelegíveis. Ausência de sinal, inelegibilidade, ambiguidade e censura continuam no registro de oportunidades; não foram convertidas em perdas nem usadas como filtro retrospectivo de inferência.

36 solicitações de ajuste resultaram em 20 fits novos e 16 aliases de contratos exatamente iguais; todos fits concluídos com sucesso. Quatro ajustes do teto 24 não foram necessários por reutilização adicional de passados CUSUM sem novas observações conclusivas em Q2. Não houve retry científico. Ledger 141→161/1.000; fonte e prefixos anteriores preservados.

## Probabilidades externas

N é suporte conclusivo com horizonte completo dentro do trimestre, distinto do número de oportunidades que receberam previsão.

| Externo | População | N | LL constante | LL logística | Brier constante | Brier logística |
|---|---|---:|---:|---:|---:|---:|
| Q2 | temporal | 3 | 0,308795 | 0,231903 | 0,070580 | 0,042852 |
| Q2 | CUSUM 0,0005 | 0 | — | — | — | — |
| Q2 | CUSUM 0,001 | 0 | — | — | — | — |
| Q3 | temporal | 42.201 | 0,584653 | 0,581849 | 0,197739 | 0,196631 |
| Q3 | CUSUM 0,0005 | 2.174 | 0,577256 | 0,573194 | 0,194328 | 0,192746 |
| Q3 | CUSUM 0,001 | 714 | 0,582350 | 0,578962 | 0,196666 | 0,195356 |
| Q4 | temporal | 76.144 | 0,581051 | 0,584482 | 0,196075 | 0,197275 |
| Q4 | CUSUM 0,0005 | 4.078 | 0,590153 | 0,596733 | 0,200265 | 0,202507 |
| Q4 | CUSUM 0,001 | 1.335 | 0,592605 | 0,598904 | 0,201368 | 0,203492 |

Q2 temporal contém três negativos, insuficientes para interpretar melhoria como evidência estável. Média temporal das diferenças de Brier entre trimestres é −0,009212, dominada pela diferença nesses três casos de Q2; essa média dá peso igual aos trimestres e não substitui suporte/inferência. Critério pré-fixado exige menor LL em todos três externos e falhou por Q4. CUSUM tem comparação tripla indisponível por Q2 vazio. Não escolher população por esses scores.

## Aceitação e cobertura

Logísticas escolheram t=0,3 internamente para externos Q2/Q4. Constantes escolheram t=0,5 e rejeitaram todas oportunidades com decisão disponível nesses externos. Q3 não recebe threshold: `no_validation_positives` temporal e `empty_validation` CUSUM. Grade externa é diagnóstico separado; não seleciona threshold externo.

| Externo | População | Previsões logísticas disponíveis | Aceitas operacionalmente | Rejeitadas operacionalmente |
|---|---|---:|---:|---:|
| Q2 | temporal | 16 | 0 | 16 |
| Q2 | CUSUM 0,0005 | 0 | 0 | 0 |
| Q2 | CUSUM 0,001 | 0 | 0 | 0 |
| Q3 | temporal | 48.913 | indisponível | indisponível |
| Q3 | CUSUM 0,0005 | 2.609 | indisponível | indisponível |
| Q3 | CUSUM 0,001 | 857 | indisponível | indisponível |
| Q4 | temporal | 81.780 | 11.896 | 69.884 |
| Q4 | CUSUM 0,0005 | 4.409 | 351 | 4.058 |
| Q4 | CUSUM 0,001 | 1.443 | 88 | 1.355 |

Em Q3, indisponibilidade de decisão não significa rejeição ou zero operações. Primário sem filtro continua aceitando oportunidades causalmente elegíveis. Previsões também existem para futuras censuras/ambiguidades e horizonte cruzando fim de trimestre; máscara dessas métricas é separada.

Em Q4, no subconjunto conclusivo, precisão logística versus primário foi 28,48% versus 26,77% temporal; 28,19% versus 27,66% CUSUM 0,0005; 33,33% versus 27,87% CUSUM 0,001. Recalls do filtro foram apenas 16,05%, 8,42% e 7,80%; F1 caiu respectivamente de 0,4224/0,4333/0,4359 para 0,2053/0,1297/0,1264. São trocas entre cobertura e acertos, condicionadas a labels conclusivos. Não demonstram melhoria econômica nem permitem selecionar uma população.

## Verificação e integridade

- 212 testes sintéticos antes do pré-registro; compilação e diff-check passaram. Incluem mutação externa com estados ajustados/seleção interna idênticos, projeção com expurgo completo, fixtures de oportunidade e falhas de persistência.
- Projeção reconstruída: 41 arrays e relatório completos, 692.087 aberturas, zero fits.
- Replay em processo separado: arrays de oportunidades, probabilidades, thresholds, decisões, métricas, sensibilidades e conclusão exatos. 488.292 probabilidades finitas conferidas; contagem inclui repetições entre fases/modelos/populações, não amostras independentes. Zero fits, ledger inalterado.
- Reserva de orçamento confere bytes/count dentro do mesmo lock. Fits e outputs têm vínculo terminal no ledger; não aceitar arquivos órfãos como resultado válido.
- Relatório integral (~600 KB), dados, modelos e previsões permanecem locais; Git contém resumos, métricas agregadas e hashes. Artefatos em `output/meta_dataset_v1/` e `output/meta_primary_v1/` do worktree da etapa.

Ledger final SHA256: `9e861f81cc713f3b583ca4a82df2beebced78fac3a7868725bd862daaefbd6ec`.
Relatório integral SHA256: `bda526a764671dfbf314b40ab60abb585ef193341b6921ac646d5793551e3e1c`.

Etapa 8 recebe universo unilateral dinâmico por continuidade pré-definida, incluindo fracassos e rejeições. Não recebe licença para escolher seed/modelo/threshold pelos externos. Fonte bid-only, sobreposição, seleção por conclusividade, baixa observabilidade de Q2 e desenho informado continuam limitando interpretação. Validação econômica exige fonte bid/ask e política própria; 2024 segue reservado até pipeline completo congelado.
