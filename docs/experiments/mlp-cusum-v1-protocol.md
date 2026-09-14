# mlp_cusum_v1 — exploração informada após PR #14

Pergunta: MLP pequena melhora logística e constante com features/candidatos iguais?
O efeito CUSUM persiste nessa arquitetura? Conhecemos resultados cusum_temporal_v2:
ambos limiares melhoraram logística temporal, mas perderam para constante Q2/Q4.
Não é confirmação independente. Temporal e eventos continuam linhas ativas.

## Contrato anterior preservado

Desenvolvimento 2022–2023 exclusivamente; confirmação 2024 fechada, nenhum 2025
ou #6–#9. Usar `prepare` e `partition_indices` inalterados: folds Q2/Q3/Q4,
expurgo estrito +4320 minutos, buffer 241, avaliação inteiramente no trimestre,
labels TP50/SL20/<72h, todas 28 features causais. CUSUM h=0,0005 e 0,001
separados, entrada após close em próxima abertura contínua, long/short, resets
por lacunas, aquecimento 241. Sem interseção entre limiares, sem ranking entre
populações, sem busca ou seleção de features/hiperparâmetros.

## MLP única congelada

scikit-learn 1.8.0, float64, CPU com threads BLAS/OpenMP=1. Arquitetura 28→16→1,
ReLU interna e sigmoid saída, entropia cruzada ponderada, Adam, alpha=0,01 L2,
learning_rate_init=0,001, batch_size=min(1024,N treino), shuffle=True somente
nos minibatches. Seed/random_state=0, inicialização Glorot uniforme da biblioteca
(pesos e biases no intervalo ±sqrt(6/(fan_in+fan_out))). Adam beta_1=0,9,
beta_2=0,999, epsilon=1e-8. Todos parâmetros completos em config versionada.
Scaler StandardScaler ponderado e unicidade normalizada exclusivamente nos
intervalos do treino de cada partição, idênticos ao controle logístico. Sem
balanceamento de classes, oversampling ou calibração. Alpha não é C: penalidades
não são numericamente equivalentes entre arquiteturas; na MLP L2 é dividido
pela soma dos pesos do minibatch, sem penalizar biases. Tamanho amostral afeta
número de atualizações por época e força efetiva da regularização.

Parar após exatamente 20 chamadas partial_fit (uma época cada) na mesma instância;
é uma tentativa de ajuste contínua, não 20 modelos ou 20 seeds. Sem early stopping,
sem conjunto de parada, sem consulta a validação interna/externa durante ajuste.
random_state inteiro preserva comportamento da biblioteca inclusive shuffles
entre partial_fit. Reportar loss_curve inteira, atualizações/épocas, diagnóstico
`abs(loss[-1]-loss[-2]) < 1e-4` de estabilização da loss de treino. Esse diagnóstico
não prova convergência e não muda parada: reportar não estabilizado separadamente,
reter previsões finitas do procedimento de épocas fixas. ConvergenceWarning ou
falha numérica torna tentativa indisponível, nunca fallback para constante.

