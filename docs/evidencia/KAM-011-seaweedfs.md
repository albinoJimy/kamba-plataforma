# Evidência — KAM-011: `StorageProvider` contra SeaweedFS 4.48

| Campo | Valor |
|---|---|
| Ticket | KAM-011 — StorageProvider S3-compatível (SeaweedFS ou gerido) |
| Ramo | `feature/KAM-011-storage-provider`, a partir de `main` (`edc9773`) |
| Código medido | *commit* `25f8d14` (depois das correcções da revisão adversarial e da integração do KAM-067) |
| Data | 2026-10-12 |
| Máquina | Windows 11; Docker 29.7.2 (`linux/amd64`); Python 3.13.15 no *host*; Node 24.21.0 em contentor (`node:24.21.0-trixie-slim`), porque não há Node no *host* |

Este ficheiro guarda **o que foi medido**, com o comando e o número. O que aqui
está é um **dado para a decisão D6** — SeaweedFS auto-alojado ou S3 gerido — e
**não é a decisão**: a D6 está aberta e depende do alojamento, D1
(`../tecnica/00_Arquitectura_Solucao.md` §13.3). O §6 diz o que a decisão
precisa de saber e ainda ninguém sabe.

---

## 1. Como se reproduz

```sh
python infra/storage/contrato.py        # ou: make storage-contrato
```

O orquestrador gera um par de credenciais, escolhe uma porta livre em
`127.0.0.1`, levanta `infra/compose/docker-compose.storage.yml`, espera que o
gateway S3 aceite um pedido assinado, corre as suites e apaga o contentor.

Saída da execução de 2026-10-12 sobre o código final (resumo; as linhas `✔` e
`... ok` de cada caso foram omitidas). É a terceira execução completa: a
primeira foi sobre `e5b6e40`, antes da revisão; a segunda foi a do revisor,
sobre `6e89c82`. As três deram o mesmo resultado.

```text
==> SeaweedFS descartavel em http://127.0.0.1:<porta> (projecto kamba-storage-contrato-31696)
 Container kamba-storage-contrato-31696-seaweedfs-1 Healthy

==> Python escreve o objecto de interoperabilidade
Ran 1 test in 1.602s
OK

==> suite TypeScript: bateria de contrato e testes de capacidade
ℹ CAPACIDADE multipart: sim (1 abertura, 2 partes, 1 fecho; sha256 idêntico)
ℹ   object lock — criar bucket com object lock: HTTP 200
ℹ   object lock — PUT com retenção COMPLIANCE: HTTP 200
ℹ   object lock — x-amz-version-id devolvido: sim
ℹ   object lock — GET ?retention: HTTP 200, modo COMPLIANCE
ℹ   object lock — DELETE da versão retida: HTTP 403
ℹ   object lock — GET da versão depois do DELETE: HTTP 200
ℹ CAPACIDADE object lock: sim
ℹ tests 20
ℹ pass 20
ℹ fail 0
ℹ skipped 0
ℹ duration_ms 301019.067452

==> suite Python: bateria de contrato
Ran 17 tests in 110.473s
OK

==> resultado
    verde    interoperabilidade: Python escreve
    verde    suite TypeScript
    verde    suite Python

storage-contrato: verde.
```

O caminho até ao servidor é o de produção: `lerConfig` lê as variáveis
`KAMBA_STORAGE_*`, as credenciais vêm do `EnvSecretProvider` do KAM-010, e o
transporte é o `fetch` do Node e o `http.client` do Python.

---

## 2. A imagem e a licença

