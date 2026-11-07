# `backup_lint` — as cinco superfícies do backup (KAM-079)

```bash
cd tools && python -m backup_lint --root .. lint
cd tools && python -m backup_lint --root .. canario
cd tools && python -m backup_lint --root .. restauro --agora 2026-11-07T00:00:00Z
cd tools && python -m backup_lint --root .. debito --bytes 20000000000 --segundos 1600
```

Códigos de saída: **0** limpo, **1** achados (ou envio recusado pela guarda),
**2** erro de utilização ou configuração que não se lê. A distinção entre 1 e 2 é
a do `canon_lint` e do `obs_lint`: *uma configuração que não se lê não pode
parecer uma configuração conforme.*

## O que lê, e porquê são cinco

| Superfície | O que dela se verifica |
|---|---|
| `infra/backup/cobertura.yaml` | os números, os estados de cobertura, os destinos, os dois alertas |
| `infra/backup/pgbackrest.conf` | cifra, retenção, PITR, `repo1` fora do *host*, nenhum segredo em claro |
| `infra/backup/postgres-arquivo.conf` | `archive_mode`, `archive_timeout` |
| `ops/metricas/catalogo.yaml` | as duas entradas de `regras_por_escrever` dizem o que **hoje** falta |
| `ops/secrets-inventory.yaml` | os dois segredos do ticket estão registados |
| `docs/runbooks/RB-K08-*.md` | o runbook que os alertas citam existe no disco |

**Porque é que são várias e não uma:** a divergência entre elas **não dá erro em
sítio nenhum**. Um `archive_timeout` de 60 s no manifesto e de 300 s no `.conf`
passa por todos os portões deste repositório — os dois ficheiros são válidos,
nenhum compilador os lê, e o defeito só aparece em produção como um RPO que
ninguém prometeu. O limite do alerta do WAL está escrito em **quatro** sítios (o
manifesto, o catálogo de métricas, o *stub* RB-K08 e o `docs/tecnica/09` §9.2). É
a leitura do `tools/lint_contagens` e do `tools/compose_prod`: o erro de conteúdo
aparece **a contar**, não a ler.

## As nove regras

| Regra | O que apanha |
|---|---|
| `r_cifra` | cifra abaixo de AES-256, ausente, ou divergente entre as duas superfícies |
| `r_segredo_em_claro` | um valor literal (ou com omissão silenciosa) numa chave sensível |
| `r_numeros_do_ciclo` | `archive_timeout`, `archive_mode`, PITR, retenção, e a aritmética 5×7=35 |
| `r_repo_fora_do_host` | o repositório apontado para a própria máquina ou para dentro do `PGDATA` |
| `r_cobertura` | uma das três bases ou dos quatro itens em falta; estado inválido; sem credor ou sem razão |
| `r_destinos` | um destino sem dono; um destino para dados reais sem `apd_ref` válida |
| `r_alertas` | severidade fora do §9.2; runbook inexistente; limite separado do RPO; prosa desactualizada no catálogo |
| `r_segredos_no_inventario` | a chave de cifra fora do `ops/secrets-inventory.yaml` |
| `r_restauro` | período não positivo; agendador sem estado ou sem credor |

## O canário

Por **mutação** e não por *fixtures*, pela razão do `compose_prod`: as regras são
sobre relações entre cinco ficheiros, e uma *fixture* por regra não é um ficheiro
— é uma árvore. Trinta cópias da árvore divergem da real sem que nada avise.

Três fechos: uma mutação que já não encontra o texto que trocava **falha** (nunca
um verde); cada caso declara as regras que espera e exige-se que sejam
**exactamente** essas; e o `MINIMO_POR_REGRA` exige que toda a regra de
`lint.REGRAS` tenha caso.

## O funil, e o ensaio que o prende

Os comandos `restauro` e `debito` têm dois formatos de saída (texto e `--json`).
A guarda do critério 7 — nada de dados reais sem `apd_ref` — atravessa os quatro
caminhos pelo **mesmo** ponto: `_decidir` é a única função que chama
`politica.pode_enviar`, e `_imprimir` é a única que escreve.

Isto não é arrumação. Uma guarda que vive num dos dois caminhos de saída não é
uma guarda, e foi medido neste repositório noutro ticket: uma protecção de
privacidade estava dentro do caminho de JSON, e o caminho de texto — que era o de
**omissão** — não corria guarda nenhuma. O ensaio `test_o_funil_e_um_so` conta,
na árvore sintáctica do `cli.py`, as chamadas a `pode_enviar` e exige **uma**.

A omissão de `--classe` é `synthetic`, que é a do compose de produção
(`KAMBA_DATA_CLASS: ${KAMBA_DATA_CLASS:-synthetic}`): a omissão de um comando de
backup não pode ser «trata isto como dados reais».

## O que este *lint* **não** faz

Não corre `pgbackrest check` nem `pgbackrest info`. Não há pgBackRest instalado,
não há `repo1` decidido (D1/KAM-105) e não há produção. Correr um `check` contra
um repositório inexistente devolveria um erro de ligação, e registar isso como
«verificado» era pior do que não verificar — as duas caixas que pedem aqueles
comandos ficam **vazias**, com o credor.

Não está ligado a nenhum portão: ligar uma verificação que trava fusões é
alteração de regra de bloqueio, e isso é decisão do fundador. A `docstring` do
`cli.py` escreve os dois caminhos — um *job* novo no `ci.yaml` cria um contexto
exigido, e entrar num alvo `ci-*` existente muda o **critério** de um portão que
já bloqueia. A suite `tests/` corre no *gate* 4 como as outras de `tools/`, porque
esse portão é sobre testes e não sobre esta configuração.
