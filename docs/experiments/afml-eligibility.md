# AFML — regra de elegibilidade antes do próximo treino

Esta regra fixa a comparação de candidatos do issue #2. Não constitui o protocolo
completo de diferenciação fracionária e não autoriza iniciar treino antes de
registrar grade de d, truncamento, histórico máximo, orçamento e seleção interna.

- Identidade da observação: (entry_index, side), vinculada ao hash dos candles e
  dos labels. Ordenação e máscaras devem ser aplicadas conjuntamente a X, y,
  timestamps e identidade.
- Preservar todos os rótulos conclusivos existentes e os critérios atuais.
  Auditoria de classes é descritiva: não escolher meses, direções, segmentos ou
  janelas por proporção de positivos ou desempenho.
- Fixar grade e regra de validade usando somente disponibilidade e continuidade
  do histórico anterior à entrada. Não preencher lacunas; reiniciar aquecimento.
- Para escolher entre ordens d dentro de um fold, usar interseção de candidatos
  válidos de todas as configurações da grade pré-registrada e do controle.
  Assim, a seleção interna não compara scores calculados em populações distintas.
- Ajustar controle e cada representação nas mesmas identidades de treino;
  avaliar nas mesmas identidades de validação interna. Recalcular unicidade
  nesse conjunto comum. Scalers e diagnósticos aprendidos usam somente treino.
- Para avaliação externa, aplicar a mesma regra pré-fixada de interseção,
  independente dos labels externos. Reajustar controle e modelo escolhido no
  mesmo treino elegível. Usar buffer comum derivado do maior histórico efetivo
  da grade, além do horizonte de informação dos labels.
- Registrar suporte e positivos antes/depois de cada exclusão; expurgo de treino
  e exclusão na fronteira direita da avaliação são etapas distintas.
- Preservar research_v1 e neural_v1. Seus números históricos são referência;
  controle no conjunto comum é o comparador primário do novo experimento.
- Julho–setembro são exploratórios. Outubro–dezembro podem aparecer nas
  contagens descritivas, mas ficam fora de seleção, ajuste e avaliação de modelos.

Limitação da interseção: uma janela extensa pode reduzir muito a amostra.
Registrar esse custo; não encurtar janela após examinar scores externos.
