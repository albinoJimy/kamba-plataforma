# Revisão de segurança independente — re-teste

| Campo | Valor |
|---|---|
| Ticket | KAM-074 |
| Relatório | [`relatorio.md`](relatorio.md) |
| Revisor | o mesmo do relatório, pela referência (`R1`…) |
| **Estado** | **Formato, sem conteúdo.** Preparado sem o mundo real (lote 24); nenhum re-teste feito. |

O bloco exige que **cada achado crítico ou alto corrigido seja re-testado pelo revisor**, e que
este relatório fique anexado. Num crítico ou alto, um re-teste feito pela equipa que corrigiu não
conta: é o autor a avaliar o próprio produto.

## 1. Regras

- O re-teste corre em `staging`, sobre a imagem que contém a correcção, identificada por *digest*,
  e nunca em `prod`.
- Cada linha cita o `RI-NN` do relatório e o ticket `fix` que o corrigiu, e diz **quem
  re-testou**: o revisor (obrigatório para crítico e alto) ou a equipa (só médio e baixo,
  *proposta* — ver [`relatorio.md`](relatorio.md) §7, passo 7).
- O que é público segue o [`relatorio.md`](relatorio.md) §1, sem regra própria.

## 2. Re-testes

| Achado | Sev. | Ticket `fix` | Quem re-testou | *Digest* da imagem re-testada | Data | Resultado (`fechado` / `ainda reproduz` / `regressão noutra área`) | Nota |
|---|---|---|---|---|---|---|---|

Um resultado `ainda reproduz` devolve o achado a `aberto` no relatório e reabre o ticket `fix`
(ou abre outro, se o primeiro já fundiu). Uma `regressão noutra área` é um achado novo, com
`RI-NN` próprio.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | 2026-11-25 | Formato preparado sem o mundo real (KAM-074, lote 24). Nenhum re-teste. | Coordenação do lote 24 |
