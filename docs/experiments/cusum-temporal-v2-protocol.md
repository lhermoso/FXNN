# cusum_temporal_v2 — continuação exploratória pré-registrada

Revisão informada pela auditoria de cusum_v1, após conhecer seu suporte: não é
confirmação independente. Léo mantém temporal e CUSUM ativos. Os 624 candidatos
por lado/40 positivos de abr–jun/2023 e a interseção 84/7 já eram conhecidos.
Pisos 1.000/100 não tinham cálculo de poder; não são reutilizados nem substituídos
por outro piso inferencial. Histórico v1 permanece intacto.

## Contrato congelado

Desenvolvimento 2022–2023, fontes e hashes de multiyear_v1; 2024 fechado, nenhum
uso de 2025. Mesmos três folds Q2/Q3/Q4, treino expansivo, expurgo +4320 min,
buffer 241 min e avaliações com horizonte integral dentro do trimestre.
Reutilizar prepare/partition_indices, TP50/SL20/<72h, features completas,
Baseline (logística L2 C=1, max_iter=1000, seed=0, scaler ponderado), unicidade
somente entre intervalos do treino de cada ajuste. Nenhuma busca, seleção de
features, FFD, barreira dinâmica, calibração ou regra direcional. #6–#9 fechadas.

CUSUM h=0,0005 e 0,001 são variantes fixas separadas. Preservar cruzamento estrito,
reset do acumulador disparado, entrada na próxima abertura contínua após close,
long/short, reset por lacunas e aquecimento causal. Referência consultada:
[AFML snippet 2.4, p.39](https://mlfinpy.readthedocs.io/en/stable/_modules/mlfinpy/filters/filters.html).
Docs NumPy 2.4.6 e scikit-learn 1.8.0 obtidas via chub antes do código.

Em cada fold ajustar internamente quatro modelos: temporal em todos candidatos
conclusivos elegíveis, constante com prior ponderado do mesmo treino temporal,
e logística em cada limiar. Repetir quatro ajustes no refit anterior ao externo.
Cada limiar avalia os três métodos nas mesmas identidades (entry_index, side)
do seu próprio universo. Nenhuma interseção entre limiares exigida. Controle e
constante são reutilizados: avaliá-los em outra população não é novo ajuste.
Publicar temporal/constante no universo temporal completo separadamente, interno
e externo. Não ordenar limiares entre populações nem selecionar vencedor, interna
ou externamente. Resultados internos são diagnósticos, sem alterar refits.

## Viabilidade técnica e métricas

Logística exige treino não vazio, ambas classes 0/1, X finito com colunas,
intervalos de duração positiva e pesos finitos positivos. Regularização permite
ajuste mesmo com menos linhas que features; isso não prova precisão inferencial.
Constante exige treino não vazio, labels binários, intervalos/pesos válidos;
aceita uma classe, prior 0 ou 1. Nunca substituir logística inviável por constante
silenciosamente. Partição inviável: registrar método/fold/fase e motivo, sem fit,
continuar demais partições fixas. ConvergenceWarning/falha numérica consome
uma tentativa, resultado técnico indisponível, sem retry; continuar outros IDs.
Falha de integridade de dados, ledger ou interrupção de processo encerra execução.

Métricas não ponderadas, condicionadas aos conclusivos, usando mesmas identidades:
log-loss (labels=[0,1], clipping da biblioteca por epsilon do dtype), Brier, AP,
ROC-AUC, precisão/recall em 0,3/0,4/0,5. Exigir probabilidades finitas em [0,1]
e comprimento idêntico a y. Vazio: métricas null com motivo; log-loss/Brier
aceitam uma classe; AP null sem positivos, ROC-AUC null sem ambas classes;
precisão null sem sinais, recall null sem positivos. Reportar contagens e motivos,
nunca NaN, zero inventado ou descartar silenciosamente partição.

Reportar classes, identidades distintas de abertura, cobertura, censura, densidade,
aquecimento, concorrência, unicidade bruta e pesos por partição. Candidatos por
lado e intervalos sobrepostos não são observações independentes; unicidade não
é tamanho amostral efetivo. Não calcular IC binomial/iid ou poder a partir de N.
Precisão: apresentar, por comparação pareada, deltas de log-loss/Brier e faixa
das médias ao remover uma semana UTC de entradas de cada vez (segunda-feira).
É sensibilidade descritiva, não IC nem teste: labels podem atravessar semanas,
regimes persistem e só há três trimestres externos. Menos de duas semanas:
sensibilidade null. Nenhum bootstrap, ajuste adicional ou decisão por essa faixa.
Poucos positivos e censura alta ampliam incerteza; não vetam métricas definidas.

## Conclusão congelada

Por limiar e por comparador (temporal e constante), ganho descritivo consistente
somente se log-loss estritamente menor nos três externos e média dos três deltas
Brier <=0. Se faltar ajuste: comparação tecnicamente indisponível; se faltar
log-loss/Brier por avaliação vazia: estimativa inconclusiva. Caso contrário,
reportar ganho consistente ou resultado preditivo misto/desfavorável. Mesmo
consistência não estabelece superioridade populacional: inferência permanece
inconclusiva sem precisão validada sob dependência, pouca diversidade de regimes
e auditoria informando desenho. Nenhuma categoria descarta CUSUM automaticamente.
Classificação não demonstra lucro: bid-only, custos, lacunas e censura permanecem.

## Orçamento e execução única

Ledger canônico /Users/leohermoso/FXNN/output/multiyear_v1/attempts.jsonl foi
conferido contra snapshot publicado: origem 0, cusum_v1 0, total 0/1.000.
Novo ID cusum_temporal_v2, diretório output/cusum_temporal_v2 exclusivo.
Máximo exato: 3 folds × 2 fases × 4 métodos = **24 tentativas** (18 logísticas,
6 constantes). Nenhum refit extra, seed extra, busca ou repetição. Se todos
viáveis, consumo será 24/1.000, saldo 976. Cada tentativa registrada antes do
scaler/fit/prior; falhas contam. Inviabilidades pré-fit consomem zero, com motivo
no relatório. Ledger append-only, sem inicialização, preserva prefixo histórico.
Extensão explícita do ledger permite somente IDs distintos após falha concluída
neste novo run; fit pendente, ID repetido e rerun seguem bloqueados.

Protocolo deve estar commitado antes de qualquer ajuste real; código e testes
sintéticos também commitados antes da execução. Relatório agregado byte-exato,
snapshot do ledger, hashes do protocolo/código/insumos/previsões publicados;
previsões por identidade ficam locais. Revisão independente e CI no SHA final,
PR sem merge automático.
