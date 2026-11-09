# Runbook RB-K08 — Base de dados indisponível ou corrompida; restauro PITR

| Campo | Valor |
|---|---|
| ID | **RB-K08** |
| Versão | 1.0 |
| Cenário | WAL parado, *host* perdido, erro de integridade, corrupção lógica (migração, *bug*), ou restauro mensal falhado |
| Severidade | **P1** (WAL parado, *host* perdido, corrupção); **P2** (restauro mensal falhado) |
| Alertas que o activam | **Nenhum, hoje.** As duas regras (WAL > 5 min, P1; restauro mensal falhado, P2) estão fixadas em dado em [`../../infra/backup/cobertura.yaml`](../../infra/backup/cobertura.yaml) e por escrever: `backup_wal_idade_segundos` e `backup_restauro_desfecho_total` existem (`libs/py-core/src/kamba_core/backup/metricas.py`) e **nenhum processo as serve**, porque o pgBackRest não corre em compose nenhum. Credores: KAM-079, KAM-071/KAM-078 (agendador), **D1/KAM-105** (`repo1`) |
| Gatilho manual | `alvo_em_baixo` ou `ingress_parado` com o Postgres em baixo (RB-K01 encaminha para aqui); erro de integridade visto em logs; uma migração ou *bug* que escreveu mal; o simulacro trimestral ([`simulacro-de-dr.md`](simulacro-de-dr.md)) |
| Nível de degradação | **N5** (doc 09 §12): BD só de leitura ou lenta — o ingress continua a aceitar e a enfileirar, sem confirmações de dinheiro |
| Dono | Plataforma/SRE |
| Última revisão | 2026-11-09 (KAM-083) |
| Último ensaio | **Nunca como mesa-redonda** (roteiro em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3). Os comandos de restauro correram no **ensaio local** do KAM-085 (anexo A), conduzido por quem escreveu o ensaio — não é o critério 2. Credor: o fundador |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K08; §8 (backups e DR) |
| Estado | **Proposta**, não ensaiada por quem não a escreveu |

---

## 0. Antes de começar

- **Não há backup de produção para restaurar.** A configuração do pgBackRest está em
  [`../../infra/backup/`](../../infra/backup/) e **não está montada por nenhum
  compose**: `archive_mode = on` com um `repo1` inalcançável enche o `pg_wal` até o
  cluster deixar de aceitar escritas. O destino do `repo1` é a **D1/KAM-105**. Até
  lá, uma perda do *host* é perda de dados, e este runbook não a resolve.
- **O contentor do `postgres` não tem `init: true`** (anexo A, linha 1). Antes de
  montar o arquivo em produção, é a primeira coisa a mudar — sem ele, um
  `archive-push` a falhar reinicia o cluster.
- **A reaplicação do *erasure ledger* não tem ferramenta.** Existem os predicados
  (`sujeitos_apagados` e `sujeitos_a_reaplicar` em
  `libs/py-core/src/kamba_core/direitos/eliminacao.py`) e nenhum comando que faça o
  apagamento. Credor: **KAM-070**.
- **Não há agendador**, logo não há restauro mensal automático nem âncora diária
  automática do `audit_log` (KAM-071/KAM-078).

## 1. Cenário e gatilho

| Ramo | Sinal | Vai para |
|---|---|---|
| **A — o Postgres não responde** | `pg_isready` falha; serviços com erro de ligação | §2.1, depois §3.1 |
| **B — disco cheio ou WAL parado** | `df` acima de 90%; `pg_wal` a crescer | §2.2, depois §3.2 |
| **C — *host* perdido** | o *host* não volta | §3.3 (restauro completo) |
| **D — corrupção lógica** | dados errados escritos por migração ou *bug*, com o primário vivo | §3.4 (PITR) |
| **E — restauro mensal falhou** | o *job* de restauro deu desfecho falhado | §3.5 |

O WAL é P1 e o restauro mensal é P2, e a ordem não é arbitrária: o WAL parado é perda
de dados **a acontecer agora**; o restauro falhado é a descoberta de que a rede de
segurança pode não estar lá — grave, mas sem relógio a correr.

## 2. Diagnóstico

### 2.1 O Postgres responde?

```bash
docker compose -f infra/compose/docker-compose.prod.yml ps postgres
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -f infra/compose/docker-compose.prod.yml logs --since 30m postgres
```
`verificado` o `pg_isready` na imagem `pgvector/pgvector:0.8.7-pg18` do compose,
num contentor isolado, a 2026-11-09 («accepting connections»). `não verificado`
contra produção.

```bash
# Está em recuperação (réplica, ou restauro a meio)? «f» é primário normal.
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT pg_is_in_recovery()"'
```
`verificado` na mesma imagem a 2026-11-09 (devolve `f`).

