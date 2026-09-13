# FXNN

- Leia `docs/methodology.md` antes de alterar pesquisa ou rótulos.
- Nunca usar seleção retrospectiva de vencedoras como universo de treino.
- Features somente com informação disponível antes da entrada. Campos de rótulo
  nunca entram em X. Novas features precisam de teste de causalidade.
- Transformações aprendidas e seleção ficam dentro do treino de cada fold.
- Sem random split em eventos financeiros sobrepostos.
- Nunca publicar dados brutos, credenciais ou resultados volumosos no Git.
- Rode `.venv/bin/python -m unittest discover -s tests -v` e `git diff --check`.
- CI usa fixtures sintéticas e não depende de downloads de mercado.
- Reporte resultados negativos e limitações; não confunda classificação com lucro.
