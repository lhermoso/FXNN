# session_models_v1 — resultado do retreino

**Nenhum modelo superou a constante consistentemente nos três externos.**
Recuperar cobertura não bastou para demonstrar previsibilidade estável nas
28 features atuais.

Pré-registro `eea8923`; código executado
`51b6f22afe3793456476ee6bcf291662c3ceb431`. Dataset session_dataset_v1 congelado;
desenvolvimento 2022–2023, sem confirmação 2024 ou execução de 2025. Todos os
controles foram recalculados no contrato de sessão.

**39 ajustes únicos, todos bem-sucedidos**: 4 constantes, 12 logísticas e 23
MLP. Máximo registrado 40; MLP20 e MLPbudget do maior treino temporal eram o
mesmo procedimento e compartilharam um ajuste. Fases com treino idêntico entre
folds também reutilizaram modelos. Ledger global: 48 → **87/1.000**, saldo 913.
Nenhum retry, fallback ou seleção após scores.

## Log-loss externa: menor é melhor

Comparações pareadas dentro de cada universo. Não comparar números entre
universos como ranking de estratégia. Constante usa probabilidade ponderada
aprendida no treino temporal, nunca prevalência do teste.

### Universo temporal

| Modelo | 2023Q2 | 2023Q3 | 2023Q4 |
|---|---:|---:|---:|
| Constante | 0.375010 | 0.540637 | 0.633109 |
| Logística temporal | 0.423741 | 0.536702 | 0.646194 |
| MLP20 temporal | 0.376258 | 0.573018 | 0.707680 |
| MLPbudget temporal | 0.373041 | 0.576783 | 0.707680 |

### Universo CUSUM h=0.0005

| Modelo | 2023Q2 | 2023Q3 | 2023Q4 |
|---|---:|---:|---:|
| Constante | 0.375308 | 0.555955 | 0.626155 |
| Logística temporal | 0.421167 | 0.553829 | 0.639893 |
| MLP20 temporal | 0.386014 | 0.596492 | 0.689817 |
| MLPbudget temporal | 0.383894 | 0.601785 | 0.689817 |
| Logística eventos | 0.392101 | 0.552789 | 0.639209 |
| MLP20 eventos | 0.377421 | 0.562693 | 0.657960 |
| MLPbudget eventos | 0.366935 | 0.592142 | 0.702906 |

### Universo CUSUM h=0.001

| Modelo | 2023Q2 | 2023Q3 | 2023Q4 |
|---|---:|---:|---:|
| Constante | 0.382102 | 0.562599 | 0.617549 |
| Logística temporal | 0.421411 | 0.562034 | 0.633341 |
| MLP20 temporal | 0.388480 | 0.604741 | 0.674728 |
| MLPbudget temporal | 0.386777 | 0.613433 | 0.674728 |
| Logística eventos | 0.397039 | 0.559782 | 0.625145 |
| MLP20 eventos | 0.389249 | 0.565672 | 0.636860 |
| MLPbudget eventos | 0.378773 | 0.612342 | 0.689960 |

## Interpretação

- Logística treinada em CUSUM melhora a logística temporal nos três externos,
  para ambos os limiares, dentro das mesmas entradas de avaliação. Ainda perde
  para constante em Q2/Q4; melhora em Q3. Ganho de amostragem descritivo, sem
  ganho estável sobre o controle sem features.
- MLP temporal com orçamento comum melhora em Q2, mas piora frente à constante
  em Q3/Q4. O ganho de log-loss em Q2 não veio acompanhado de Brier melhor.
- MLP de eventos com 18.100 atualizações melhora frente à versão de 20 épocas
  em Q2, mas piora em Q3/Q4, para ambos h. Aumentar atualizações não produziu
  ganho consistente.
- MLP20 de eventos h=0.0005 melhora a MLP20 temporal nos três externos. Isso
  também não supera a constante de forma consistente.
- Nenhuma comparação MLP versus logística apresentou ganho consistente nos
  três externos. CUSUM e redes continuam hipóteses de pesquisa; esta execução
  não prova ausência de qualquer sinal possível.

Consistência descritiva exigia LL menor nos três externos e média dos deltas
Brier <=0. Sensibilidade delete-one-entry-week é descritiva, não intervalo de
confiança. Todos os scores, thresholds e contrastes constam nas evidências.

## Suporte externo após expurgo

| Universo | Q2 linhas / positivos | Q3 linhas / positivos | Q4 linhas / positivos |
|---|---:|---:|---:|
| Temporal | 14.964 / 1.105 | 106.339 / 24.568 | 164.679 / 50.567 |
| CUSUM 0.0005 | 742 / 55 | 5.267 / 1.286 | 8.651 / 2.607 |
| CUSUM 0.001 | 236 / 19 | 1.733 / 433 | 2.834 / 834 |

Q2 permanece condicionado a forte censura. Candidatos sobrepostos não são
observações independentes. Internos Q3/Q4 repetem externos anteriores e não
constituem novas replicações. Inferência permanece inconclusiva.

## Otimização e contrato

Arquitetura fixa 28→16→1, seed 0, sem busca. 20 épocas contra 18.100 atualizações
exatas por modelo, valor derivado do maior suporte temporal antes dos scores.
Oito MLPbudget de eventos estabilizaram o diagnóstico das duas últimas perdas
completas; as demais 15 MLP únicas não. Estabilização não prova convergência e
não altera resultados de avaliação. Loss parcial não é época completa.

Unicidade calculada em minutos de mercado aberto, excluindo fechamento semanal
da duração; scaler ponderado aprende exclusivamente no treino. Lacunas curtas
abertas continuam contando tempo. Configuração e fontes sklearn fixadas.

## Artefatos e verificação

Local: `/Users/leohermoso/FXNN-trading-clock/output/session_models_v1/`.

- `models/*.npz` e `models/*.json`: 39 modelos/scalers com metadados e hashes,
  sem pickle.
- 18 arquivos `2023Q*_inner/refit_universo.npz`: identidades, labels e
  probabilidades por universo/fase.
- `report.json`: métricas completas, curvas de treino, diagnósticos e aliases.
- `verification.json`: reprodução integral de previsões e métricas.
- `ledger-before.jsonl` e `ledger-after.jsonl`: cadeia e prefixo histórico.

124 testes passaram; compileall e git diff --check passaram na finalização.
Verificação posterior confrontou identidades com dataset congelado, reabriu
cada modelo salvo e reproduziu exatamente **2.321.307 probabilidades** nos
18 arquivos, além de todas as métricas. Os 39 ajustes estão ligados ao ledger
e aos hashes dos artefatos. Dataset e manifesto permaneceram iguais.

Carregar pesos sem executar pickle:

```python
import numpy as np
from fxnn.session_models import predict_state

with np.load(model_path, allow_pickle=False) as state:
    probabilities = predict_state(state, X)
```

X deve respeitar a ordem original das 28 features causais. Esses modelos
pertencem aos folds históricos; não são um modelo escolhido para produção nem
um ajuste final em todo 2023. Sem evidência de lucro, custos/ask ausentes e
nenhuma liberação de 2024.

Hash SHA-256 do relatório completo:

`f3604c1a27fb8517d4ef24f74788e5994287039d87a46d7a49a4473cd66a507a`