### 2.2 Disco e WAL

```bash
docker compose -f infra/compose/docker-compose.prod.yml exec postgres df -h /var/lib/postgresql
docker compose -f infra/compose/docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT * FROM pg_stat_archiver"'
```
O `df` está `verificado` na mesma imagem; o `pg_stat_archiver` é vista do
PostgreSQL e `não verificado` com arquivo ligado (não há arquivo em compose
nenhum). Um `failed_count` a subir com `last_archived_time` parado é o WAL parado.

```bash
# Com o pgBackRest montado (hoje não está): o repositório é alcançável e o arquivo funciona?
docker compose -f infra/compose/docker-compose.prod.yml exec -u postgres postgres \
  pgbackrest --stanza=kamba check
docker compose -f infra/compose/docker-compose.prod.yml exec -u postgres postgres \
  pgbackrest --stanza=kamba info --output=json
```
`não verificado` nesta forma: o serviço que correrá o pgBackRest em produção não
existe (D1/KAM-105). Os mesmos subcomandos, com a stanza `kamba`, correram no ensaio
local do KAM-085 como `docker exec -u postgres <contentor> pgbackrest --stanza=kamba
check` ([`../evidencia/KAM-085.md`](../evidencia/KAM-085.md)).

### 2.3 A cadeia do `audit_log`

```bash
python db/auditoria.py verificar --tenant <tenant_id>
python db/auditoria.py verificar --tenant <tenant_id> --ancora <ficheiro-da-ancora>
```
Sai **0** com «cadeia intacta» e **2** com «SEV1 auditoria» no stderr
([`../auditoria.md`](../auditoria.md)). `não verificado` contra produção. Depois de um
PITR, usa-se a **última âncora anterior a T** (anexo A, linha 9).

## 3. Mitigação

### 3.1 Ramo A — o Postgres não responde

1. Ler os logs do §2.1. Se for falta de memória ou de disco, ir ao ramo B.
2. `docker compose -f infra/compose/docker-compose.prod.yml restart postgres`, **uma**
   vez. Se não voltar em 5 min, é ramo C. (`não verificado` contra produção.)
3. Enquanto está em baixo, o sistema está em **N5**: o GWY continua a responder e a
   enfileirar no Valkey; nenhum serviço confirma dinheiro.

### 3.2 Ramo B — disco cheio ou WAL parado

1. Se o `pg_wal` cresce porque o arquivo falha: o `repo1` está alcançável? (`check`
   do §2.2). **Não se apaga WAL à mão** — um segmento apagado antes de arquivado é
   RPO perdido.
2. Se o `repo1` não volta e o disco vai encher: decisão do Arquitecto, registada,
   entre aumentar o disco e desligar temporariamente o arquivo (que **suspende o RPO**
   e tem de ser dito na comunicação).

### 3.3 Ramo C — *host* perdido (restauro completo)

1. **Declarar o incidente** e escolher o restauro — decisão humana (o primeiro passo
   que o simulacro do KAM-085 não mede).
2. Novo *host* por IaC: [`../../infra/README.md`](../../infra/README.md) §5 («host
   novo em 30 min»).
3. Restaurar até ao fim do WAL arquivado, com o repositório montado **só de leitura**
   e a credencial de **leitura** (`backup_repo_credenciais/leitura`):
   `pgbackrest --stanza=kamba restore` (anexo A, linha 2).
4. Sem cofre: a passphrase (`backup_repo_cifra_passphrase`) tem de chegar **ao
   servidor**, não só ao `restore` (anexo A, linha 4).
5. Arrancar e esperar por `SELECT pg_is_in_recovery()` = `f` (§2.1; anexo A, linha 3).
6. Verificar a cadeia (§2.3) e correr o *smoke* da pilha.
7. Passar à credencial de escrita e fazer um completo novo (anexo A, linha 10,
   `não verificado`).
8. **Reaplicar o *erasure ledger*** — sem ferramenta (§0). Até ao KAM-070, é um passo
   manual que **não se pode saltar** e que fica por escrever.

### 3.4 Ramo D — corrupção lógica (PITR)

1. Com o primário **vivo**, fixar T: ler a hora no registo da migração ou do
   *deploy*; correr `SELECT pg_switch_wal();` e o `check` (anexo A, linha 5).
2. **Antes do PITR**, exportar as linhas do `events_outbox` e as marcas de
   `events_consumed` dos consumidores com efeito externo, com margem antes de T
   (anexo A, linha 5).
3. Se a corrupção está confinada a **uma tabela**: restaurar para um *host* lateral e
   corrigir só essa tabela, em vez de PITR do primário — perde-se menos (anexo A,
   linha 8; **proposta**, não ensaiada).
