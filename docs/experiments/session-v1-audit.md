# Auditoria de session_dataset_v1 e session_models_v1

14/09/2026. Worktree `/Users/leohermoso/FXNN-trading-clock`, branch
`codex/trading-clock-gap-policy`, HEAD inicial `d496120feaf03908e582a6fd89c5a6f7cb789ec8`.
Git inicialmente limpo neste worktree e no checkout original. Esta auditoria
trata da reconstrução de sessão, não do experimento anterior do PR #16.

**Não encontrei erro material de implementação que invalide os resultados
auditados. Não há evidência de previsibilidade estável nas configurações
testadas. O ganho descritivo CUSUM ainda não identifica sua causa.**

Nenhum novo ajuste de pesquisa; ledger canônico preservado em **87/1.000**,
SHA-256 `9b06ec50cfd9afda1e0bbc890c4125fc3a419c4dacb63177144c393b7ad40645`.
Sem preços/labels 2024, execução de 2025, etapas #6–#9 ou merge.

## Evidência efetivamente conferida

Código reproduzível: [scripts/audit_session_v1.py](../../scripts/audit_session_v1.py).
Saída agregada: [session-v1-audit-evidence.json](session-v1-audit-evidence.json).
O auditor não chama estimadores para treinar nem abre o ledger para escrita.

- Hashes de dataset, candidatos, manifesto, relatório, fontes normalizadas
  2022–2023, modelos e previsões confrontados com evidências congeladas.
- Cadeia do ledger e prefixo anterior conferidos; 39 modelos ligados aos
  registros de início/fim e respectivos contratos e hashes.
- Todas as 1.105.737 identidades, direções, classes, intervalos e máscaras
  confrontadas com candidatos, incluindo preservação dos excluídos.
- Todas as 28 features reconstruídas dos candles e comparadas exatamente;
  máscaras CUSUM reconstruídas integralmente. Em 12 entradas distribuídas pelo
  dataset, truncar futuro e substituir OHLC da própria entrada não alterou X[t].
- 129 rótulos amostrados, cobrindo todos os outcomes, comparados por outcome e
  instante final com oráculo escalar por minuto, sem árvore de barreiras nem
  cálculo vetorial de censura. Isso não é revalidação escalar de todos os labels.
- Partições persistidas recalculadas; arrays e identidades de cada solicitação
  de treino conferidos com contratos, inclusive aliases entre fases/folds.
- Pesos dos 12 conjuntos únicos de treino confrontados com implementação densa
  por minuto aberto, independente da integração por intervalos comprimidos.
  Médias/escalas exportadas recalculadas somente desses treinos, sem novo fit.
- 39 modelos salvos reabertos; **2.321.307 probabilidades reproduzidas exatamente**
  nos 18 arquivos, e todas as métricas recalculadas. Reprodução de inferência
  não equivale a repetir treinamento, nem prova validade estatística.

Diferença de proveniência menor: `d496120` removeu uma linha vazia ao final de
`fxnn/session_neural.py`, alterando seu hash frente a `51b6f22`. O arquivo do
commit executado corresponde ao hash registrado; AST atual é idêntica. Não há
mudança funcional nessa diferença. O auditor registra ambos os hashes, sem
reescrever evidências antigas nem exigir retreino.

## Contrato e implementação