| O que | Valor | Como se obteve |
|---|---|---|
| Imagem | `chrislusf/seaweedfs:4.48` | `docker pull`, 2026-10-12 |
| *Digest* | `sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d` | `docker image inspect --format '{{json .RepoDigests}}'` |
| Versão do binário | `version 30GB 4.48 530be3e37 linux amd64` | `weed version`, dentro da imagem |
| Data da imagem | 2026-09-28 (coincide com a data de *release* de E4 §2.11) | `docker image inspect --format '{{.Created}}'` |
| Rótulos | `org.opencontainers.image.version=4.48`, `…revision=530be3e37337488ecc34d58441e0bc476e121c93`, `…source=https://github.com/seaweedfs/seaweedfs`, `…licenses=Apache-2.0` | `docker image inspect --format '{{json .Config.Labels}}'` |

**Licença: Apache-2.0 — CONFIRMADO**, em fonte primária, a 2026-10-12:

```sh
curl -s https://raw.githubusercontent.com/seaweedfs/seaweedfs/4.48/LICENSE | head -3
#                                  Apache License
#                            Version 2.0, January 2004
#                         http://www.apache.org/licenses/
curl -s https://raw.githubusercontent.com/seaweedfs/seaweedfs/4.48/LICENSE | sha256sum
# d789d433cc11da163273d1e39be2e8fa67642f9a58ef220d3f258fa9c14ef613
```

HTTP 200 na etiqueta `4.48` do repositório que o rótulo da imagem nomeia. A
imagem está fixada por *digest* em
`../../infra/compose/docker-compose.storage.yml`, e `Apache-2.0` está na lista
de licenças permitidas (`../../ci/licenses.yaml`). Desde que o KAM-067 entrou
em `main`, a imagem está também no inventário
(`../../ci/supply-chain/imagens.yaml`, com o *digest* do índice lido por
`docker buildx imagetools inspect` — o mesmo) e o `make supply-chain` confere-o
em cada PR. **Estar no inventário não é a decisão D6**: é o registo do
*digest* de uma imagem que o repositório referencia, e só para testes.

Três coisas que esta verificação **não** cobre, ditas para não se ler mais do
que está escrito:

- **As dependências embutidas no binário.** Verificou-se a licença do projecto,
  não a de cada módulo Go compilado lá dentro. O SBOM por imagem é do KAM-067.
- **A assinatura da imagem.** Não se verificou `cosign` nem proveniência (no
  inventário está `por_apurar`); o
  *digest* garante que é sempre a mesma imagem, não quem a construiu. Também
  KAM-067.
- **A edição.** O `weed version` anuncia uma «SeaweedFS Enterprise Edition»,
  comercial, com funcionalidades que a edição aberta não tem. A imagem usada é
  a aberta. Que funcionalidades ficam só na comercial, e se alguma delas faz
  falta em produção, **não foi verificado** — e é um dado para a D6.

**MinIO ausente.** `tools/blocklist.yaml` recusa-o (ADR-014) e o `lint_arch`
passa: `python -m lint_arch --root . all` → «lista de bloqueio: conforme». Um
`git grep -il minio` sobre `infra/`, `packages/`, `libs/` e `services/` só
devolve o comentário do próprio compose de armazenamento, que diz que está
excluído.

O contentor corre como o utilizador `seaweed` (uid 1000), com sistema de
ficheiros só de leitura, `cap_drop: ALL` e `no-new-privileges`, publica a porta S3 só em `127.0.0.1` e guarda os dados em
`tmpfs`. As credenciais chegam por `AWS_ACCESS_KEY_ID` e
`AWS_SECRET_ACCESS_KEY`, geradas em cada execução; com elas definidas o gateway
**exige** assinatura (§4).

---

## 3. Os três testes de capacidade

O critério de aceitação 5 pede três, e são os três itens que o contexto do
ticket marcava NÃO VERIFICADO.

### 3.1 Envio em partes (*multipart*) — **sim**

Caso `CAPACIDADE multipart: 25 MB vão em partes e voltam iguais`. Um objecto de
25 MiB (26 214 400 bytes aleatórios), com partes de 16 MiB:

| Medida | Valor |
|---|---|
| `POST ?uploads` | 1 |
| `PUT ?partNumber=…&uploadId=…` | 2 |
| `POST ?uploadId=…` (fecho) | 1 |
| Tamanho lido de volta | 26 214 400 bytes |
| SHA-256 do que voltou | idêntico ao do que foi |
| Metadados depois do envio em partes | `classe` lida por `head`: `audio` |

Os pedidos são contados por um transporte espião à volta do `fetch`, não
inferidos. A bateria de contrato repete a ida e volta de 1 KB, 10 MB e 25 MB,
nas duas linguagens.

### 3.2 URL assinada com expiração — **sim**

Caso `uma URL com TTL de 60 s devolve 200 antes e 403 depois de 65 s`, da
bateria comum. Contra o servidor real o relógio **não** é injectado: a suite
espera 65 segundos a sério (o caso levou 65 462 ms em TypeScript), e quem
recusa a URL é o servidor.

| Momento | `GET` anónimo da URL |
|---|---|
| logo após assinar | 200, com o conteúdo (SHA-256 idêntico) |
| 65 s depois | 403 |

Mais dois casos sobre a mesma capacidade: uma URL assinada para um objecto,
com a chave trocada pela de outro, dá 403; e uma URL assinada com a chave
secreta errada dá 403.

### 3.3 *Object lock* — **sim, pela API S3, com reservas**

Caso `CAPACIDADE object lock: sim ou não`. É uma sonda, não um requisito:
regista o que o servidor faz.

| Passo | Resposta |
|---|---|
| criar *bucket* com `x-amz-bucket-object-lock-enabled: true` | 200 |
| `PUT` com `x-amz-object-lock-mode: COMPLIANCE` e retenção de 1 h | 200, com `x-amz-version-id` |
| `GET ?retention` | 200, `<Mode>COMPLIANCE</Mode>` |
| `DELETE ?versionId=…` da versão retida | **403** |
| `GET ?versionId=…` depois da tentativa | 200 (o objecto continua lá) |

**Estado: INDÍCIO, não CONFIRMADO.** O que a sonda prova é que, pela API S3,
num nó, segundos depois da escrita, a versão retida não se apaga. O que
**não** prova, e que WORM a sério exigiria:

- que a retenção sobrevive a um reinício do servidor (os dados estavam em
  `tmpfs`);
- que não se contorna **por fora da API S3** — o SeaweedFS expõe também o
  *filer* e os volumes, e nenhum deles foi atacado;
- o modo `GOVERNANCE`, o *legal hold*, e o que acontece quando a retenção
  expira;
- o comportamento com mais de um nó.

WORM continua fora do âmbito deste ticket e do Piloto (`../tecnica/08` §6: só
em Clusters). A frase «NÃO VERIFICADO para SeaweedFS» desse documento deixa de
ser inteiramente verdade e passa a ser «INDÍCIO»; a emenda está registada em
`../dividas-documentais.md`.

---

## 4. A assinatura é mesmo verificada

Sem isto, tudo o resto provava pouco: uma bateria que passa contra um servidor
que aceita qualquer pedido não diz nada sobre o SigV4 escrito à mão.

Caso `a assinatura é verificada: chave errada e pedido anónimo são recusados`,
nas duas linguagens:

| Pedido | Resposta |
|---|---|
| `put` com a chave secreta errada | 403 |
| `get` com a chave secreta errada | 403 |
| URL assinada com a chave secreta errada | 403 |
| `GET` anónimo do objecto | 403 |
| `GET` anónimo da listagem do *bucket* | 403 |
| os mesmos pedidos com a chave certa | 200 (a bateria inteira) |

E as duas implementações assinam igual: dois vectores fixos — um pedido por
cabeçalho e uma URL pré-assinada — dão o mesmo valor em
`packages/core-ts/tests/storage.s3.test.ts` e em
`libs/py-core/tests/test_storage_s3.py`.

**Interoperabilidade.** O Python escreve um objecto, o TypeScript lê-o com os
metadados (`classe`, `retain_until`) e escreve outro, que o Python lê. Os dois
sentidos passam.