Histórico neural_v1 inspecionado somente como implementação: usa (32,16), três
seeds e seleção de checkpoints interna. Não executar runner nem importar resultados
2025 como evidência. Docs scikit-learn/package e numpy/package obtidas por chub;
suporte real a partial_fit(sample_weight), regularização e inicialização conferidos
no código instalado e [API 1.8](https://scikit-learn.org/1.8/modules/generated/sklearn.neural_network.MLPClassifier.html).

## Comparações pareadas

Em cada fase interna/refit, no temporal completo: MLP temporal, logística temporal,
constante do treino temporal. Em cada limiar: MLP eventos, MLP temporal, logística
eventos, logística temporal e mesma constante, exatamente mesmas identidades
(entry_index, side), timestamps e labels. Comparações direcionadas:

- Arquitetura: MLP temporal − logística temporal; MLP eventos − logística eventos.
- Amostragem: MLP eventos − MLP temporal; logística eventos − logística temporal.
- Features: cada modelo − constante temporal.

Internos são diagnósticos, não selecionam nada. Internos Q3/Q4 repetem externos
Q2/Q3 e não são evidência adicional. Não ordenar limiares nem escolher vencedor.

## Viabilidade, precisão e conclusão

Treino exige não vazio, duas classes binárias, X finito, intervalos positivos,
pesos positivos finitos. Nenhum piso 1.000/100 ou outro veto inferencial.
Uma classe é condição técnica deste protocolo MLP, não afirmação de impossibilidade
matemática da biblioteca. Inviabilidade pré-fit consome zero; registrar por fase/
método. Falha durante tentativa consome um; registrar antes de scaler/modelo;
continuar outros IDs, jamais retry ou substituição silenciosa. Integridade inválida
ou interrupção encerra execução; não abrir outro run para refazer tentativa.

Métricas não ponderadas: suporte 0/1, log-loss, Brier, AP, ROC-AUC, thresholds
0,3/0,4/0,5. Reutilizar score de v2: vazio → null; AP null sem positivos, ROC-AUC
null sem ambas classes, precisão null sem sinais, recall null sem positivos.
Registrar motivos individuais. Publicar cobertura/censura/densidade/aquecimento,
aberturas distintas, concorrência/unicidade bruta por partição, pesos de treino.
Sensibilidade pareada delete-one-entry-week UTC para cada contraste (LL/Brier),
sem refits; faixas descritivas nunca IC, nem candidatos sobrepostos independentes.

Para cada contraste dentro de cada universo: ganho descritivo consistente somente
se LL menor nos três externos e média dos deltas Brier ≤0. Caso contrário resultado
negativo/misto. Falta de modelo → indisponibilidade técnica; métricas LL/Brier
indefinidas → estimativa inconclusiva. Estabilização de treino não altera regra,
mas limita interpretação de otimização. Melhorar logística sem superar constante
não estabelece valor consistente das features. Inferência permanece inconclusiva
sob dependência, poucos positivos, censura e desenho informado. Uma seed condiciona
resultado à inicialização; nenhuma robustez entre seeds. Nenhuma categoria descarta
CUSUM ou redes neurais. Bid-only, custos ausentes, lacunas e censura impedem lucro.

## Orçamento e reutilização verificável

Ledger canônico `/Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl`
verificado: 24/1.000; snapshot publicado v2 deve permanecer prefixo exato.
Novo ID mlp_cusum_v1 e output exclusivo. Máximo exato **12 ajustes MLP**:
quatro passados únicos (fronteiras jan/abr/jul/out 2023) × três treinos
(temporal, h=0,0005, h=0,001) × seed 0. Se todos viáveis: total 36, saldo 964.
Zero novos controles/constantes, zero refits extras, zero seleção ou seeds extras;
falhas incluídas nesse máximo. Sem aumentar orçamento após scores.

Reutilizar modelos MLP do refit Q2/Q3 como treino interno Q3/Q4 somente após
igualdade de hashes de identidades, X/y, intervalos, pesos, parâmetros/seed,
features e versões; scaler já ajustado no mesmo treino. Cache inclui falhas,
sem repetir tentativa desfavorável. Registrar alias de cada fase ao fit original.

Controles v2 locais em `/Users/leohermoso/FXNN-cusum-exploratory/output/cusum_temporal_v2`.
Antes dos fits verificar relatório byte-exato publicado, cadeia/ligação ao ledger,
hash predictions.csv, config/protocolo pais, versões, fontes e módulos que definem
dados, features, pesos, scaler/modelo e partições. Regenerar dados determinísticos
2022–2023 e validar identidades de TODOS treinos/avaliações, y/timestamps e métricas
das previsões antigas. Isso demonstra igualdade de contrato/transforms sem refazer
fit. Divergência encerra antes de novos ajustes; não ajustar controles por conveniência.
Congelar hashes na config. Dados originais e previsões antigas permanecem intactos.

Commits de protocolo e código/testes sintéticos antes de qualquer ajuste real.
Teste causalidade, pareamento, isolamento temporal, scaler/pesos de treino,
parada fixa sem split aleatório, suporte reduzido, falhas e cache. unittest completo,
compileall, diff --check. Publicar relatório agregado byte-exato, manifesto de
hashes e prefixo verificável do ledger; previsões locais fora do Git. Revisão
independente via gh-workflow-suite e CI executado no SHA final, PR sem merge.
