# Runbook — Trust & Safety: uma suspensão decidida, a escada automática acima do ritmo, o recálculo da confiança com falhas, e a recusa da base sobre o tecto, vista pelo `tenant_guard` e lida do registo do PostgreSQL, e o registo parado

**Esboço** (KAM-200, critério 3). **Não é procedimento ratificado** e nenhum passo foi ensaiado
contra uma pilha com tráfego. O desenho está no [`docs/tecnica/10`](../tecnica/10_Onboarding_Governanca.md)
§8.3 e no bloco do KAM-097.

**Não leva número RB-K**, pela razão do [`orcamento-de-erro.md`](orcamento-de-erro.md): a série
`RB-K01`–`RB-K10` é a lista fechada do [`docs/tecnica/09`](../tecnica/09_Topologia_Operacao_Escala.md)
§13, e um `RB-K11` acrescentava uma linha a um canon que este ticket não governa.

| Campo | Valor |
|---|---|
| Cenário | Uma loja foi suspensa por decisão de T&S; a escada automática (`aviso`, `limitacao`) deu mais passos numa hora do que o ritmo esperado; o recálculo da confiança gradual falhou para um tenant (KAM-203); ou a base recusou (`42501`) a uma transacção da aplicação uma operação sobre `platform.trust_level` (KAM-219) |
| Severidade | **P3** a suspensão; **P2** a escada acima do ritmo, o recálculo com falhas e a recusa sobre o tecto |
| Quem age | **T2**, com o responsável de produto de T&S |
| Alertas que apontam para aqui | `ts_suspensao_decidida`, `ts_escada_automatica_acima_do_ritmo`, `confianca_recalculo_com_falhas` e `confianca_tecto_escrita_recusada`, em [`../../infra/compose/prometheus/regras/kamba-trust.yml`](../../infra/compose/prometheus/regras/kamba-trust.yml) |
| Série | `ts_sancoes_total{passo,origem}` e `confianca_recalculos_total{origem,desfecho}`, servidas pelo `onboarding-lote`; `tenant_guard_tecto_recusado_total`, servida pelo `onboarding-lote`, pelo `com` e pelo `worker-canal-entrada` |
| Estado | **Esboço.** Gatilho e leitura fixados; o ritmo de 5 passos por hora é *proposta* |

---

## 1. Qual loja

A métrica não leva tenant (`OBS-I`). A loja lê-se da `platform.ts_sanction`, **pelo lote**
(`kamba_batch`): a ligação de auditoria só vê um tenant com o contexto dele.

```sql
SELECT tenant_id, passo, origem, motivo_publico, case_id, em
  FROM platform.ts_sanction
 WHERE em > now() - interval '1 hour' AND recurso_de IS NULL
 ORDER BY em DESC;
```

**Não corrido** contra uma base com dados do Piloto. O `motivo_interno`, a `regra` e os `sinais` da
mesma linha são só de T&S: não se copiam para um canal de conversa, e nunca para o dono.

## 2. Uma suspensão decidida (`ts_suspensao_decidida`)

A decisão já foi humana, com papel e MFA, na fila de revisão (KAM-089). O alerta existe para que a
equipa saiba que aconteceu, e não para a reverter. **Conta a decisão, e não a transição**: dispara
numa suspensão e num encerramento (que suspende até o prazo do recurso passar), e também sobre uma
loja que já estava suspensa — pela régua de cobrança, por exemplo. Confirmar três coisas:

1. **O estado mudou pela porta.** A suspensão passa pelo `platform.transition_tenant` (KAM-092): há
   uma linha no `platform.tenant_state_log` com o motivo `decisao_ts` e o actor do revisor, e um
   `tenant.suspended` no *outbox*. Sem a linha, a transição não aconteceu (o tenant não estava
   `ativo` nem `restrito`), e o caso mostra porquê.
2. **O aviso ao dono saiu.** Hoje **não sai**: o processo de lote não tem agregador de SMS nem o
   telefone em claro (KAM-116), e o caso fica com o efeito por reaplicar
   (`review_case.efeito_pendente_at`). É o estado esperado até o agregador existir, e não uma falha
   deste alerta.
3. **O recurso.** O dono pode recorrer uma vez; o recurso é outro caso da fila, decidido por outro
   revisor. Um recurso provido devolve a loja a `ativo` pela mesma porta (`tenant.reactivated`) — a
   menos que a suspensão em vigor seja a da régua de cobrança (KAM-058), tenha partido de `restrito`
   (a restrição da Meta), ou não tenha registo: nesses três casos a loja fica `suspenso`, e quem a
   repõe decide-o à mão.

## 3. A escada automática acima do ritmo (`ts_escada_automatica_acima_do_ritmo`)

Mais de cinco passos automáticos numa hora em toda a plataforma. Duas leituras, e a segunda é a
mais provável enquanto a política não estiver calibrada:

- **Um ataque em curso** — vários tenants novos a gerar `burla_provavel` ou `auto_compra`. Ver os
  sinais da última hora por tipo (`ts_sinais_total{tipo}` no painel, ou a `platform.ts_signal`
  pelo lote) e procurar um padrão comum.