| Área | Conclusão da auditoria | Limite relevante |
|---|---|---|
| Relógio | `weekly_fx_clock` usa America/New_York; prefixo acumula apenas minutos abertos. `deadlines` escolhe primeira fronteira que completa 4.320 minutos, inclusive fechamento de sexta. | Convenção semanal, sem feriados específicos de corretora. |
| Censura | 14 ausências permitem continuar; 15 encerram na fronteira após o 15º minuto ausente. Fim de arquivo encerra imediatamente; TP/SL anteriores sobrevivem. | Toques durante gaps curtos são desconhecidos, não demonstradamente inexistentes. |
| Barreiras | Abertura decide precedência quando já ultrapassou barreira; stop pode exceder 20 pips. Duplo toque intrabar é ambíguo. TP intrabar no último minuto é boundary; stop é negativo. | OHLC M1 não fornece ordem intrabar; contrato assume execução bid-only. |
| Features | Preços até t−1; contexto temporal e direção de t conhecidos. Warmup exige 241 observações; gap longo reinicia, fim de semana não. | Janela de 240 observações não é duração fixa. Retorno entre observações inclui deslocamento através do gap/fim de semana. |
| CUSUM | Mudança entre closes observados; evento habilita próxima abertura. Gap longo reinicia acumuladores e descarta sinal pendente. | Treino por eventos modifica população, suporte e pesos simultaneamente. |
| Expurgo | Horizonte conservador completo, não duração realizada. Treino termina antes do início do histórico de 241 observações na fronteira. Teste exclui prazos que alcançam fim do trimestre. | Últimos dias de cada trimestre ficam fora do alvo de avaliação. Internos repetidos não são replicações. |
| Pesos/scaler | Unicidade entre intervalos realizados do próprio treino, em minutos abertos; média dos pesos 1. Scaler ponderado local ao treino. | Pesos dependem da duração realizada: permitido no treino, mas muda distribuição-alvo frente à avaliação não ponderada. |
| Pareamento/cache | Mesmas identidades/y para modelos dentro de cada universo; contratos incluem X/y, intervalos, identidades, pesos e parâmetros. | Não comparar scores entre universos como ranking de estratégia. |
| Adam | Trainer mantém estado; testes comparam épocas e prefixo parcial ao algoritmo nativo. 20 épocas e 18.100 updates são paradas registradas, sem seleção externa. | Updates iguais não igualam exposições, diversidade ou convergência. Seed inteira repete permutação após primeira época. |

Não foi identificado uso de loader histórico de 72h corridas nesta execução.
Campos de resultado não entram em X; usar rótulos/durações passadas para pesos
de treino não é vazamento da avaliação. Já excluir censurados cria avaliação
condicionada a informação que só estará disponível depois da entrada.

## Diagnóstico priorizado

### 1. Censura e mudança de distribuição limitam a interpretação

| Externo | Censurados / todos os candidatos após corte de horizonte | Positivos / linhas utilizáveis | Constante aprendida no treino |
|---|---:|---:|---:|
| Q2 2023 | 74,84% | 7,38% | 25,65% |
| Q3 2023 | 27,24% | 23,10% | 23,74% |
| Q4 2023 | 4,39% | 30,71% | 22,84% |

Os denominadores das duas primeiras colunas são diferentes e estão explícitos.
As constantes são ponderadas por unicidade, não prevalências brutas do treino.

**Evidência:** cobertura e frequência de positivos mudam muito. Q2 permanece
gravemente incompleto. Q4 tem muito menos censura e ainda apresenta resultado
negativo frente à constante; portanto a dificuldade não está restrita a Q2.

**Hipótese aberta:** movimentos que chegam rápido ao SL podem sobreviver a gaps
que censuram trajetórias mais longas até TP. Isso poderia reduzir a prevalência
observada. Estes dados não identificam quanto da mudança vem de seleção por
censura, regime de mercado, ponderação ou combinação. Não recuperar labels
ausentes por imputação, nem excluir Q2 depois de olhar seus scores.

### 2. Ganho CUSUM em log-loss não é ganho estável de ordenação

| AUC logística, temporal → eventos, mesmas entradas | Q2 | Q3 | Q4 |
|---|---:|---:|---:|
| h=0.0005 | 0,3622 → 0,3301 | 0,5547 → 0,5619 | 0,4561 → 0,4473 |
| h=0.001 | 0,4101 → 0,3849 | 0,5490 → 0,5533 | 0,4498 → 0,4440 |

**Evidência:** logística de eventos melhora log-loss nos três externos contra
logística temporal, mas sua AUC piora em Q2/Q4. Ambas ficam abaixo de 0,5 nesses
dois externos. Em Q3 há ganho descritivo de ordenação e de log-loss.

**Inferência limitada:** mudanças no nível/dispersão das probabilidades podem
melhorar proper scores sem melhorar ranking. Isso é compatível com os números;
não prova que toda melhora seja calibração ou prevalência. Não inverter sinais
após observar AUC abaixo de 0,5. Uma recalibração monotônica preservaria esse
ranking e não resolveria sozinha sua instabilidade.

### 3. Controles válidos, mas insuficientes para atribuir causa ao CUSUM

A constante temporal compartilhada é controle legítimo e pré-registrado.
Entretanto, falta constante aprendida em cada treino CUSUM com seus próprios
pesos. Assim, ainda não se mediu diretamente valor das features acima do prior
daquela população de treino.

