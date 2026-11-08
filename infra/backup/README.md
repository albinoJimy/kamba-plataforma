# Backups fora do *host*, PITR e restauro mensal — KAM-079

Fonte: [`../../docs/tecnica/09_Topologia_Operacao_Escala.md`](../../docs/tecnica/09_Topologia_Operacao_Escala.md) §8;
[`../../docs/tecnica/08_Seguranca_Conformidade.md`](../../docs/tecnica/08_Seguranca_Conformidade.md) §6 (âncora
do `audit_log`), §11 (retenção de backups e *erasure ledger*), §13 N2 (backups
fora de Angola). Ticket: [`../../specs/EPIC-08_Topologia_Operacao.md`](../../specs/EPIC-08_Topologia_Operacao.md),
bloco KAM-079.

## O que está aqui

| Ficheiro | O que é |
|---|---|
| [`cobertura.yaml`](cobertura.yaml) | A **fonte única** dos números e dos predicados: ciclo, retenção, PITR, alvos de RPO/RTO, os dois alertas, o que está coberto e para onde pode sair |
| [`pgbackrest.conf`](pgbackrest.conf) | A configuração do pgBackRest: *stanza* `kamba`, AES-256, retenção, arquivo assíncrono |
| [`postgres-arquivo.conf`](postgres-arquivo.conf) | O fragmento de `postgresql.conf` que liga o arquivo contínuo de WAL |

A verificação é [`../../tools/backup_lint/`](../../tools/backup_lint/), que lê
estes três ficheiros mais o `ops/metricas/catalogo.yaml`, o
`ops/secrets-inventory.yaml` e o *stub* `RB-K08` — **cinco superfícies que dizem
o mesmo** — e falha quando discordam.

```bash
cd tools && python -m backup_lint --root .. lint
cd tools && python -m backup_lint --root .. canario
```

## O que **não** está ligado, e porquê

**Nenhum compose monta estes ficheiros.** Não é trabalho a meio: é a única
decisão segura que se podia tomar hoje, e a razão é curta.

`archive_mode = on` com um `archive_command` que falha não é um backup
incompleto — é uma **falha de disponibilidade**. O PostgreSQL não recicla um
segmento de WAL até o `archive_command` devolver 0; com o repositório
inalcançável, o `pg_wal` cresce a cada 60 s do `archive_timeout` até o disco
encher, e um cluster com o disco cheio deixa de aceitar escritas. Um ticket de
backups que derrubasse a base de dados para parecer entregue seria o pior
resultado possível.

E o repositório **é** inalcançável, por três coisas em cadeia que não são de
engenharia:

1. **Não há destino.** A **D1** (KAM-105) não escolheu jurisdição nem
   fornecedor. O `docs/tecnica/09` §5.3 dá a regra de trabalho (Luanda se a
   cotação ≤ 2× JNB, com SLA e 2.º local angolano; senão JNB/CPT com
   procedimento concluído) e **não dá o fornecedor**.
2. **Sem destino não há FQDN**, e sem FQDN não há linha na *allowlist* de
   [`../egress/proxy-saida.yaml`](../egress/proxy-saida.yaml). A regra dessa
   *allowlist* vale nos dois sentidos — todo o destino aprovado é declarado por
   um serviço, e todo o destino declarado está aprovado —, e um `repo1` sem FQDN
   não dá nenhum dos dois lados. É a mesma leitura com que
   [`../egress/alertmanager.yaml`](../egress/alertmanager.yaml) tem a lista
   vazia: «um FQDN escrito aqui por antecipação **passava o gate** e mandava
   [dados] para um sítio que ninguém decidiu».
3. **Sem `apd_ref` não sai dado real**, por ADR-008 e pelo N2 do
   `docs/tecnica/08` §13. O `repo1` recebe cópias de bases de dados inteiras:
   aqui o palpite custa mais do que num destino de notificação.

Ligar isto são duas edições, quando houver destino: uma linha de `volumes:` no
`../compose/docker-compose.prod.yml` e o `include` no `command:` do `postgres`.
Nenhuma das duas se faz antes do destino.