- **A política de risco está a limitar lojas honestas.** Os pesos, a meia-vida e os dois limiares
  são *proposta* (`POLITICA_DE_RISCO`, `../../packages/core-ts/src/trust/regras.ts`). Uma
  `limitacao` automática bloqueia produtos novos, e cada uma é recorrível: um surto delas enche a
  fila de recursos.

**Não se desliga a escada à mão.** Mudar a política é mudar a versão dela, e isso é uma alteração
de código revista — não uma operação.

## 4. O recálculo da confiança com falhas (`confianca_recalculo_com_falhas`)

O recálculo do nível de confiança de um tenant (`../../packages/core-ts/src/confianca/lote.ts`) falhou
pelo menos uma vez nos últimos 15 minutos. A etiqueta `origem` diz de onde veio: `aprovacao` (logo depois
de um onboarding aprovado), `entrega` (depois de um `order.delivered`, e o BullMQ repete-o sozinho),
`descida` (a varredura de cada minuto) ou `diario` (a volta de 24 h).

- **Quem ficou por fazer.** Pelo lote, os tenants com caso aprovado e sem linha em
  `platform.trust_level` — esses não cobram até ao nível nascer, porque o *trigger* da cobrança recusa
  sem nível (falha fechada, KAM-096). E os tenants acima do nível 0 que a varredura das descidas lista
  (`SQL_TENANTS_A_DESCER`): esses continuam com o tecto do nível 1.
- **Porquê.** O registo do `onboarding-lote` diz o passo (`confianca_aprovacao_falhou`,
  `confianca_descida_com_falhas`, `confianca_diaria_com_falhas`, `confianca_volta_falhou`) e nunca o
  tenant. A origem `entrega` não tem linha própria: a falha sobe ao BullMQ, que repete o *job*, e o
  registo do consumidor diz o desfecho dele. As causas prováveis são as da ligação: a base em baixo, ou a tranca do tenant presa por uma
  cobrança longa (o `lock_timeout` do processo é 10 s).
- **O que fazer.** Nada à mão no nível: a volta seguinte — a das descidas num minuto, a diária no dia
  seguinte — recalcula o mesmo tenant, e o recálculo é idempotente. Se a falha persistir, reiniciar o
  `onboarding-lote` corre a volta diária no arranque. **Não se escreve `trust_level` à mão**: só o
  `kamba_batch` a escreve, e cada escrita vai ao `audit_log`.

## 5. A recusa da base sobre o tecto (`confianca_tecto_escrita_recusada`)

Uma transacção do `comTenant` ou do `comBatch` (`../../packages/core-ts/src/tenant_guard/`) recebeu da base
um `42501` que nomeia `trust_level`. Só o `kamba_batch` escreve o tecto (KAM-096), e nenhum código da
aplicação o tenta escrever com outro papel: ou alguém está a tentar mudar um tecto por um caminho que não
devia existir (uma injecção, um defeito novo), ou o próprio lote perdeu um privilégio sobre o tecto.
**A base já recusou**: o tecto não mudou. O alerta existe para que se saiba quem tentou.

- **Qual processo.** A etiqueta `job` diz qual: `onboarding_lote`, `com` ou `entrada`.
- **Qual credencial.** O `onboarding-lote` não arranca com a `KAMBA_LOTE_DB_URL` de outro papel
  (`../../services/onboarding-web/src/lote.ts`), pelo que uma recusa nele não é a credencial do arranque:
  é código a tentar o que não devia. Nos outros dois, confirmar que nenhuma mudança recente pôs SQL sobre
  `trust_level` no processo (`git log -S trust_level -- services packages`).
- **Qual tenant.** **Não se lê desta série** (`OBS-I`), nem do `audit_log`, que só tem as escritas que
  passaram. O registo do processo no mesmo minuto pode dizer o passo que falhou, pelo `error_code`, e
  nunca o tenant. **Não verificado** contra uma pilha com tráfego.
- **O que fazer.** Nada no tecto. Se a origem não for a credencial, é um incidente de segurança: preservar
  o registo do processo e do proxy, e seguir o [`RB-K10`](RB-K10-incidente-de-seguranca.md) se o
  pedido vier de fora.
- **O que esta regra não vê.** Uma ligação directa à base com a credencial do `kamba_app`, um processo
  Python, uma transacção aberta à mão (o `consumir` dos eventos, o `comContexto` das acções, a DLQ, o publicador, a lista de espera) ou uma consulta solta num *pool* não chegam ao contador. Essas vê-as a
  regra do §6, desde o KAM-225, pelo registo do PostgreSQL.

## 6. A recusa sobre o tecto no registo do PostgreSQL (`confianca_tecto_recusado_no_registo`)

O recolector `registo-pg` (`../../libs/py-core/src/kamba_core/registo_pg/`) leu no registo do servidor um
`42501` que nomeia `trust_level`, a uma sessão que **não** é do `kamba_batch`. É a mesma recusa do §5, vista
do lado da base: chega aqui a que o servidor escreve no registo — a do `comTenant`, a de uma ligação directa
com a credencial do `kamba_app`, a de um processo Python ou de uma consulta solta. **A base já recusou**: o
tecto não mudou.

