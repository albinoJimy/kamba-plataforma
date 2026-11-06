# Rotação de *on-call* — **modelo, por preencher**

| Campo | Valor |
|---|---|
| Ticket | KAM-082 (critério 7) |
| Fonte | [`../docs/tecnica/09_Topologia_Operacao_Escala.md`](../docs/tecnica/09_Topologia_Operacao_Escala.md) §16 |
| Estado | **Por preencher.** Não há pessoas atribuídas, e não há canal de alertas |
| Quem preenche | **Responsável de Produto**, com o fundador |

> **Este ficheiro não leva nomes de pessoas, e isso não é um esquecimento.** O
> repositório é **público**. Uma escala de turnos com nomes e números é um
> inventário de quem está acordado a que horas, e isso não se publica. Quando a
> rotação existir, os marcadores abaixo preenchem-se **fora** deste repositório,
> num sítio com controlo de acesso, e aqui fica só o apontador.

---

## 1. O que o §16 exige

| Requisito | Valor |
|---|---|
| Pessoas na rotação | **≥ 3** |
| Período | semanal |
| Cobertura | **07:00–23:00 WAT** (horário de comércio) |
| Fora da cobertura | um alerta **P1** chama **apenas o primário**; a degradação automática (doc 09 §12) protege os dados |
| Escalamento | primário → **secundário aos 15 min** → arquitecto |
| Depois do turno | passagem de turno escrita; compensação de *on-call* e dia de folga após P1 nocturno |
| Depois de um incidente | *post-mortem* sem culpa em **≤ 5 dias** |

A frase do §16 que explica por que isto é parte do SLO e não um acessório: o
orçamento de **3,6 h/mês** de 99,5% **não cobre** noites inteiras sem resposta —
oito horas de silêncio são 480 min, mais do dobro do orçamento mensal.

---

## 2. A escala (marcadores)

| Semana | Primário | Secundário | Escalamento final |
|---|---|---|---|
| `<AAAA-SS>` | `<PAPEL: Plataforma/SRE>` | `<PAPEL: Engenharia de agentes>` | `<PAPEL: Arquitecto>` |
| `<AAAA-SS>` | `<PAPEL: Engenharia de agentes>` | `<PAPEL: Ops/Trust & Safety>` | `<PAPEL: Arquitecto>` |
| `<AAAA-SS>` | `<PAPEL: Ops/Trust & Safety>` | `<PAPEL: Plataforma/SRE>` | `<PAPEL: Arquitecto>` |

Três linhas porque o §16 pede **≥ 3** pessoas e a rotação é semanal: com menos de
três, uma delas está de serviço em semanas seguidas. Os papéis são os quatro do
§16; **a atribuição de pessoas a papéis não está neste repositório.**

---

## 3. Duas coisas que impedem este ficheiro de funcionar hoje

Estão aqui e não na gaveta porque quem preencher a escala precisa de saber que
preenchê-la não basta.

1. **O Alertmanager não notifica ninguém.** Os três `receivers` de
   [`../infra/compose/alertmanager/alertmanager.yml`](../infra/compose/alertmanager/alertmanager.yml)
   não têm notificador, porque o **canal de alertas não está escolhido** —
   escolher um acrescenta um subprocessador (**KAM-069**). Os alertas avaliam-se,
   agrupam-se e ficam visíveis no Alertmanager, e **nenhum ser humano é
   notificado**. Sem canal, «escala ao secundário em 15 min» não tem mecanismo.
2. **O escalamento temporizado não é do Alertmanager.** Ele reenvia
   (`repeat_interval`) e inibe (`inhibit_rules`), mas não sabe se alguém
   *reconheceu* um alerta nem muda de destinatário por causa disso. Um
   escalamento a 15 min por falta de reconhecimento precisa de um gestor de
   plantão (*paging*), que é outro subprocessador e outra decisão.

**Credor: o fundador**, para a composição da rotação; **KAM-069** para o canal e
para o gestor de plantão.

---

## 4. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Modelo criado pelo **KAM-082**, critério 7. Requisitos do doc 09 §16 fixados, escala com marcadores de papel e **sem nomes de pessoas** (repositório público), e as duas faltas a montante medidas: o Alertmanager sem notificador (KAM-069) e a ausência de gestor de plantão. A caixa do critério 7 fica **vazia**, com o fundador como credor. | Equipa KAMBÁ |
