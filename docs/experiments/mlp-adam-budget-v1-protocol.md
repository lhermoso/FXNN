# mlp_adam_budget_v1 — comparação exploratória de atualizações Adam

Continuação informada após merge #15 (8dd59cf). Resultados mlp_cusum_v1 conhecidos:
CUSUM melhorou MLP temporal, sem superar constante; nenhuma loss estabilizada.
Não é confirmação independente. Nenhuma execução #6–#9, 2024 fechado, nenhum 2025.

## Contrato e orçamento congelados antes dos ajustes

Incorporar integralmente contrato de dados, features, pesos, scaler, arquitetura,
parâmetros, métricas e falhas de [mlp_cusum_v1](mlp-cusum-v1-protocol.md).
Desenvolvimento 2022–2023, folds Q2/Q3/Q4, expurgo +4320 minutos/buffer 241,
TP50/SL20/<72h, 28 features causais, CUSUM h=0,0005 e h=0,001 separados,
long/short, entrada após fechamento, resets e aquecimento inalterados.
Nenhuma seleção de checkpoint, early stopping, busca ou extensão após resultados.

Nova condição: **9.580 atualizações Adam por ajuste**, maior orçamento temporal
anterior. Derivação sem scores, conferida no relatório histórico e novamente antes
de ajustes: N=378214/437752/451267/490276, batch=min(1024,N),
20×ceil(N/batch)=7400/8560/8820/9580. Quatro passados × três treinos × seed 0:
no máximo 12 tentativas incluindo falhas. Ledger canônico existente conferido
36/1000, máximo final 48/1000, saldo 952. Nunca inicializar novo ledger científico.
ID/diretório exclusivos: mlp_adam_budget_v1. Registrar tentativa antes de scaler/modelo.

## Sequência de otimização exata

Preservar MLP 28→16→1, ReLU/Adam, alpha=0,01, lr=0,001, seed inteiro 0,
shuffle=True, batch=min(1024,N), todos parâmetros do contrato anterior.
Usar a mesma instância em chamadas partial_fit sobre treino completo ponderado.
Cada chamada completa é uma época; cada minibatch executa uma atualização Adam.
Não trocar para chamadas por minibatch: isso alteraria shuffle/inicialização.
Ordem exatamente nativa sklearn 1.8.0: arange(N) a cada chamada, shuffle pelo
RandomState que _fit reinicializa com inteiro 0; primeira chamada consome RNG
na inicialização dos pesos/biases antes do shuffle. Último batch curto incluído,
sem padding, descarte ou renormalização local de pesos.

Interromper antes do backprop seguinte se contador Adam já for 9580. Sentinel
interno próprio, capturado exclusivamente pelo treinador, permite término no
meio de época sem atualização extra. Se orçamento termina na fronteira, não
iniciar próxima chamada. Estado Adam (t, momentos m/v) nunca reinicializado;
checar identidade do otimizador entre chamadas, t exato, contagem de backprops,
coeficientes/estado/loss finitos. Testar igualdade de prefixo contra implementação
original e referência independente por minibatches em fixtures sintéticas.
Fonte instalada de partial_fit/_fit_stochastic/_backprop/Adam consultada após
chub scikit-learn/package e numpy/package; hashes de implementação congelados.

Publicar trajetória de loss agregada por época completa, curva por batch em
artefato local com hash, contagem de chamadas, épocas completas, batches/linhas
da época parcial e exposições totais. Loss de época parcial relatada separadamente,
sem compará-la à época completa para diagnóstico. Diagnóstico pré-fixado:
abs(loss das duas últimas épocas completas) < 1e-4. Se menos de duas, indefinido.
Reportar finitude explicitamente; ausência de ConvergenceWarning não é evidência
de convergência (partial_fit não o emite por limite). Diagnóstico não muda parada.
Igualar atualizações não iguala exposições por candidato, convergência ou
regularização efetiva: L2 continua dividido pela soma de pesos de cada batch.

## Reutilização e falhas

Validar cadeia e prefixo publicado mlp-cusum-v1-ledger, hashes de relatórios e
previsões MLP/logística, vínculo de cada run ao ledger, versões estritas reais,
config/protocolo/fontes/módulos históricos. Regenerar dados de desenvolvimento;
validar contratos de TODOS treinos MLP (X/y/intervalos/identidades/pesos/features/
parâmetros/seed/versões), hashes do scaler e todas previsões por identidade,
timestamp, label e métricas; controles logísticos seguem verificador anterior.
Nenhum scaler adicional ajustado para validar: médias/escalas históricas ficam
vinculadas a contratos verificados e serão comparadas aos novos ajustes equivalentes.
Divergência encerra antes dos fits; sem substituição silenciosa de controles.
Refit pode ser próximo interno apenas com contrato integral idêntico; incluir
orçamento e hashes da implementação no contrato novo. Cache inclui falhas.

Treino vazio, uma classe, X/intervalos/pesos inválidos: indisponível técnico,
zero fits. Falha numérica/aviso consome tentativa, sem retry, continuar outros IDs.
Integridade ou interrupção encerra run. Probabilidade não finita torna run falho;
nunca substituir por constante. Métricas indefinidas preservam null/motivos do
protocolo anterior: vazio, AP sem positivos, AUC sem duas classes, precisão sem
sinais e recall sem positivos. Nenhum piso amostral arbitrário.

## Comparações e interpretação

No temporal completo: nova MLP temporal, MLP temporal 20 épocas, logística e
constante temporal. Em cada limiar: novas MLPs eventos/temporal, antigas MLPs
20 épocas eventos/temporal, logísticas eventos/temporal e constante temporal.
Todos métodos de cada comparação usam identidades exatamente iguais. Sem
interseção obrigatória, ranking entre limiares ou seleção por externos.

Contrastes explícitos: orçamento (nova−antiga na mesma amostragem), amostragem
(eventos−temporal dentro de cada orçamento/arquitetura), arquitetura (cada MLP−
logística da mesma amostragem), cada modelo−constante. Ganho descritivo consistente
somente LL menor nos três externos e média dos deltas Brier ≤0; ausências técnicas
ou métricas indefinidas separadas. Internos Q3/Q4 repetem externos Q2/Q3.
Classes, LL, Brier, AP, AUC, thresholds 0,3/0,4/0,5, cobertura, censura, densidade,
aquecimento, concorrência e unicidade bruta em agregado. Sensibilidade pareada
por remoção de semana UTC, sem refit; faixas não são IC, overlap não é independência.

Inferência inconclusiva sob dependência/desenho informado. Melhorar outro modelo
sem superar constante não demonstra valor consistente das features. Uma seed não
estabelece robustez entre inicializações. Otimização limitada ou resultado negativo
não descartam CUSUM/redes. Classificação não demonstra lucro: bid-only, custos
ausentes, lacunas e censura preservados.

Protocolo commitado antes dos fits; código/testes também. Unittest completo,
compileall, diff --check, fixtures portáveis entre patches Python com verificação
estrita de versões para dados reais. Publicar agregado, hashes/snapshot ledger,
sem dados/previsões volumosos. Revisão independente gh-workflow-suite, CI executado
verde no SHA final, PR sem merge automático.
