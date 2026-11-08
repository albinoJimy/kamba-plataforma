# Runbook RB-K08 — Base de dados indisponivel ou corrompida; restauro PITR

**Esboco** (KAM-080, criterio 4: «os *stubs* RB-K01 a RB-K10 (titulo, gatilho,
severidade)»). **Nao e procedimento ratificado e nao se executa a partir daqui.**
O runbook completo — passos executaveis por quem nao esteve na conversa,
ensaiados por outra pessoa que nao o autor — e o **KAM-083**, que depende deste
ticket.

O que este *stub* existe para fazer sao duas coisas, e so duas:

1. **dar ao alerta um destino que existe.** A regra do `docs/tecnica/09` §9.2 e
   «alerta sem runbook e removido»; o `runbook_url` de cada regra de alerta
   aponta para este ficheiro, e o *lint* de `tools/obs_lint` recusa um alerta
   cujo destino nao exista no disco;
2. **fixar o gatilho e a severidade**, que sao o que o alerta codifica. O
   diagnostico e a mitigacao estao na linha deste runbook em
   `docs/tecnica/09` §13 e **nao se repetem aqui**, para que nao haja duas
   versoes a divergir antes de o KAM-083 escrever a definitiva.

| Campo | Valor |
|---|---|
| ID | **RB-K08** |
| Cenario | WAL parado, *host* perdido, erro de integridade, ou restauro mensal falhado |
| Severidade | **P1** (WAL parado), **P2** (restauro mensal falhado) |
| Alertas que apontam para aqui | **Nenhum, hoje — e o que falta mudou com o KAM-079.** As duas metricas existem (`backup_wal_idade_segundos` e `backup_restauro_desfecho_total`, em `libs/py-core/src/kamba_core/backup/metricas.py`) e **nenhum processo as serve**: servi-las exige o pgBackRest a correr, que exige um `repo1` alcancavel, que exige a **D1/KAM-105**. Uma regra de alerta sobre elas poria o `tools/obs_lint` vermelho (`metrica_sem_produtor`), e e essa regra que cumpre a promessa escrita no `ops/metricas/catalogo.yaml`. O gatilho, a severidade e este runbook estao fixados em dado no `../../infra/backup/cobertura.yaml`, e o `tools/backup_lint` confronta-os com esta pagina e com o catalogo. O `ingress_parado` aponta para o RB-K01 |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K08** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Duas condicoes com severidades diferentes (`docs/tecnica/09` §9.2):

- **WAL** — o ultimo arquivo tem mais de **5 minutos** (P1);
- **restauro mensal** — o *job* de restauro do mes falhou (P2).

O WAL e P1 e o restauro falhado e P2, e a ordem nao e arbitraria: o WAL parado e perda de dados **a acontecer agora** (o RPO a crescer em tempo real); o restauro falhado e a descoberta de que a rede de seguranca pode nao estar la — grave, mas sem relogio a correr.

## 2. Sinal

`pgbackrest check`, estado do disco (`docs/tecnica/09` §13, linha RB-K08). O desenho de backups e DR e o §8 do mesmo documento.

A configuracao do pgBackRest entrou com o **KAM-079** e esta em
[`../../infra/backup/`](../../infra/backup/) — **e nao esta montada por nenhum
compose**, com a razao escrita no `pgbackrest.conf`: `archive_mode = on` com um
`repo1` inalcancavel enche o `pg_wal` ate o cluster deixar de aceitar escritas.
Logo, hoje, **nem o `pgbackrest check` nem o `pgbackrest info` tem onde correr**
contra um `repo1` de producao, e quem cair aqui num incidente nao tem backup para
restaurar. (Correram num ensaio local com esta configuracao, contra um repositorio
num volume Docker: secao 4.) Isso nao e uma
lacuna deste runbook: e o estado do sistema, e esta dito na seccao de
verificacao do bloco KAM-079 com o credor (**D1/KAM-105**, o destino do `repo1`).

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.

## 4. O que o ensaio do KAM-085 mediu, e o procedimento do KAM-083 tem de levar

O KAM-085 correu os cenarios A (perda do *host*), B (corrupcao logica) e C (cofre
indisponivel) **num ensaio local**: PostgreSQL 18.6 da imagem do compose, o
pgBackRest do PGDG, a configuracao de `infra/backup/` tal como esta em git, o
esquema real e dados sinteticos. O repositorio era um volume Docker e nao um
`repo1` noutro dominio de falha. Os numeros e os comandos estao em
[`../evidencia/KAM-085.md`](../evidencia/KAM-085.md); a forma de conduzir o
simulacro humano esta em [`simulacro-de-dr.md`](simulacro-de-dr.md).