---

## 5. A bateria de contrato

A mesma bateria — 15 casos, escritos uma vez por linguagem — corre sobre três
alvos:

| Alvo | TypeScript | Python | Onde corre |
|---|---|---|---|
| *fake* em memória | 15 / 15 | 15 / 15 | *gate* 4, em cada PR |
| motor S3 sobre um servidor S3 em memória | 15 / 15 | 15 / 15 | *gate* 4, em cada PR |
| motor S3 contra SeaweedFS 4.48 | 15 / 15 | 15 / 15 | `make storage-contrato`, à mão |

Contra o servidor real, a suite TypeScript tem mais cinco casos (preparação do
*bucket*, assinatura, interoperabilidade e as duas sondas de capacidade), e a
Python mais dois (assinatura e leitura de interoperabilidade): **20 e 17**.

Os 15 casos: ida e volta de 1 KB, 10 MB e 25 MB com soma idêntica; corpo em
fluxo; objecto vazio; metadados lidos do servidor; recusa de TTL acima de
300 s; expiração de uma URL de 60 s; URL com a chave trocada; `delete`
idempotente; `list` por prefixo; `list` que não corta em silêncio; X-08 (A
contra B: `get`, `head`, `signUrl`, `delete`, `list`); escrita no prefixo de
outro tenant; operação sem contexto.

> **O segundo alvo não é a prova de que o motor fala S3.** O servidor em
> memória foi escrito por quem escreveu o motor, e confere as assinaturas com a
> mesma função que as produz: apanha um cabeçalho por assinar ou uma URL
> adulterada, e não apanha um erro de canonicalização que os dois lados
> partilhem. Existe para o código do motor ser exercitado em cada PR. A prova é
> o terceiro alvo.

---

## 6. O que a D6 precisa de saber

O critério de aceitação 6 pede a decisão escrita num ADR, com quatro critérios.
A decisão **não foi tomada** — não é deste ticket tomá-la. Fica o que cada
critério tem hoje:

| Critério | O que se sabe | Estado |
|---|---|---|
| Resultado dos 3 testes | SeaweedFS 4.48: *multipart* sim, URL com expiração sim, *object lock* sim pela API S3 (§3) | CONFIRMADO os dois primeiros; INDÍCIO o terceiro; nó único, `tmpfs` |
| Os mesmos testes num S3 gerido | Nenhum foi contactado. O motor só faz endereçamento por caminho; um fornecedor que exija *virtual-hosted* precisa de código novo | **NÃO VERIFICADO** |
| Custo cotado | Não há cotação, nem de S3 gerido acessível em Angola, nem do disco e da operação de um SeaweedFS (E4 §2.11; `../tecnica/09` §19) | **NÃO VERIFICADO** |
| Local de alojamento (D1) | D1 aberta | **por decidir** |
| `destino.country` | O código exige-o e, em `prod`, recusa arrancar fora de `AO` sem `apd_ref`. Que valor terá depende de D1 e da escolha | **por decidir** |

E o que a escolha deveria pesar e este ticket não mediu:

- **operar** um SeaweedFS: cópias de segurança, restauro, actualizações,
  monitorização, e o que acontece quando o disco enche — nada disto foi
  ensaiado;
- **cifra em repouso**: o servidor tem a opção `-s3.encryptVolumeData`; não foi
  ligada nem testada;
- **TLS** até ao servidor: os testes correram em HTTP, em `127.0.0.1`;
- **a edição comercial** do SeaweedFS e o que ela reserva (§2);
- **desempenho e limites**: tamanho máximo de objecto, concorrência, latência a
  partir de Luanda.

---

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-011): imagem e licença, três testes de capacidade, bateria de contrato, e o que a D6 ainda não sabe. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Execução repetida sobre o código final, depois da revisão adversarial e da integração do KAM-067 (sistema de ficheiros só de leitura; imagem no inventário da cadeia de abastecimento). | Equipa KAMBÁ |