- **Se o §5 disparou no mesmo minuto**, é a mesma recusa, e o `job` dele diz o processo: seguir o §5.
- **Se só este disparou**, a recusa veio de fora dos *helpers* — e uma ligação directa com a credencial de
  um serviço é a hipótese a afastar primeiro.
- **Qual papel e quando.** Não se lê desta série (`OBS-I`); lê-se do registo do servidor, no volume
  `postgres-log`, por quem tem acesso ao *host*. O filtro casa o campo `message`, e não a linha inteira
  (`não verificado` em produção, que não existe; o ensaio do KAM-225 leu o mesmo volume com um filtro
  equivalente, `../evidencia/KAM-225.md` §4):

  ```sh
  docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
    sh -c 'grep -h "\"state_code\":\"42501\",\"message\":\"permission denied for table trust_level\"" /var/log/postgresql/*.json'
  ```

  Cada linha diz o `user`, o `remote_host`, o `application_name` e a hora. **Não traz o texto da consulta**
  (`log_min_error_statement=panic`, KAM-225): o que se tentou escrever não está no registo, e o registo não
  substitui o `audit_log`. Mesmo assim, não se cola num ticket, num chat nem num *prompt*: tira-se dela o
  papel, a origem e a hora, e mais nada.
- **O que fazer.** Nada no tecto. Uma recusa a um papel de serviço que nenhum código explica é um
  incidente de segurança: rodar a credencial desse papel (o cofre, KAM-010), preservar o registo do
  servidor antes de ele rodar (24 h, `log_truncate_on_rotation`) e seguir o
  [`RB-K10`](RB-K10-incidente-de-seguranca.md).
- **O que esta regra não vê.**
  - Uma recusa escrita enquanto o `registo-pg` estava em baixo. O alvo é fixo no `prometheus.yml`, pelo que
    um recolector parado ou em ciclo de reinício põe o `up` a 0 e dispara o `alvo_em_baixo`; esse vê o
    processo, e não a recusa perdida.
  - Uma recusa que o próprio SQL apanha. Um bloco PL/pgSQL com `EXCEPTION WHEN insufficient_privilege`
    (ou `WHEN OTHERS`) engole o erro, e o servidor **não o escreve no registo** (medido na revisão
    adversarial do KAM-225). Quem tem a credencial pode sondar o tecto assim sem disparar nada. Isto não
    tem remédio no registo.
  - Uma recusa de uma sessão do `kamba_batch`, também depois de um `SET ROLE` para outro papel: o `user`
    do registo é o da sessão. Se passar pelos *helpers*, vê-a o §5.
- **Um falso positivo conhecido.** Um buraco de raspagem de 10 min ou mais (o Prometheus parado, ou a
  rede de `ops`) volta a disparar a regra sobre uma recusa antiga, pelo segundo ramo dela. A regra do §5
  tem o mesmo comportamento. Antes de tratar o alerta como novo, confirmar no registo que há uma linha da
  última janela.

## 7. O registo do PostgreSQL parado (`registo_pg_registo_parado`)

O `jsonlog` mais novo do volume `postgres-log` não muda há mais de duas horas. Com o servidor a escrever, a
rotação por tempo cria ou trunca o ficheiro de cada hora mesmo sem nada para registar, pelo que isto quer
dizer que o servidor deixou de escrever o `jsonlog`. **Enquanto dura, a regra do §6 está cega**, com o
`/healthz` do `registo-pg` a 200 e o contador a zero.

- **O servidor está de pé?** Se não, este alerta vem ao lado dos dele: seguir o
  [`RB-K08`](RB-K08-base-de-dados-e-restauro.md).
- **O `jsonlog` está ligado?** `SHOW log_destination` e `SHOW logging_collector` pelo `psql` do contentor
  (`não verificado` em produção; o ensaio do KAM-225 mediu-os, `../evidencia/KAM-225.md` §4). Um `postgres`
  recriado sem o `command:` do compose volta ao `stderr`, e os 24 ficheiros velhos ficam no volume a parecer
  registo.
- **O que fazer.** Repor o `command:` do compose e recriar o `postgres`. Uma recusa sobre o tecto na janela
  em que o registo esteve parado não se recupera daqui: ler o `audit_log` e o registo dos processos dessa
  janela.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | Novembro 2026 | Esboço, com as duas regras do KAM-200 | Equipa KAMBÁ |
| 0.2 | Novembro 2026 | KAM-203: o §4, a regra `confianca_recalculo_com_falhas` | Equipa KAMBÁ |
| 0.3 | Novembro 2026 | KAM-219: o §5, a regra `confianca_tecto_escrita_recusada` | Equipa KAMBÁ |
| 0.4 | Novembro 2026 | KAM-225: o §6 e o §7, as regras `confianca_tecto_recusado_no_registo` e `registo_pg_registo_parado`, e o fim do §5 a apontar para o §6 | Equipa KAMBÁ |
