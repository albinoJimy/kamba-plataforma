# Revisão de segurança independente — decisão

| Campo | Valor |
|---|---|
| Ticket | KAM-074 |
| Relatório | [`relatorio.md`](relatorio.md) |
| Re-teste | [`reteste.md`](reteste.md) |
| **Estado** | **Formato, sem conteúdo.** Preparado sem o mundo real (lote 24); nenhuma decisão tomada nem assinada. |

## 1. A decisão

Uma de três, e só uma. Assina o Responsável de Segurança; aprova o Responsável de Produto.

| Decisão | Quando se pode escolher |
|---|---|
| `pronto` | 0 achados críticos ou altos em `aberto` ou `corrigido — por re-testar`; os médios com plano, dono e data |
| `pronto com condições` | as mesmas condições de `pronto` sobre críticos e altos, com condições escritas abaixo — cada uma com dono e prazo |
| `não pronto` | qualquer outro caso |

**Nenhuma das três autoriza dados reais sozinha.** O KAM-074 não substitui o gate de go-live de
transferência (KAM-069 e KAM-105) nem o parecer jurídico (KAM-104), e o Piloto (KAM-109) depende
dos três.

| Campo | Valor |
|---|---|
| Decisão | — |
| Data | — |
| Relatório na versão | — |
| Re-teste na versão | — |
| Achados críticos ou altos abertos | — (tem de ser 0 para `pronto` e `pronto com condições`) |

## 2. Condições

| # | Condição | Dono | Prazo |
|---|---|---|---|

## 3. Risco aceite por escrito

Preenche-se **só** se a revisão foi feita por um engenheiro não-autor em vez de um revisor
independente, que é o único caso em que o bloco prevê risco aceite, com a assinatura dos dois
responsáveis. Aceitar um achado sem correcção não está previsto no bloco e não se decide aqui.

| Risco aceite | Porquê | Até quando | Responsável de Segurança | Responsável de Produto |
|---|---|---|---|---|

## 4. Fora do âmbito, por escrito

O bloco pede que os itens que dependem de terceiros fiquem explícitos como fora do âmbito da
revisão. A lista de partida está em [`escopo.md`](escopo.md) §5; repete-se aqui na versão
assinada, sem acrescentar nem tirar sem o dizer.

## 5. Fecho do acesso

| Campo | Valor |
|---|---|
| Acesso do revisor a `staging` revogado em | — |
| Registo da revogação | a entrada correspondente no registo de acessos (ver [`escopo.md`](escopo.md) §4) |
| Segredos de `staging` rodados depois da revisão (*proposta*) | — |
| Anexos verificados sem segredos nem dados pessoais | — (o que cada verificação cobre e não cobre está em [`relatorio.md`](relatorio.md) §1) |

## 6. Assinaturas

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança | — | — | — |
| Responsável de Produto | — | — | — |
| Revisor interno de Segurança (resposta aos achados) | — | — | — |
| Revisor interno de Arquitectura (resposta aos achados) | — | — | — |

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | 2026-11-25 | Formato preparado sem o mundo real (KAM-074, lote 24): as três decisões, condições, risco aceite, fora do âmbito, fecho do acesso e assinaturas. Nada decidido nem assinado. | Coordenação do lote 24 |