## Porque é que o pgBackRest não é um serviço do conjunto reduzido

Além das três acima, há uma razão medida e local, e vale escrevê-la porque é a
que surpreende:

`tools/compose_prod/tests/test_lint.py:58` prende a soma do manifesto do
conjunto reduzido a **24 064 MiB exactos**, que é a soma das linhas de limites
propostos do **bloco do KAM-076**. Um serviço novo é memória que aquela proposta
não contém, e mudar aquela igualdade é mudar a medição de outro ticket. O
acréscimo legítimo é com o ticket que traga o `repo1`.

E a **rede** já tem a intenção escrita: o comentário das redes do
`../compose/docker-compose.prod.yml` diz que «com o KAM-079 o pgBackRest … vai
precisar de sair para o repositório fora do *host*, e há-de sair pelo
`proxy-saida` como os outros» — isto é, na rede `ops` e não em `data`. O
`postgres` está **só** em `data`, que é `internal: true` e sem DNS para fora
(medido pelo KAM-076: dez destinos, dez `gaierror`), pelo que um pgBackRest
colado ao Postgres não alcançaria repositório nenhum.

## Os predicados, e porque são funções

Não há agendador neste repositório — medido: nem `cron`, nem `repeat:`, nem
`delay:`; nasce com o KAM-071/KAM-078. O bloco pede «restauro mensal
**automático**», e as duas metades daquela frase têm donos diferentes: o
*mensal* é um predicado, que se escreve e testa hoje; o *automático* é um
agendador, que não existe.

Por isso cada decisão é **uma função idempotente sobre um predicado**, em
[`../../tools/backup_lint/politica.py`](../../tools/backup_lint/politica.py),
com o **relógio por parâmetro** e o prazo **em coluna** (`periodo_dias` do
`cobertura.yaml`):

| Função | O predicado |
|---|---|
| `pode_enviar` | **o funil** do critério 7: nada de dados reais sem `apd_ref` |
| `restauro_devido` | o restauro está em dívida a `agora`? («nunca correu» = sim) |
| `idade_do_wal_segundos` / `wal_em_alerta` | a idade passou os 300 s do §9.2? («nunca arquivou» = `inf`, não 0) |
| `debito_mbps` / `orcamento_a_corrigir` | o débito medido contra o orçamento do §8.2, e a regra dos 20% |
| `sujeitos_a_reaplicar` | quem foi apagado **depois** do instante de que o backup é cópia |
| `SQL_ANCORA_DO_AUDIT_LOG` | a âncora diária, por tenant, **sem `now()`** — a janela entra por `$1`/`$2` |

Um `now()` dentro de uma função (ou de uma consulta) não se consegue acelerar
num ensaio: para provar que o restauro de há 31 dias está em dívida, teria de se
esperar 31 dias ou mentir ao relógio do sistema.

## Segredos

Não há nenhum valor de segredo nesta pasta, e nunca haverá. Os dois segredos
estão em [`../../ops/secrets-inventory.yaml`](../../ops/secrets-inventory.yaml):

* `backup_repo_cifra_passphrase` — **sem ela o backup é inútil** (§8.1), e é por
  isso que a entrada existe antes de haver repositório: um segredo sem registo
  não tem quem lhe guarde a **cópia offline**. Rodar esta chave **não** re-cifra
  os backups existentes, e isso está escrito na entrada;
* `backup_repo_credenciais` — **duas instâncias e não uma**, pela defesa contra
  *ransomware* do §8.3: «restauro com credenciais distintas e **sem** acesso de
  escrita a partir de produção».

O *object lock* fica **NÃO VERIFICADO**: o
[`../../docs/evidencia/KAM-011-seaweedfs.md`](../../docs/evidencia/KAM-011-seaweedfs.md)
§3.3 mediu-o e é **INDÍCIO** — a sonda não prova que a retenção sobreviva a um
reinício (os dados estavam em `tmpfs`) nem que não se contorne fora da API S3. A
alternativa que o bloco nomeia é um *host* de backup que **puxa**, e esse depende
da D1.