Outro confundidor concreto: no sklearn 1.8.0 instalado, `_logistic.py` usa
`l2_reg_strength = 1 / (C * sum(sample_weight))` para lbfgs. Como a soma dos
pesos é N, mesmo C=1 produz regularização mais forte em relação à loss média
nos treinos menores. Nos refits externos, CUSUM tem aproximadamente 10,8–11,5
vezes menos linhas em h=0.0005 e 30,6–32,8 em h=0.001. Não é bug nem violação do
protocolo; impede atribuir melhora exclusivamente à seleção de eventos.

Na MLP, gradiente L2 é dividido pela soma dos pesos do minibatch; manter alpha
e updates também não isola perfeitamente o efeito de amostragem.

### 4. Mais Adam não sustentou a hipótese de falta de otimização

**Evidência:** 18.100 updates não geraram melhoria externa consistente; houve
melhoras em Q2 e pioras em Q3/Q4. MLP temporal tem AUC aproximadamente 0,44 em
Q4. Loss estabilizada de duas épocas não demonstra ótimo nem generalização.

**Hipóteses abertas:** overfitting, instabilidade de regime, seed, ordem de
minibatches e representação inadequada continuam possíveis. Estes resultados
não distinguem suas contribuições. Repetir seeds/épocas buscando score melhor
não é próximo teste justificável por esta evidência.

## Próximo experimento recomendado — proposta, não executada

**Controles pareados para separar prior e regularização do ganho CUSUM**, ainda
em desenvolvimento 2022–2023. Não ampliar arquitetura nem buscar hiperparâmetros.
Antes de qualquer ajuste: registrar protocolo/config/código, testes e commits.

Desenho mínimo: manter dataset, partições, features, máscaras, pesos de cada
treino e todos os controles existentes. Para cada um dos quatro passados únicos
e cada h, acrescentar apenas:

1. Constante igual à média ponderada de y daquele treino CUSUM.
2. Logística CUSUM com `C_event = N_temporal / N_event`, fixado por suporte de
   treino antes dos scores. Com pesos de média 1, isso iguala `1/(C*N)` ao
   controle temporal C=1. Não é grade de busca nem C selecionado no externo.

São no máximo **16 ajustes novos**: 8 constantes e 8 logísticas; teto global
**103/1.000**, caso o protocolo seja adotado. Constantes também contam como fits.
Reutilizar os quatro passados e controles somente por igualdade verificada;
registrar tentativas antes de ajustar, sem retries para melhorar resultados.

Contrastes, sempre nas mesmas entradas de cada h:

- Logística CUSUM original versus sua nova constante: existe ganho acima do
  prior ponderado da própria população?
- Logística CUSUM com regularização equivalente versus original: quanto o
  resultado muda ao remover diferença de penalização relativa?
- Logística CUSUM com regularização equivalente versus temporal e versus
  constante correspondente: o ganho sobrevive aos dois controles?

LL/Brier continuam critérios primários; AUC/AP e média/dispersão das previsões
explicam mudanças de ranking versus nível. Conservar critério descritivo
original — LL menor nos três externos e média dos deltas Brier <=0 — e reportar
todos os trimestres e ambos h separadamente. Sensibilidade semanal é descritiva,
não p-valor/IC. Não selecionar h, thresholds ou C por resultados.

Se ganho desaparecer contra constante de eventos, explicação por prior ganha
força. Se desaparecer ao igualar penalização, regularização ganha força. Se
persistir contra ambos, com ranking favorável e estabilidade entre trimestres,
amostragem informativa permanece hipótese mais plausível, ainda sem isolamento
do efeito dos pesos ou confirmação independente. Resultado misto continua misto.

Esse experimento distingue mecanismos do ganho CUSUM melhor que outra MLP.
Não resolve ausência de preços em gaps, não separa integralmente censura de
regime e não converte externos já vistos em holdout novo. 2024 continua fechado.

## Validação e limites finais

Auditoria acrescentou testes de transição DST de março/novembro e invariância
de features/CUSUM ao OHLC da própria entrada e remoção do futuro. Nenhuma
alteração no código de produção, labels, configurações ou artefatos originais.
Suíte completa: **126 testes passaram**; `git diff --check` e compilação do
auditor passaram. Os ajustes sintéticos dos testes usam ledgers temporários,
sem consumir tentativas de pesquisa. Arquivos desta auditoria ficam no worktree
para revisão, sem commit ou merge nesta tarefa.

Recuperar cobertura ampliou o universo utilizável; não demonstrou sinal. A
ausência de ganho consistente rejeita a conclusão forte de sucesso destes
modelos, não a possibilidade universal de sinal. Custos, ask, execução e
dependência entre posições continuam impedindo qualquer alegação de lucro.