4. Senão, PITR: `pgbackrest --stanza=kamba restore --type=time --target="<T>"
   --target-action=promote` (anexo A, linha 6).
5. **Os efeitos externos órfãos** (eventos posteriores a T que já tinham produzido
   efeito fora): **proposta deste runbook**, que fica por ensaiar — reimportar o
   exportado no passo 2 **só para os consumidores de efeito externo** e com o
   consumidor interno parado, e reconciliar à mão as encomendas que o PITR apagou.
   O anexo A, linha 7, mediu que reimportar para todos troca um órfão externo por
   63 internos; a escolha entre os dois é do Arquitecto, registada, até haver
   ensaio.
6. Verificar a cadeia com a **última âncora anterior a T** (anexo A, linha 9) e
   reaplicar o *erasure ledger* (§0).

### 3.5 Ramo E — restauro mensal falhou

P2, sem relógio. Abrir incidente, ler o desfecho do *job*, repetir o restauro para um
*host* descartável à mão pelo ramo C, passos 3 a 6. **Hoje não há *job*** (§0).

## 4. Critério de recuperação

- `pg_isready` aceita ligações e `pg_is_in_recovery()` devolve `f` (§2.1);
- `df` abaixo de 80% e `pg_stat_archiver` com `last_archived_time` a avançar (§2.2);
- `python db/auditoria.py verificar` sai 0 para os *tenants* verificados (§2.3);
- o *smoke* da pilha passa e o `ingress_parado` e o `alvo_em_baixo` resolvem
  (`amtool … alert query` sem eles; ver RB-K01 §2);
- o *erasure ledger* foi reaplicado, com registo — **hoje não se cumpre** (§0).

## 5. Escalamento

Primário → secundário (15 min) → Arquitecto (doc 09 §16). A decisão de PITR, de
desligar o arquivo ou de aceitar órfãos é **do Arquitecto**, registada. Corrupção por
acesso indevido → **RB-K10**. Fornecedor do `repo1` (por decidir, D1).

## 6. Comunicação

- **Interna:** a linha temporal do incidente, com T, a decisão e o RPO efectivo.
- **PMEs:** só se o restauro perder escritas delas (RPO > 0 ou PITR). O texto é o do
  RB-K01 §6 (serviço interrompido), com a frase do que se perdeu — que só se sabe
  depois do restauro. **Proposta, por aprovar** pelo Responsável de Produto.

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| `pg_ctl -w` pode voltar antes do fim da recuperação com `hot_standby` | **INDÍCIO** | anexo A, linha 3 |

---

## Anexo A — o que o ensaio do KAM-085 mediu

**Era o §4 até à versão 1.0 desta página**, e é por esse número que o
`specs/EPIC-08` (bloco KAM-085) e a [`../evidencia/KAM-085.md`](../evidencia/KAM-085.md)
o citam. O conteúdo não mudou; os passos do §3 remetem para as linhas por número.

O KAM-085 correu os cenarios A (perda do *host*), B (corrupcao logica) e C (cofre
indisponivel) **num ensaio local**: PostgreSQL 18.6 da imagem do compose, o
pgBackRest do PGDG, a configuracao de `infra/backup/` tal como esta em git, o
esquema real e dados sinteticos. O repositorio era um volume Docker e nao um
`repo1` noutro dominio de falha. Os numeros e os comandos estao em
[`../evidencia/KAM-085.md`](../evidencia/KAM-085.md); a forma de conduzir o
simulacro humano esta em [`simulacro-de-dr.md`](simulacro-de-dr.md).

**Isto nao e o procedimento**, pela razao da secao 3. Sao as correccoes que o
procedimento do KAM-083 tem de trazer escritas — as linhas 1 a 9 encontradas pelo
ensaio, as 10 a 12 por leitura do esquema e dos documentos —, cada uma com o
estado em que ficou:

