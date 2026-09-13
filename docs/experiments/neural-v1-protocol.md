# neural_v1 — protocolo antes do treino

Comparar MLP tabular com regressão logística completa e probabilidade constante.
Mesmos dados, 28 features, rótulos, pesos de unicidade e divisões de research_v1.
Sem seleção de features neste experimento: isolar mudança de família de modelo.

- Arquitetura fixa 28 → 32 → 16 → 1; ReLU nas camadas internas, sigmoid na saída.
- scikit-learn 1.8 MLPClassifier; Adam, learning_rate_init=0.001, alpha=0.01,
  batch_size=1024; early_stopping=False. CPU, sem novas dependências.
- Seeds 11, 29, 47 predefinidas. Média das probabilidades é resultado principal;
  relatar também cada seed, sem escolher vencedora pelo teste.
- Checkpoints de 5, 10 e 20 épocas. Escolher por menor log-loss médio das três
  seeds na validação interna; empate favorece menos épocas. Recomeçar modelos
  do zero e refazer scaler/pesos no passado disponível antes do mês externo.
- Shuffle somente dos minibatches dentro do treino, nunca para dividir dados.
- Julho/agosto/setembro externos; mês anterior interno; horizonte conservador
  de 72h mais buffer de 241 minutos. Outubro–dezembro continuam fora dos modelos.
- Métricas e thresholds 0.3/0.4/0.5 iguais ao baseline. Sem cálculo de lucro.
- Meses externos já examinados: comparação exploratória, não holdout novo.
- Sem repetir busca de arquitetura após olhar resultados. Preservar experimento.

Referência: [MLPClassifier 1.8](https://scikit-learn.org/1.8/modules/generated/sklearn.neural_network.MLPClassifier.html).
