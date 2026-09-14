# Plano de implementação

## Etapa 1 — concluída

- Download anual, normalização UTC e auditoria.
- Triple barrier com TP/SL/prazo fixos, scanner indexado e referência independente.
- Descarte de ambiguidades; negativos com stop antes do alvo.
- Seleção retrospectiva não sobreposta, explicitamente separada da modelagem.

## Etapa 2 — concluída: primeira implementação

- Features causais M1 com testes de invariância a mudanças futuras.
- Unicidade dos rótulos e splits temporais com expurgo.
- Baseline logístico, constante e seleção agrupada interna.
- Relatório reproduzível com hashes, configurações, versões e métricas externas.
- CI com dados sintéticos; sem downloads externos nos testes.

Primeira execução: [research_v1](experiments/research-v1.md). Resultado preservado:
ganho sobre modelo constante não foi consistente entre os três meses externos.

## Etapa 3 — estudos subsequentes

- Auditoria pré-AFML concluída: [universo e ingestão](experiments/universe-v1.md),
  com [regra de candidatos comuns](experiments/afml-eligibility.md).
- [afml_v1 concluído](experiments/afml-v1.md): FFD contra controle comum,
  SFI e permutação internas; sem ganho consistente nos três meses.
- Comparar árvore/ensemble, MDI e grupos aprendidos dentro do treino.
- Ampliar histórico e obter bid/ask ou ticks, corrigir censura e calendário.
  HistData 2022–2025 disponível; [triagem](data-coverage.md) realizada, calendário
  e cobertura ainda pendentes. [Reserva temporal](experiments/multiyear-v1-protocol.md)
  fixada: desenvolvimento 2022–2023, confirmação histórica 2024.
- Calibração, thresholds internos e simulação causal de posições/custos.
- Teste final em dados novos. Paper trading somente após esses controles.

Resultados ruins são resultados válidos: registrar antes de alterar configuração.
Não executar busca ilimitada até encontrar lucro.

### Sequência #3: estado de dados

Pré-requisito neural/AFML integrado pelo PR #10 (`fd8ed59`). Etapa #4 possui
[contrato executável e limites](experiments/multiyear-v1-protocol.md),
[inventário verificável](experiments/multiyear-v1-sources.json) e auditoria de
suporte em `python -m fxnn.data_audit`. [Etapa #5, CUSUM](experiments/cusum-v1.md),
executada: parada pelo piso operacional registrado, zero ajustes; previsibilidade
inconclusiva. **CUSUM permanece como linha ativa em paralelo ao controle temporal**,
por decisão de Léo após merge do PR #12; ver [registro da decisão](decisions.md).
Próximo trabalho é definir novo protocolo de comparação, revisando justificativa
de suporte e desenho de avaliação comum antes de novos ajustes. O corte 1.000/100
não constitui evidência para descartar CUSUM. #6–#9 não executadas.
Bid/ask/calendário continuam bloqueios econômicos;
2024 só pode ser aberto após congelamento final na #9.

Continuação autorizada executada em [cusum_temporal_v2](experiments/cusum-temporal-v2.md):
24 ajustes, limiares separados comparados ao temporal e constante nas mesmas
identidades. Ganho descritivo contra logística temporal; contra constante,
resultado misto. Inferência inconclusiva. Ambas linhas permanecem ativas;
#6–#9 continuam não executadas, confirmação 2024 fechada.

Continuação neural autorizada: [mlp_cusum_v1](experiments/mlp-cusum-v1.md).
12 MLPs únicas e controles anteriores verificados; global 36/1.000. Efeito
descritivo CUSUM persistiu na MLP, sem ganho contra constante. Sem estabilização
da loss nas 20 épocas fixas; não extrapolar para outras inicializações ou redes
convergidas. Temporal e CUSUM seguem ativos, #6–#9 não executadas, 2024 fechado.
