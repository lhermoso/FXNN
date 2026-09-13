# cusum_v1 — pré-registro da #5

Registrado antes de calcular eventos/suporte CUSUM ou ajustar modelos reais.
Contrato: `configs/cusum_v1.json`, subordinado ao hash congelado de
`configs/multiyear_v1.json`. Novo diretório `output/cusum_v1`; nada histórico
é sobrescrito. Desenvolvimento exclusivamente 2022–2023, HistData bid,
mesmas fontes/hashes da #4. Confirmação 2024 fechada; 2025 não entra.

## Filtro e identidades

Grade em ordem: **0,0005; 0,001**, unidades de log-retorno. Valores fixos,
sem estimação por volatilidade ou dados anuais. Para cada candle fechado,
`r = log(close[t]) - log(close[t-1])`, atualizar
`S+ = max(0, S+ + r)` e `S- = min(0, S- + r)`.
Disparar se `S- < -h`, senão se `S+ > h`; zerar apenas acumulador disparado.
Igualdade não dispara; sem epsilon no cruzamento, no máximo um evento/candle.
Segue código do [snippet 2.4 AFML](https://mlfinpy.readthedocs.io/en/stable/_modules/mlfinpy/filters/filters.html),
cuja desigualdade estrita difere do texto ≥ da documentação. Referência e
documentação NumPy/scikit-learn consultadas via chub antes da implementação.

Evento no fechamento t só autoriza abertura t+1 se timestamp for exatamente
60 segundos posterior ao timestamp de abertura t. Nunca entra no candle t.
Sem próxima abertura contínua, descartar evento; nunca transportar à reabertura.
Toda lacuna reinicia ambos acumuladores e histórico de 241 minutos. Primeiro
close após lacuna apenas inicializa preço anterior; nenhum retorno atravessa
lacuna. Filtro acumula durante aquecimento, mas só entradas com 241 candles
anteriores contínuos e features finitas são elegíveis. Aquecimento não acumula
eventos pendentes. Manter long e short, identidade `(entry_index, side)`.
Sem filtro pelo sentido do evento ou pelo resultado futuro.

Labels TP50/SL20/<72h e features atuais completas, logística L2 C=1,
max_iter=1000, seed=0, scaler e pesos iguais a `research.Baseline`. Sem seleção
de famílias, FFD, calibração, balanceamento ou nova regra direcional.

## Comparação e parada

Preservar três folds 2023Q2/Q3/Q4, horizonte conservador +4320 minutos,
expurgo estrito e buffer 241, exatamente como contrato pai. Reutilizar
`protocol.partition_indices`, `require_training_support`, `data_audit` e
`temporal.uniqueness_weights`.

Antes de qualquer ajuste, verificar em todos os folds: treino, validação e
refit do controle temporal e de cada limiar; adicionalmente validação interna
na interseção das identidades elegíveis conclusivas dos dois limiares.
Cada conjunto exige ≥1.000 linhas e ≥100 de cada classe. Primeira insuficiência
encerra etapa inteira com **zero ajustes**, sem pular fold ou remover limiar.
Relatar contagens de todos os conjuntos internos verificados e custo da
interseção (retidos/excluídos por limiar). Suporte externo não é guarda e só
é relatado após previsões. Em parada, não produzir métricas externas.

Controle temporal usa todos candidatos conclusivos elegíveis do treino; cada
logística CUSUM usa candidatos do seu limiar no mesmo treino. Constante usa
prior ponderado do treino temporal. Os quatro modelos internos são avaliados
nas **mesmas identidades da interseção** e mesmas features válidas. Escolher
limiar por menor log-loss interna; empate absoluto ≤1e-12 favorece primeiro
limiar da grade. Comparar também controle/constante internamente; empate entre
métodos favorece constante, depois controle temporal, depois CUSUM na ordem.
Essa recomendação interna não cancela comparação externa diagnóstica.

Refit temporal, constante e CUSUM do limiar escolhido usam seus respectivos
passados expurgados. Todos avaliam **as mesmas identidades externas do limiar
selecionado internamente**. Relatar controle e constante no universo temporal
inteiro separadamente; não comparar scores entre populações distintas.
Guardar previsões locais com fold, identidade, y e probabilidades de todos
métodos. Log-loss, Brier, AP, ROC-AUC, thresholds 0,3/0,4/0,5 sem otimização.
Suporte externo insuficiente torna conclusão inconclusiva, sem mudar seleção.

Pesos de unicidade normalizados são recalculados exclusivamente nos intervalos
de cada treino/refit; nunca usar vizinhos externos. Unicidade **bruta** é média
de 1/concorrência ponderada por duração em `[entry_time,end_time)` real do label.
Relatar média/min/max bruta, concorrência máxima e média ponderada pelo tempo
ativo, pesos normalizados; densidade, cobertura, censura, classes, exclusão por
aquecimento e interseção por partição/fold. Auditoria inclui todas as entradas
observadas no denominador, inclusive resultados não conclusivos; não transforma
censura futura em elegibilidade ex ante.

## Ledger e orçamento

Inspeção dos diretórios de resultados das worktrees existentes e relatório
versionado `multiyear-v1-data.md`: #4 consumiu **0/1.000**; nenhum ledger ou
experimento #5–#9 existente encontrado. Auditoria #4 preservada na worktree
`/Users/leohermoso/FXNN-issue-4/output/multiyear_v1/data_audit.json`.
Experimentos históricos de 2025 pertencem a protocolos anteriores, fora desse
teto explicitamente definido para #5–#9.

Ledger canônico compartilhado: caminho em `configs/cusum_v1.json`. Inicializar
uma vez com origem/consumo prévio 0; se existir, validar e contar antes de operar.
Persistir registro de execução antes de carga/treino; impedir segunda execução
do mesmo identificador mesmo em outro output. Reservar ajuste com ID, etapa,
fold, parâmetros, seed e hashes antes de chamar fit; concluir com status,
resultado ou erro. Registro iniciado/interrompido/falho consome orçamento.
Append com lock, flush/fsync e cadeia SHA-256; arquivo corrompido falha fechado.
Não apagar tentativa ou repetir fit falho. Auditoria sem modelo custa zero.

Orçamento exato por fold elegível: 4 ajustes internos (temporal, constante,
dois CUSUM) + 3 refits (temporal, constante, CUSUM escolhido) = **7**.
Três folds = **21**, incluindo constantes estimadas; scaler faz parte do ajuste
do respectivo modelo. Sem seeds extras, retries, permutações ou grid adicional.
Checar espaço para 21 antes de iniciar. Falha numérica/interrupção encerra
execução, preservando ajuste iniciado e todos resultados parciais. Não retomar
para substituir resultado desfavorável. Fixtures sintéticas de software não
entram no ledger científico.

## Interpretação

Ganho classificatório consistente somente se CUSUM superar temporal em
log-loss nos três folds e não piorar Brier médio, com suporte externo adequado.
Resultado misto preserva controle; insuficiência encerra como inconclusivo.
Menor densidade/concorrência e maior unicidade não demonstram previsibilidade,
independência estatística ou lucro. Bid-only, censura seletiva, overlap,
calendário incompleto e ausência de custos continuam limitações. Sem #6–#9.
