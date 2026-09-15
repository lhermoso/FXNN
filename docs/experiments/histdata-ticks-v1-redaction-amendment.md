# histdata_ticks_v1 — emenda de ocultação de timestamp inválido

2026-09-15, após aquisição e antes da integração do PR #20.
Correção de `AC-TEMPORAL-001` da revisão independente do commit `2c20bbf`.

## Falha e correção

Um separador ausente ou `;` no lugar de `,` fazia o primeiro campo conter
texto da linha inteira. O tratamento de timestamp inválido copiava esse texto
para `source_timestamp_est`, potencialmente expondo preços reservados enquanto
marcava `prices_redacted=true`.

Agora o ramo `invalid_timestamp_or_source_month` grava ambos os timestamps como
`null`, preservando sequência, motivo e sinalização de ocultação. Texto original
permanece somente no ZIP. Não tentar recuperar timestamp parcial da linha.
Timestamp válido de desenvolvimento conserva o comportamento anterior.

Nova fixture cobre separador `;`, separador ausente, timestamp ausente, primeiro
campo com preço sentinela e timestamp seguido por preço sentinela. Teste falhou
antes da correção e passou depois; verifica ausência de todos os preços sentinela
em CSV, quarentena, reservas e relatório, além de presença no ZIP original.

## Proveniência e impacto histórico

Pré-registro e aquisição permanecem associados ao commit
`971af1ef37fc5798182466380301618ea7c24025`. O campo `script_sha256` da
[evidência histórica](histdata-ticks-v1-evidence.json) identifica **o código de
aquisição original**, não o script corrigido do PR. Configuração, protocolo,
relatório e evidência originais não foram reescritos.

SHA-256 do script corrigido nesta emenda:
`6c159ff02de2cddc26581558994eee40a71484a812572fa3c6dc6b44cbb3b887`.

Verificação somente leitura dos 24 `audit.json` já congelados:

- Cada SHA-256 coincide com o registro na evidência histórica.
- Em cada mês, `invalid_rows == anomalies.out_of_order`; globalmente, ambos
  totalizam 7.182. No código histórico, cada retrocesso gera exatamente uma linha
  inválida; timestamp inválido gera linha inválida sem incrementar retrocessos.
  A igualdade exclui ocorrências do ramo de timestamp inválido nesta aquisição.
- `field_count` é zero em todos os meses. A chave de motivo
  `invalid_timestamp_or_source_month` não aparece; sua ausência isolada não
  comprovaria zero, pois o ramo histórico não incrementava esse contador.
  A comprovação vem da igualdade acima.

Assim, a borda corrigida não foi exercida nos arquivos reais desta aquisição.
Nenhum download, reauditoria de ticks, alteração de normalizados/quarentenas,
manifesto, ZIP ou fit foi necessário. Não estender essa conclusão a arquivos
futuros ou outras fontes.

Validação da correção: suíte completa com **158 testes**, `compileall` e
`git diff --check`; aderência, revisão final e CI precisam do novo SHA do PR.
