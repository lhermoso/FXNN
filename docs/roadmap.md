# Plano de implementação

## Etapa 1 — concluída

- Download anual, normalização UTC e auditoria.
- Triple barrier com TP/SL/prazo fixos, scanner indexado e referência independente.
- Descarte de ambiguidades; negativos com stop antes do alvo.
- Seleção retrospectiva não sobreposta, explicitamente separada da modelagem.

## Etapa 2 — primeira implementação

- Features causais M1 com testes de invariância a mudanças futuras.
- Unicidade dos rótulos e splits temporais com expurgo.
- Baseline logístico, constante e seleção agrupada interna.
- Relatório reproduzível com hashes, configurações, versões e métricas externas.
- CI com dados sintéticos; sem downloads externos nos testes.

## Etapa 3 — estudos subsequentes

- Comparar árvore/ensemble, MDI, SFI e grupos aprendidos dentro do treino.
- Comparar diferenciação fracionária contra baseline simples.
- Ampliar histórico e obter bid/ask ou ticks, corrigir censura e calendário.
- Calibração, thresholds internos e simulação causal de posições/custos.
- Teste final em dados novos. Paper trading somente após esses controles.

Resultados ruins são resultados válidos: registrar antes de alterar configuração.
Não executar busca ilimitada até encontrar lucro.
