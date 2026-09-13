# neural_v1 — resultado

MLP 28 → 32 → 16 → 1, ReLU/Adam, regularização L2, três seeds fixas.
[Protocolo pré-registrado](neural-v1-protocol.md), sem alterar arquitetura depois
de examinar métricas. Cada fold escolheu épocas na validação interna e refez
normalização/modelos no passado disponível. Média das três redes é resultado principal.

| Mês | Épocas | Log-loss constante | Log-loss logística | Log-loss rede | Sinais p≥0,3 | Precisão rede p≥0,3 |
|---|---:|---:|---:|---:|---:|---:|
| 2025-07 | 5 | 0.56480 | 0.57291 | 0.58791 | 2454 | 12.63% |
| 2025-08 | 10 | 0.53298 | 0.53973 | 0.54735 | 1893 | 27.63% |
| 2025-09 | 5 | 0.54777 | 0.53028 | 0.53766 | 421 | 34.20% |

**Rede perdeu para logística nos três meses.** Cada seed individual também perdeu
para logística em cada mês; o resultado não depende de uma única inicialização.
Em setembro, rede superou constante, mas continuou inferior à logística.
Log-loss menor é melhor. A logística reproduziu métricas e contagens do
research_v1 nos mesmos candidatos, verificadas numericamente.

Isso rejeita ganho deste MLP sob este protocolo; não demonstra que toda rede
neural falha em Forex. Não houve teste de LSTM, Transformer, novas features ou
outras arquiteturas. Meses externos já foram examinados anteriormente: resultados
são exploratórios. Outubro–dezembro continuam fora de ajuste e avaliação.

Precisão é por candidato sobreposto e condicionada a rótulo conclusivo. Sem
simulação causal de posições, custos ou tratamento operacional de censura, não
converter essas métricas em lucro. Limiares altos produziram pouquíssimos sinais;
não selecionar threshold pela aparente precisão de amostras pequenas.

39 testes passam, incluindo aprendizado de sinal não linear sintético,
reprodutibilidade e isolamento de labels externos da seleção de épocas/previsões.
[JSON completo](neural-v1.json) registra todas as seeds, métricas, hiperparâmetros,
versões e hashes. Previsões individuais ficam em output/neural_v1/predictions.csv,
fora do Git. Execução levou cerca de 34 segundos nesta máquina, CPU com threads
numéricas limitadas a uma; comando reproduzível no README.
