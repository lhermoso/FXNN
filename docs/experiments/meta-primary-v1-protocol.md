# Pré-registro — meta_primary_v1

Etapa 7, registrada antes de projetar oportunidades reais ou ajustar modelos. Configuração executável: `configs/meta_primary_v1.json`. Desenvolvimento exclusivamente 2022–2023. Não abrir 2024 ou 2025 nesta etapa. Experimentos anteriores permanecem congelados. Continuação dinâmica é decisão metodológica anterior aos resultados desta etapa, sem escolha retrospectiva de tarefa ou população.

## Fonte e regra primária

Consumir somente fonte dinâmica 2,5v/v de `volatility_barriers_v1`, com hashes de manifest, relatório, observed, dataset e candidates vinculados na configuração. Verificar arquivos de código/configuração/protocolo da fonte e conclusão de sua execução no ledger. Não gerar novos rótulos, alterar volatilidade, selecionar lado por resultado ou carregar a configuração 7 num loader vinculado à etapa 6.

Na abertura de índice observado i, comparar os preços originais Decimal close[i−1] e close[i−61]. Maior: long; menor: short; igual: sem sinal. Exigir 61 candles anteriores observados no segmento atual; reset na própria abertura também invalida histórico. São 60 transições entre 61 endpoints, não 61 minutos corridos. Nenhuma informação da própria abertura ou futuro determina o sinal. A regra não é estimada; OOF de modelo primário não se aplica.

Juntar somente a direção proposta por identidade (índice observado, lado), preservando índice original da fonte. Duplicidade ou ausência de lado proposto invalida construção. Lado proposto censurado permanece censurado mesmo quando lado oposto ganha. Sem sinal mantém abertura no registro, com mapeamento de candidato indisponível.

Manter 28 features existentes, com orientação por direção conforme schema da fonte. Não acrescentar volatilidade, outcome, duração ou PnL a X. Verificar X/y projetados contra linhas correspondentes do dataset bilateral congelado. Nenhum transformador aprendido durante projeção.

## Universo, partições e ajustes

Temporal e CUSUM 0,0005/0,001 separados, sem interseção, ranking ou eliminação. Treino inclui todos os sinais primários causalmente elegíveis com rótulo conclusivo, inclusive perdas, sem condicionar à aceitação de um filtro anterior. y=1 para TP antes do prazo; y=0 para SL ou timeout observado. Não é rótulo de lucro líquido.

Mesmas três avaliações externas de Q2/Q3/Q4 de 2023 e fronteiras internas do protocolo multiyear. Expurgo usa horizonte completo de 4.320 minutos abertos, não saída realizada. Buffer adicional de 1.941 candles observados preservado. A regra primária menor não reduz buffer. Pesos por unicidade local usam intervalos de saída realizada em minutos abertos; `last_information_bar_end` é preservado separadamente para etapa 8.

Por população: constante ponderada própria e regressão logística L2 C=1 com todos parâmetros da etapa 6, seed 0. StandardScaler e pesos calculados exclusivamente no treino correspondente. Sem balanceamento de classes, arquitetura alternativa, calibração aprendida ou nova busca. Quatro passados únicos × três populações × dois modelos = no máximo 24 ajustes novos. Reutilizar apenas contratos completos idênticos, incluindo tarefa, identidades, arrays, intervalos, pesos, parâmetros, runtime e fontes.

Treino vazio: indisponível. Logística de classe única: indisponível, sem ajuste. Constante de classe única não vazia: permitida. Falha numérica/convergência após início consome ajuste e não pode repetir. Não aplicar piso arbitrário de suporte. Threads OMP/OPENBLAS/MKL/VECLIB iguais a 1 antes de iniciar Python.

## Thresholds e consequência conhecida de Q2

Cada modelo/população escolhe threshold exclusivamente na validação interna conclusiva. Grade fixa 0,3/0,4/0,5, aceitação p≥t. Maximizar F1 não ponderado = 2TP/(2TP+FP+FN); maior threshold vence empate exato. Relatar todos os thresholds. Validação vazia ou sem positivos: threshold indisponível. Com positivos e zero aceitações, F1=0 é definido; precisão pode ser indefinida.

Mapa: externo Q2 calibra em Q1; externo Q3 calibra em Q2; externo Q4 calibra em Q3. Fonte bilateral dinâmica Q2 contém somente três exemplos temporais, todos negativos, e zero CUSUM. Projeção unilateral não cria positivos: threshold de Q3 será indisponível. Não emprestar Q1, carregar threshold anterior, usar 0,5 por padrão, unir períodos ou selecionar usando Q3. Suporte unilateral de outros períodos ainda exige execução própria; não antecipar resultados.

Threshold indisponível não é rejeição. Probabilidades continuam exportadas quando modelo/features estão disponíveis; `acceptance_available=false`, `accepted=-1` mascarado e razão explícita. Contagens/metricas de aceitação agregadas ficam null quando filtro indisponível, nunca zero trades artificial. Primário sem filtro continua disponível.

## Replay de todas as oportunidades

