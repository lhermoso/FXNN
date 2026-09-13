# multiyear_v1 — fechamento exploratório de dados (#4)

Protocolo e código registrados no commit `f8af187` antes da primeira auditoria
real de labels 2022–2023. Nenhum ajuste de modelo: **0/1.000 fits**.
Confirmação histórica 2024 permanece fechada; 2025 não entrou nesta execução.

Comando: `.venv/bin/python -m fxnn.data_audit`. Saída local:
`output/multiyear_v1/data_audit.json`. SHA-256:

```text
023a49a239ab8225a8bc33c6c20df59524609b8d2933bba5c69b930c872048e9
```

Hash do contrato: `ad288bd306d53ae07faff867ffed78c1490df9d4fc7f9b137204594bdaf191c8`.
Versões: Python 3.13.5, NumPy 2.4.6.
Inspeção de integridade anterior ao protocolo é registrada no inventário;
contagens de labels abaixo foram abertas somente após o commit de pré-registro.

## Cobertura e suporte por mês UTC

Cada candidato representa um lado em uma abertura observada. Colunas de censura,
ambiguidade e conclusivos são mutuamente exclusivas; exclusão de histórico abaixo
é somente entre conclusivos. Ausências de candles permanecem no relatório de
lacunas; candidatos não existem onde não há abertura observada.

| Mês | Candidatos | Censura | Ambíguos | Conclusivos sem histórico | Retidos | Positivos retidos |
|---|---:|---:|---:|---:|---:|---:|
| 2022-01 | 60344 | 36617 | 0 | 8752 | 14975 | 2521 |
| 2022-02 | 57380 | 27577 | 0 | 8791 | 21012 | 4498 |
| 2022-03 | 65948 | 20654 | 0 | 9787 | 35507 | 9631 |
| 2022-04 | 60016 | 25441 | 0 | 9025 | 25550 | 5975 |
| 2022-05 | 63262 | 21012 | 0 | 10256 | 31994 | 7270 |
| 2022-06 | 63054 | 19254 | 0 | 9854 | 33946 | 8546 |
| 2022-07 | 60248 | 16782 | 0 | 10078 | 33388 | 8188 |
| 2022-08 | 66072 | 18237 | 0 | 9363 | 38472 | 10708 |
| 2022-09 | 62956 | 14543 | 0 | 8116 | 40297 | 10582 |
| 2022-10 | 60402 | 15597 | 0 | 10261 | 34544 | 8751 |
| 2022-11 | 63074 | 15494 | 0 | 11021 | 36559 | 9447 |
| 2022-12 | 62734 | 19107 | 0 | 9176 | 34451 | 7879 |
| 2023-01 | 63046 | 24014 | 0 | 9351 | 29681 | 5565 |
| 2023-02 | 51340 | 23052 | 0 | 7853 | 20435 | 4896 |
| 2023-03 | 46412 | 30338 | 0 | 8064 | 8010 | 1531 |
| 2023-04 | 39866 | 30347 | 0 | 5687 | 3832 | 294 |
| 2023-05 | 46588 | 35457 | 0 | 5981 | 5150 | 299 |
| 2023-06 | 44266 | 35589 | 0 | 4781 | 3896 | 206 |
| 2023-07 | 43612 | 32984 | 0 | 5275 | 5353 | 153 |
| 2023-08 | 65974 | 35146 | 0 | 8861 | 21967 | 4814 |
| 2023-09 | 59664 | 39128 | 0 | 7506 | 13030 | 1842 |
| 2023-10 | 63404 | 33084 | 0 | 9039 | 21281 | 4701 |
| 2023-11 | 63002 | 34461 | 47 | 8270 | 20224 | 4165 |
| 2023-12 | 57862 | 26796 | 0 | 6396 | 24670 | 7583 |

Totais: 1390526 candidatos; 630711 censurados; 47 ambíguos.
Conclusivos: 759768. Excluídos por histórico entre conclusivos: 201544.
Retidos: 558224 (130045 positivos / 428179 negativos).
Nenhum timeout ou caso boundary nesta execução. Contagens não são retornos.

## Partições após expurgo e buffer

| Fold | Partição | Linhas | Positivos | Negativos | Piso |
|---|---|---:|---:|---:|---|
| 2023Q2 | train | 378214 | 93309 | 284905 | passa |
| 2023Q2 | validation | 57057 | 11989 | 45068 | passa |
| 2023Q2 | refit | 437752 | 105985 | 331767 | passa |
| 2023Q2 | test | 12446 | 799 | 11647 | passa |
| 2023Q3 | train | 437752 | 105985 | 331767 | passa |
| 2023Q3 | validation | 12446 | 799 | 11647 | passa |
| 2023Q3 | refit | 451267 | 106787 | 344480 | passa |
| 2023Q3 | test | 38577 | 6359 | 32218 | passa |
| 2023Q4 | train | 451267 | 106787 | 344480 | passa |
| 2023Q4 | validation | 38577 | 6359 | 32218 | passa |
| 2023Q4 | refit | 490276 | 113146 | 377130 | passa |
| 2023Q4 | test | 65183 | 16449 | 48734 | passa |

Todas as partições passam nos pisos registrados. Isso não prova independência,
poder estatístico ou validade econômica. O baixo suporte positivo de 2023Q2
(799 em 12.446 externos) serve somente à interpretação. Não pode mudar folds,
pesos de classe, amostragem, limiares CUSUM ou pisos nas etapas #5–#9.
CUSUM pode reduzir suporte abaixo do piso; nesse caso abortar a comparação,
sem baixar piso ou buscar outro trimestre.

## Decisão e bloqueios

Fechamento da etapa #4: **apto apenas para experimentação preditiva condicionada**.
Política conservadora de lacunas tem fixtures e preserva labels anteriores.
Hashes ZIP/CSV foram reconciliados; triagem de lacunas foi reproduzida.
Confirmar sessões históricas e obter bid/ask multianual íntegro seguem bloqueios
explícitos da #9. Não converter esse fechamento exploratório em alegação econômica.

Próxima etapa: pré-registrar detalhes da #5 dentro do teto global; usar folds,
guarda de suporte e regra de parada existentes. Não executar os runners históricos
de 2025 com outro CSV supondo que o calendário seja automaticamente adaptado.

Validação local: 67 testes sintéticos, compileall e git diff --check passaram.
CI do SHA publicado deve passar separadamente; sucesso local não substitui CI.

Após a auditoria original, validação de entrada foi reforçada para comparar
manifestos ao inventário versionado e rejeitar alterações no orçamento registrado.
Nenhuma contagem, label, partição ou decisão experimental foi recalculada/alterada.
