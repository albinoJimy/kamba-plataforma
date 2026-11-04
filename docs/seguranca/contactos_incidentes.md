# Lista de contactos de resposta a incidentes — por papel

| Campo | Valor |
|---|---|
| Ticket | KAM-113 |
| Runbook | [`resposta_incidentes.md`](resposta_incidentes.md) |
| Estado | **Estrutura sem valores.** Nenhuma entrada foi verificada |

> **Este repositório é público e esta lista não leva nenhum contacto.** Leva o **papel**, o
> **tipo de canal**, **onde está o valor** e **quem é o dono da entrada**. Os números, os
> e-mails e os nomes vivem no **repositório de provas** (privado; `E3` requisito 25) ou no cofre
> de segredos, e é lá que se verificam. Um número de telefone pessoal neste ficheiro é um
> defeito: a varredura do padrão de telefone que o X-11 usa nos logs aplica-se também aqui.

**Regra de frescura:** cada entrada tem **dono** e **data de verificação**, e a data tem de ser
de há **≤ 90 dias** (critério do ticket; *proposta*). Verificar é **contactar de facto** pelo canal e registar
a resposta — não é reler a entrada. Uma entrada com data mais antiga está **vencida** e conta
como se não existisse: o runbook, ao precisar dela, escala ao fundador.

| # | Papel | O que é | Canal (tipo) | Onde está o valor | Dono da entrada | Verificada em | Estado |
|---|---|---|---|---|---|---|---|
| 1 | **APD** | Autoridade de protecção de dados: canal de notificação e de pedidos | Formulário/e-mail oficial (NÃO VERIFICADO qual) | Repositório de provas | PRIV | — | **por verificar** |
| 2 | **Meta** | Direct Support do Business Manager; contacto de segurança | Portal de suporte | Repositório de provas | OPS | — | **por verificar** |
| 3 | **Facilitador de pagamentos** | Contacto técnico e de segurança do(s) facilitador(es) em uso | E-mail + canal técnico | Repositório de provas | AP | — | **por verificar** |
| 4 | **Alojamento** | Suporte do anfitrião/cloud (a decisão D1 está aberta: o fornecedor ainda não está escolhido) | Portal de suporte + telefone de emergência | Repositório de provas | OPS | — | **por verificar** — não há fornecedor |
| 5 | **Fornecedores de LLM** | Contacto de segurança de cada fornecedor em `ops/secrets-inventory.yaml` | Portal / e-mail de segurança | Repositório de provas | AP | — | **por verificar** |
| 6 | **Advogado externo (ADV)** | Parecer e revisão de textos | E-mail + telefone | Repositório de provas | PRIV | — | **vago** — não há advogado contratado (KAM-104) |
| 7 | **SEG** (titular) | Responsável de Segurança: comanda o incidente | Telefone + canal interno | Cofre | SEG | — | **por verificar** |
| 8 | **SEG** (suplente) | | Telefone + canal interno | Cofre | SEG | — | **vago** |
| 9 | **PRIV** (titular) | Responsável interno de privacidade | Telefone + e-mail | Cofre | PRIV | — | **por verificar** |
| 10 | **PRIV** (suplente) | | | Cofre | PRIV | — | **vago** |
| 11 | **OPS** (titular e suplente) | SRE de serviço | Telefone + escala | Cofre | OPS | — | **por verificar** |
| 12 | **AP** (titular) | Arquitecto de Plataforma | Telefone + canal interno | Cofre | AP | — | **por verificar** |
| 13 | **Fundador** | Escalada: decisões que não são do SEG (§9.4 do runbook) | Telefone | Cofre | SEG | — | **por verificar** |
| 14 | **Contacto do dono de cada PME** | O canal alternativo verificado do dono (KAM-115) | E-mail do dono | Tabela de contactos do dono (`owner_contacts`), **não esta lista** | PRIV | por tenant | n/a — vive no sistema |

**A entrada 14 não é uma linha desta lista:** o contacto de cada dono vive no sistema
([`../avisos-ao-dono.md`](../avisos-ao-dono.md)), com a sua própria prova de verificação e a sua
própria invalidação por falha de entrega. A lista só lembra que o aviso à PME (§7.2 do runbook)
parte de lá.

## Como se verifica (no exercício e de 90 em 90 dias)

1. Quem é dono da entrada abre o valor no repositório de provas e contacta **de facto**, pelo canal.
2. Regista a data, o resultado (respondeu / não respondeu / mudou) e o tempo de resposta.
3. Se mudou, corrige-se **no repositório de provas**; este ficheiro só muda a data e o estado.
4. Uma entrada que não respondeu passa a **vencida** e abre-se um ticket `fix`.

## O que esta lista não resolve

- **Não há ADV** nem fornecedor de alojamento (D1); as entradas 4 e 6 não podem ser verificadas
  até existirem.
- **Não há suplentes** nomeados: as entradas 8 e 10 estão vagas.
- **O canal da APD** é desconhecido (NÃO VERIFICADO): o site da APD tem formulários, mas qual se
  usa para violações depende de a Circular 02 se aplicar (A-05 do pacote do KAM-104).

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | Novembro 2026 | Emissão (KAM-113): estrutura por papel, sem valores. Nenhuma entrada verificada | Equipa KAMBÁ |