Uma linha por abertura observada, incluindo ausência de sinal, histórico inválido e não-evento. Inferência operacional usa somente sinal primário, elegibilidade causal da fonte e máscara da população. Não usar retained, outcome, censura futura, saída realizada ou horizonte dentro do trimestre para decidir se pode prever. Construir inferência antes da junção diagnóstica de outcomes.

Exportar probabilidades também para oportunidades depois ambíguas, censuradas ou de fronteira; manter sinais próximos ao fim do trimestre. Máscara de métricas é separada: além de elegibilidade operacional, exige rótulo conclusivo e horizonte conservador dentro do período. Decisão de carregar posição ou rejeitar fim de janela pertence à etapa econômica, não esta.

Primário sozinho aceita todas oportunidades operacionalmente elegíveis; relatar decisões, sem probabilidade fictícia 1. Constante/logística compartilham mesmas identidades. Denominadores: todas aberturas, sinais, eventos, elegibilidade causal, probabilidade disponível, decisão disponível, aceitos/rejeitados; inconclusividade futura e razões separadas.

## Relatórios e critério

Por fold, fase e população: suporte completo, resultados/ausências, LL, Brier, AP, ROC-AUC, grade e F1, threshold selecionado e identidade da validação, cobertura operacional, resultados do primário sozinho e constante própria. Sensibilidade por exclusão de semana é descritiva, sem refit, não intervalo de confiança.

Ganho probabilístico descritivo consistente exige LL da logística menor que própria constante nos três externos e média da diferença de Brier ≤0. Período vazio não satisfaz critério. Caso contrário resultado misto/desfavorável ou comparação indisponível. Preservar Q2, resultados negativos, todas populações e thresholds. Não selecionar universo por externos nem confundir classificação com lucro. Dependência, seleção por conclusividade e desenho informado por pesquisa prévia limitam inferência.

## Ledger, persistência e verificação

Ledger canônico `output/multiyear_v1/attempts.jsonl` no projeto original. Prior 141, SHA256 `430161fa2aa56aa0a653f527f0b3467bee19b972b4a2591345d1a3e271f4e1d7`; teto global 1.000, após etapa no máximo 165. BoundStageLedger verifica count e bytes exatos sob mesmo flock da reserva; hash por os.pread do descritor bloqueado, sem reabrir caminho ou normalizar newlines. Experimento intermediário de zero fits também invalida reserva. Check antecipado é diagnóstico; bloqueio atômico é autoridade.

Registrar início antes de scaler/modelo; cache terminal em andamento impede aliases repetirem falha. Sucesso exige export NumPy sem pickle, replay numérico, JSON exclusivo e terminal succeeded no ledger. Erro de armazenamento/ledger aborta todos próximos ajustes; arquivos parciais preservados. Falha numérica independente só permite próximo contrato após terminal failed e relatório persistido. Registro iniciado sem terminal bloqueia pesquisa nova mesmo em processo diferente. Nunca reinicializar ledger nem repetir experimento em outro diretório.

Falha em threshold, oportunidade, fase ou relatório final também aborta. Handler tenta encerrar run em finally mesmo se failure.json falhar, preservando erro original e erros secundários. Não escrever segundo terminal após run já fechado. Relatório final vinculado por SHA ao run completed e snapshots antes/depois. Sem vínculo completo, não declarar pesquisa concluída.

CLI dataset constrói projeção em saída exclusiva; `--verify` repete somente projeção determinística a partir de fonte com hashes conferidos, sem relabeling. CLI modelos `--verify` reconstrói contratos de treino, probabilidades, seleção interna, decisões externas, masks, métricas, sensibilidades e conclusão sem qualquer fit ou alteração de ledger. Replay compara arrays/JSON exatos e hashes/modelos/terminal. Uma execução abortada não recebe verificação completa; arquivos individuais só podem ser auditados como parciais com ledger correspondente.

## Aceite técnico antes de execução real

Fixtures independentes de Decimal/equality/reset/futuro, identidade embaralhada/censura do lado selecionado, orientação contra fonte bilateral, cenário de oito oportunidades com censura/sem sinal/near-end/decisão indisponível, F1 manual/empates/mapa Q2→Q3, expurgo 1.941, reserva atômica com intervening runs 0/1 fit e bytes diferentes, falhas de persistência e replay sem fits. Toda suíte unittest, compileall e diff-check devem passar; revisão independente e CI real no SHA publicado para integração. Fixtures CI sintéticas, sem downloads de mercado. Código/config/protocolo commitados antes de qualquer projeção ou ajuste real.

## Referências e documentação técnica

AFML, capítulo 3, e [documentação mantida de meta-labeling](https://mlfinpy.readthedocs.io/en/stable/Labelling.html#meta-labeling)
orientam separação entre direção primária e filtro secundário. Aqui há adaptação
explícita: target é TP antes do prazo, não lucro líquido após custos.
Documentação NumPy 2.4.6 e scikit-learn 1.8.0 consultada via `chub search/get`
antes do código. Transformações usam somente treino; estados numéricos NPZ com
`allow_pickle=False` preservam inferência auditável sem desserializar estimadores.