**Isto nao e o procedimento**, pela razao da secao 3. Sao as correccoes que o
ensaio encontrou e que o procedimento do KAM-083 tem de trazer escritas — cada
uma com o estado em que ficou:

| # | O que o procedimento tem de dizer | Estado |
|---|---|---|
| 1 | **Antes de montar o arquivo em producao, o contentor do `postgres` leva `init: true`.** Com `archive-async=y` e o `postgres` como PID 1, um `archive-push` que falha (repositorio inalcancavel, stanza em falta) reinicia o cluster inteiro: 13 reinicios em 180 s sem `init`, 0 com `--init`. Nenhum compose deste repositorio tem `init` | **CONFIRMADO** (ensaio `pid1`) |
| 2 | Perda do *host*: `pgbackrest --stanza=kamba restore`, sem alvo, recupera ate ao fim do WAL arquivado. O repositorio **montado so de leitura** basta para restaurar | **CONFIRMADO** (cenario A) |
| 3 | A recuperacao so acabou quando `SELECT pg_is_in_recovery()` devolve `f`. O `pg_ctl -w` volta antes, porque com `hot_standby` o servidor aceita ligacoes a meio da recuperacao | **CONFIRMADO** |
| 4 | **Sem cofre, a passphrase do repositorio tem de chegar ao servidor, e nao so ao `pgbackrest restore`.** O `restore_command` que o pgBackRest escreve e um `archive-get` que o servidor corre durante a recuperacao; com a passphrase so no ambiente do `restore`, o restauro passa e o arranque falha. O que funcionou: decifrar a exportacao para `/dev/shm`, conferir a contagem, escrever a passphrase num `/etc/pgbackrest/conf.d/*.conf` com modo 0600, e apaga-lo quando o *host* voltar a ter cofre | **CONFIRMADO** (cenario C) |
| 5 | Corrupcao logica, **com o primario vivo e antes do PITR**: `SELECT pg_switch_wal()` e `pgbackrest check`, para que o instante T esteja no WAL arquivado; exportar as linhas do `events_outbox` posteriores a T e as marcas de `events_consumed` dos consumidores cujo efeito sai da base | **CONFIRMADO** (cenarios B1 e B2) |
| 6 | PITR: `pgbackrest --stanza=kamba restore --type=time --target="<T>" --target-action=promote`, com T lido no registo da migracao | **CONFIRMADO** |
| 7 | **Depois do PITR, republicar o *outbox* nao basta.** Os eventos posteriores a T perdem-se com o resto, e os efeitos externos que eles ja tinham produzido ficam orfaos (sem a linha que os causou). Reimportar o que se exportou no passo 5 da 0 duplicados, 0 orfaos e 0 eventos perdidos nos consumidores | **CONFIRMADO** — com o publicador e os consumidores do ensaio, que sao a regra em SQL e nao o codigo de producao |
| 8 | O PITR descarta tambem as escritas **boas** posteriores a T: o RPO de uma corrupcao logica e o tempo ate a deteccao, e nao os 5 min do §8.3. O procedimento precisa de um ramo para a corrupcao confinada a uma tabela (restaurar para um *host* lateral e corrigir so essa tabela), que o ensaio nao executou | o RPO **CONFIRMADO**; o ramo e **proposta** |
| 9 | Verificar a cadeia do `audit_log` com a **ultima ancora anterior a T**. A ancora do proprio dia, se for posterior a T, da SEV1 sobre uma cadeia integra (o elo ancorado foi descartado pelo PITR) | **CONFIRMADO** |
| 10 | Depois de promover o *host* restaurado: passar da credencial de restauro (so leitura) a de escrita e fazer um completo novo, porque o ultimo completo e da linha temporal anterior | **NAO VERIFICADO** — o ensaio nao o executou |
| 11 | O *erasure ledger* vive na mesma base: um apagamento feito na janela que o restauro perde perde tambem a sua linha do ledger, e a reaplicacao nao o ve | **NAO VERIFICADO** — raciocinio sobre o esquema (`erasure_ledger`, revisao 0038), nao exercitado |
| 12 | Onde esta a exportacao do cofre. O `infra/backup/cobertura.yaml` escreve que o destino dela e o `repo1`; o `ops/runbooks/secrets-export.md` §4 que o unico destino aceite e um volume offline com dois detentores. O ensaio usou a segunda forma. As duas nao sao equivalentes: no `repo1`, a perda do fornecedor do repositorio leva o backup **e** a exportacao | divergencia entre duas superficies, por resolver (KAM-072) |
