# Experimento research_v1

Primeiro baseline, protocolo registrado antes da execução. Dados EUR/USD M1 2025,
TP 50 / SL 20 / prazo <72h. Modelo logístico com 28 features, pesos de unicidade
e seleção de famílias na validação interna. Sem busca de hiperparâmetros.

328.217 rótulos com histórico contínuo suficiente; 95.894 rótulos conclusivos
excluídos pelo aquecimento das features ou lacunas. Avaliações externas abaixo
contêm somente rótulos conclusivos cujo horizonte cabe no próprio mês.

| Mês externo | Candidatos | Log-loss constante | Log-loss completo | Log-loss selecionado | Sinais p≥0,3 | Precisão p≥0,3 |
|---|---:|---:|---:|---:|---:|---:|
| 2025-07 | 24,845 | 0.56480 | 0.57291 | 0.57240 | 1654 | 13.12% |
| 2025-08 | 21,540 | 0.53298 | 0.53973 | 0.53900 | 788 | 24.49% |
| 2025-09 | 20,408 | 0.54777 | 0.53028 | 0.52943 | 913 | 33.95% |

Log-loss menor é melhor. Modelo selecionado perdeu para constante em julho e
agosto e venceu em setembro. **Não há evidência consistente de ganho preditivo
nesse primeiro baseline.** Nenhum sinal atingiu thresholds 0,4 ou 0,5.

Precisão refere-se a candidatos sobrepostos, condicionados à disponibilidade de
rótulo conclusivo. Não representa operações executadas nem rentabilidade. Pesos
corrigem parte da redundância no treino; não tornam resultados independentes.
Outubro–dezembro não entraram em ajuste, seleção ou avaliação dos modelos.

Relatório [JSON completo](research-v1.json) preserva métricas, famílias escolhidas,
parâmetros, versões e hashes de código/dados. Previsões individuais permanecem em
`output/research_v1/predictions.csv`, fora do Git. Dependências exatas estão em
`requirements-lock.txt`. Reproduzir com comando do README em novo diretório.

Próxima pesquisa deve tratar disponibilidade/censura e ampliar regimes antes de
multiplicar features e modelos. Mudanças futuras exigem novo experimento,
preservando este resultado; não reutilizar meses externos como holdout intocado.
