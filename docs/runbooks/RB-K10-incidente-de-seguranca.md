# Runbook RB-K10 — Incidente de segurança

| Campo | Valor |
|---|---|
| ID | **RB-K10** |
| Versão | 1.0 |
| Cenário | Fuga, acesso indevido, credencial em posse de terceiro, ou comprometimento confirmado ou suspeito |
| Severidade | **P1** à entrada; a classe final (P1–P4) dá-a a triagem do procedimento |
| Alertas que o activam | **Nenhum, por desenho** — um incidente de segurança não se detecta por limiar. Ver §1 |
| Gatilho manual | Qualquer pessoa que ouça falar de um incidente (alerta sem causa, PME, titular, fornecedor, Meta); escalamento do **RB-K07** quando a suspeita de fuga de um segredo se confirma; escalamento do RB-K06 ou do RB-K09 quando a origem é maliciosa |
| Nível de degradação | — (a contenção pode isolar um *tenant* ou cortar um caminho) |
| Dono | Responsável de Segurança (**SEG**), que comanda o incidente |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca.** Roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3; o exercício anual é o de [`../seguranca/exercicio_simulacao.md`](../seguranca/exercicio_simulacao.md). Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K10; [`../tecnica/08_Seguranca_Conformidade.md`](../tecnica/08_Seguranca_Conformidade.md) §10 |
| Estado | **Proposta**, não ensaiada |

> **Este runbook é uma porta, não o procedimento.** O procedimento é
> [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md)
> (KAM-113), que o próprio documento diz ser «o conteúdo» do RB-K10 e pede que o
> runbook **remeta para lá e não duplique**. Esta página segue o modelo comum
> ([`README.md`](README.md) §3) e diz, por ordem, o que fazer nos primeiros
> minutos e onde está cada passo. Duas cópias de uma árvore de triagem divergem; uma
> não.

---

## 0. Antes de começar

- **Não há escala de *on-call* nem lista de contactos com valores.** A
  [lista de contactos](../seguranca/contactos_incidentes.md) tem a estrutura e
  nenhuma entrada verificada; um papel vago escala para o fundador
  (`resposta_incidentes.md` §3).
- **Não há advogado contratado** (KAM-104). Nenhum texto externo sai sem revisão
  do ADV; enquanto o papel estiver vago, sai só com decisão do fundador.
- **Não há script de recolha de evidência** (`resposta_incidentes.md` §7). A
  exportação faz-se à mão, pelos comandos do §2 abaixo.
- **A rotação de um segredo não fica registada no `audit_log`** — o domínio de
  `action` não tem acção para isso (ver RB-K07 §0). Regista-se na **linha
  temporal** do incidente.

## 1. Cenário e gatilho

A entrada é manual. O que distingue este runbook dos vizinhos:

| Se… | Então |
|---|---|
| há suspeita de que alguém **de fora** tem ou usou uma credencial, ou ela esteve num sítio público (este repositório é público) | **RB-K10**, e o RB-K07 corre dentro da contenção |
| é uma rotação por calendário, sem suspeita | RB-K07, e não este |
| a Meta desligou a conta e a PME não o pediu | RB-K06; se a causa for acesso indevido, abre também este |
| um contacto ou IP inunda o sistema | RB-K09; se for ataque dirigido, abre também este |

## 2. Diagnóstico

O diagnóstico é a **triagem**: a árvore P1–P4 de `resposta_incidentes.md` §5, com
as duas regras de prova e as definições de «em posse de terceiro» e «âmbito de
plataforma». Em dúvida sobre qual é o segredo, é P1.

Os comandos de que a triagem e a preservação precisam:

```bash
# A cadeia do audit_log, antes de qualquer extracto (`resposta_incidentes.md` §7.1).
# Sai 0 com «cadeia intacta»; sai 2 com «SEV1 auditoria» no stderr.
python db/auditoria.py verificar --tenant "<tenant_id>"
```
`não verificado` contra produção (não há). A ferramenta, os argumentos e os
códigos de saída são os de `db/auditoria.py` (KAM-012), documentados em
[`../auditoria.md`](../auditoria.md). Liga-se à base pelas variáveis de
`db/ligacao.py` (`KAMBA_DB_HOST`, `KAMBA_DB_PORT`, `KAMBA_DB_NAME` e a palavra-passe
do papel, pelo cofre) — e **hoje não há onde o correr**: o `postgres` de produção não
publica porta e só está na rede interna `data` ([RB-K08](RB-K08-base-de-dados-e-restauro.md) §2.3).