| # | O que o procedimento tem de dizer | Estado |
|---|---|---|
| 1 | **Antes de montar o arquivo em producao, o contentor do `postgres` leva `init: true`.** Com `archive-async=y` e o `postgres` como PID 1, um `archive-push` que falha (repositorio inalcancavel, stanza em falta) reinicia o cluster inteiro: 13 reinicios em 180 s sem `init`, 0 com `--init`. Nenhum compose deste repositorio tem `init` | **CONFIRMADO** (ensaio `pid1`) |
| 2 | Perda do *host*: `pgbackrest --stanza=kamba restore`, sem alvo, recupera ate ao fim do WAL arquivado. O repositorio **montado so de leitura** basta para restaurar | **CONFIRMADO** (cenario A) |
| 3 | A recuperacao so acabou quando `SELECT pg_is_in_recovery()` devolve `f`. O `pg_ctl -w` pode voltar antes, porque com `hot_standby` o servidor aceita ligacoes a meio da recuperacao | **INDICIO** — comportamento documentado do PostgreSQL; o ensaio esperou pelo `f`, mas com 3 s de *replay* nao ha artefacto que mostre o `pg_ctl` a voltar antes |
| 4 | **Sem cofre, a passphrase do repositorio tem de chegar ao servidor, e nao so ao `pgbackrest restore`.** O `restore_command` que o pgBackRest escreve e um `archive-get` que o servidor corre durante a recuperacao; com a passphrase so no ambiente do `restore`, o restauro passa e o arranque falha. O que funcionou: decifrar a exportacao para `/dev/shm`, conferir a contagem, escrever a passphrase num `/etc/pgbackrest/conf.d/*.conf` com modo 0600, e apaga-lo quando o *host* voltar a ter cofre | **CONFIRMADO** (cenario C) |
| 5 | Corrupcao logica, **com o primario vivo e antes do PITR**: `SELECT pg_switch_wal()` e `pgbackrest check`, para que o instante T esteja no WAL arquivado; exportar as linhas do `events_outbox` e as marcas de `events_consumed` dos consumidores cujo efeito sai da base, **com margem antes de T** — o `criado_at` do *outbox* e o inicio da transaccao e nao o *commit* | os passos correram (B1, B2); **que o `pg_switch_wal` seja necessario nao se ensaiou** — passaram 60 s de `archive_timeout` depois de T; a margem e **proposta** (achado da revisao, nao ensaiado) |
| 6 | PITR: `pgbackrest --stanza=kamba restore --type=time --target="<T>" --target-action=promote`, com T lido no registo da migracao | **CONFIRMADO** |
| 7 | **Depois do PITR, republicar o *outbox* nao basta.** Os eventos posteriores a T perdem-se com o resto, e os efeitos externos que eles ja tinham produzido ficam orfaos (sem a linha que os causou): 63 no ensaio. Reimportar o que se exportou no passo 5 leva os orfaos externos a 0 — **mas o consumidor interno processa os eventos reimportados e produz 63 efeitos sobre encomendas que o PITR apagou**: troca-se o orfao externo por um interno. Qual dos dois se aceita, ou se se reconstroi o produtor a partir dos eventos, e decisao do procedimento | o orfao externo e a troca: **CONFIRMADO**, com o publicador e os consumidores do ensaio (a regra em SQL, sincronos, nao o codigo de producao); a receita: **por decidir** (KAM-083) |
| 8 | O PITR descarta tambem as escritas **boas** posteriores a T: o RPO de uma corrupcao logica e o tempo ate a deteccao (64 s no ensaio), e nao os 5 min que o `docs/tecnica/09` §8.3 lhe da. O procedimento precisa de um ramo para a corrupcao confinada a uma tabela (restaurar para um *host* lateral e corrigir so essa tabela), que o ensaio nao executou | o RPO **CONFIRMADO**; o ramo e **proposta**; a emenda ao §8.3 do doc 09 e do fundador, que nao foi feita aqui |
| 9 | Verificar a cadeia do `audit_log` com a **ultima ancora anterior a T**. A ancora do proprio dia, se for posterior a T, da SEV1 sobre uma cadeia integra (o elo ancorado foi descartado pelo PITR) | **CONFIRMADO** |
| 10 | Depois de promover o *host* restaurado: passar da credencial de restauro (so leitura) a de escrita e fazer um completo novo, porque o ultimo completo e da linha temporal anterior | **NAO VERIFICADO** — o ensaio nao o executou |
| 11 | O *erasure ledger* vive na mesma base: um apagamento feito na janela que o restauro perde perde tambem a sua linha do ledger, e a reaplicacao nao o ve | **NAO VERIFICADO** — raciocinio sobre o esquema (`erasure_ledger`, revisao 0038), nao exercitado |
| 12 | Onde esta a exportacao do cofre. O `infra/backup/cobertura.yaml` escreve que o destino dela e o `repo1`; o `ops/runbooks/secrets-export.md` §4 que o unico destino aceite e um volume offline com dois detentores. O ensaio usou a segunda forma. As duas nao sao equivalentes: no `repo1`, a perda do fornecedor do repositorio leva o backup **e** a exportacao | divergencia entre duas superficies, por resolver (KAM-072) |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): cinco ramos (A–E), diagnóstico com comandos marcados, mitigação por ramo que remete para as linhas medidas pelo KAM-085, critério de recuperação e escalamento. A tabela do KAM-085 passa do §4 para o **anexo A**, sem alteração de conteúdo | KAM-083 |