```bash
# Há um segredo no repositório ou numa árvore copiada? Sai 0 limpo, 1 achados.
cd tools && python -m scan_secrets --root .. tree
```
`verificado` na árvore deste ramo a 2026-11-09 (saída 0). É o mesmo instrumento do
*gate* 9.

```bash
# Os alertas activos na hora T0 — vão para a linha temporal.
docker exec kamba-prod-alertmanager-1 \
  amtool --alertmanager.url=http://127.0.0.1:9093 alert query
```
`verificado` contra o Alertmanager v0.28.1 do compose, com a configuração do
repositório, a 2026-11-09.

## 3. Mitigação

1. **Abrir o registo antes de avaliar**, com o T0 verdadeiro
   (`resposta_incidentes.md` §2 e §4). Quem: quem ouviu primeiro.
2. **Chamar o SEG.** Ele comanda. Sem SEG alcançável, o fundador.
3. **Triagem em ≤ 1 h (PRZ-1):** a árvore do §5 do procedimento dá a classe.
4. **Conter** pela tabela do §6 do procedimento — revogar e rodar chaves (o
   **RB-K07**, com a ordem de incidente: LLM e provedores primeiro), isolar um
   *tenant* (estado `suspenso`; a chave virtual com `max_budget: 0` **não existe no compose actual** — o LiteLLM não tem base de dados, RB-K03 §0), suspender um
   destino de transferência, cortar um caminho. Conter antes de compreender, **sem
   destruir o que se vai precisar**.
5. **Preservar a evidência em ≤ 24 h (PRZ-7)** pelo §7 do procedimento: a cadeia
   verificada primeiro (§2 acima), depois o extracto, os logs, os *snapshots* e os
   avisos de terceiros, cada ficheiro com `sha256` na linha temporal. **O destino é o
   repositório de provas, privado — nunca este repositório.**
6. **Avaliar em ≤ 24 h (PRZ-2)** e **notificar** pelo §8 e §9 do procedimento. Os
   prazos de 72 h para a APD e os titulares são **boa prática; obrigação a
   confirmar por parecer** — não se escrevem como lei.

## 4. Critério de recuperação

- a contenção do §6 do procedimento está feita e cada acção tem linha temporal;
- se houve rotação, o RB-K07 §4 passa para cada segredo rodado;
- `python db/auditoria.py verificar --tenant "<tenant_id>"` sai **0** para cada
  *tenant* afectado (`não verificado` contra produção);
- a decisão de notificar está registada, com quem a tomou;
- o *post-mortem* sem culpa está marcado para ≤ 5 dias (doc 09 §16).

## 5. Escalamento

O SEG comanda desde o primeiro minuto; o escalamento é o do §3 do procedimento
(papéis SEG, PRIV, ADV, OPS, AP, e o escriba). Papel vago → fundador. De fora: os
canais da [lista de contactos](../seguranca/contactos_incidentes.md), por papel.

## 6. Comunicação

- **Interna:** a linha temporal, mantida pelo escriba.
- **PMEs, APD, titulares:** pelos **modelos** de
  [`../seguranca/modelos/`](../seguranca/modelos/), e **só** depois da revisão do
  ADV e da autorização do SEG (`resposta_incidentes.md` §9). Este runbook não traz
  texto próprio: um segundo texto ao lado dos modelos seria uma segunda versão a
  divergir.

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| A notificação à APD em 72 h é boa prática e possível obrigação da Circular 02 | **INDÍCIO**, contraditório — *a confirmar por parecer* | `E3` §1, pergunta 7; `resposta_incidentes.md` §1.1 |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**). Remete para `docs/seguranca/resposta_incidentes.md` (KAM-113) em vez de o duplicar, como esse documento pede; acrescenta a entrada, o encaminhamento face aos vizinhos, os comandos dos primeiros minutos com a marca de verificação e as lacunas do §0 | KAM-083 |
