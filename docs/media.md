# MED — mídia recebida: descarga, armazenamento e URL interna

> Entregue pelo KAM-020. O bloco do ticket está em
> [`../specs/EPIC-02_Canais_WhatsApp_Handoff.md`](../specs/EPIC-02_Canais_WhatsApp_Handoff.md)
> e os nomes estão no §3.16 do
> [dicionário](../specs/02_Dicionario_de_Dados_Canonico.md) (emenda 1.24).

## 1. O que o MED é, em duas frases

Áudio, imagens e documentos chegam por `media_id` — um identificador, não um
ficheiro — e o MED é quem os vai buscar, valida, guarda no `StorageProvider`
(ADR-014) e registra. Serve o STT (KAM-036), o Catálogo AI (KAM-049), o KYC
(KAM-087) e o espelho para o Chatwoot (KAM-019), e nenhum deles vê o URL da
Meta nem a chave do objecto: vêem `media://{assetId}`.

## 2. O que o MED não pode fazer, e é por construção

**Uma imagem pode ser um comprovativo de pagamento e nunca é prova** (ADR-013).
Um cliente manda a fotografia de um depósito e o pagamento só muda de estado por
um evento autenticado do banco ou do facilitador — não por alguém, ou algum
modelo, ter olhado para a imagem.

O critério 8 pede «0 caminhos de código que alterem estado de pagamento a partir
de uma imagem», e a forma de o cumprir não é disciplina: é **não haver a
importação**. O `med.arquitectura.test.ts` lê a fonte e está escrito ao
contrário — enumera as importações que o MED tem e exige que cada uma esteja
numa lista de permissão com razão escrita. Uma lista de bloqueio passaria hoje
por o `pay/` ainda não existir, e isso não é uma garantia: é um acaso com data
de validade.

## 3. A tabela não tem o conteúdo, tem a chave dele

A `media_assets` é a primeira tabela do projecto cujo conteúdo **não está nela**.
O que ela guarda é onde o objecto está, o que é preciso para saber se já foi
tratado, e quando deve desaparecer.

| Coluna | O que é |
|---|---|
| `asset_id` | A chave, `uuid` gerado. É o que vai em `media://{assetId}` |
| `tenant_id`, `contact_id`, `conversation_id` | De quem, e de que conversa. As duas últimas por FK **composta** |
| `wamid`, `media_id` | A origem: a mensagem e o objecto do lado da Meta |
| `classe` | `media_audio`, `media_imagem` ou `media_documento` |
| `content_type`, `size`, `sha256` | O que a **descarga** descobriu. Anuláveis até ela acontecer |
| `storage_ref` | A `ObjectKey` do KAM-011 |
| `estado` | `pendente`, `armazenado`, `rejeitado` ou `falhou` |
| `retain_until` | Quando o blob deve desaparecer. A purga é KAM-071 |
| `criado_at` | A convenção de todas as tabelas do §3 |

**Catorze colunas e não as onze do critério 1**, e as três a mais vêm do próprio
ticket: o `media_id`, porque o critério **2** pede a unicidade de
`(tenant_id, wamid, media_id)` e o critério 1 não o lista — a contagem de um não
fecha com a do outro; o `asset_id`, porque o critério 5 emite
`media://{asset_id}` e não havia chave de onde o tirar; e o `criado_at`.

### Nenhum URL da Meta cabe aqui

E não é por omissão: **não há coluna onde ele caiba.** O que se guarda é o
`media_id` (um identificador) e o `storage_ref` (a chave do nosso objecto). O
critério 3 pede um teste que percorra as tabelas à procura de padrões do domínio
da Meta, e a ausência de coluna é o que o faz passar **por construção** e não
por disciplina. O `media.bd.test.ts` percorre a tabela inteira convertida a
texto, coluna a coluna, e exige que não haja lá `http` nenhum.

## 4. A idempotência é da base, e não deixa órfãos

A `media_assets_origem_uq (tenant_id, wamid, media_id)` é o que torna o critério
2 uma propriedade da base. **Três colunas e não uma:** o `wamid` sozinho não
chega, porque uma mensagem pode trazer mais do que um objecto; o `media_id`
sozinho também não, porque é do lado da Meta e nada nos garante que não se repita
entre mensagens.

**E a linha escreve-se ANTES de falar com a Meta.** Os três valores da chave vêm
todos da mensagem, pelo que a linha se pode escrever sem gastar uma chamada: o
segundo chamador perde o `ON CONFLICT` e **não descarrega**.

> É o contrário do `ensureAccount` do HND (KAM-019), que precisava de
> identificadores que só a criação no provedor devolve — e que por isso deixa
> recurso **órfão** numa corrida, contado e registado porque não há como o
> evitar. Aqui não há órfão possível: o pior que sobra é uma linha em `pendente`,
> que é nossa e que a purga do KAM-071 vê.

É o `pendente` que o consegue, e ele **não está no ticket**: o critério nomeia
`rejeitado` e `falhou`, e este valor entrou porque sem ele a reserva não podia
existir.

### A assimetria com a `0011`, e é deliberada

A `handoff_accounts_conta_uq` recusa a mesma conta do provedor em dois *tenants*;
a `media_assets_origem_uq` **aceita** o mesmo `(wamid, media_id)`. A diferença
não é descuido:

- uma **conta** no provedor é um recurso compartilhável por erro, e dois
  *tenants* a apontar para ela era uma PME a ler as conversas da outra;
- um **`wamid`** é emitido pela Meta por mensagem, e duas PMEs com o mesmo valor
  é uma colisão do lado dela — recusar a segunda fazia a nossa base perder uma
  mensagem por um defeito que não é nosso.

Há um teste para cada sentido, e o do «aceite» existe para que apertar a
unicidade **falhe ali**, em vez de perder mensagens em produção.

## 5. A ordem dos sete passos

```text
1. traduz o `wa_type` em classe          — sem classe, nada do resto faz sentido
2. RESERVA a linha em `pendente`         — e é aqui que a idempotência acontece
3. resolve o `media_id` num URL          — a Meta, primeira de duas chamadas
4. descarrega os bytes                   — a Meta, e é a que pode falhar
5. corre a *allowlist* no tipo REAL      — e não no anunciado
6. `put` no armazenamento                — o objecto, com a chave do tenant
7. marca `armazenado` com o que se soube — content_type, size, sha256, ref
```

**O passo 5 corre no tipo da resposta.** Um `image/png` que o webhook anuncia e
que chega como outra coisa é exactamente o caso que a *allowlist* existe para
apanhar; o anúncio serve só para recusar cedo e poupar a descarga.

**O passo 6 vem antes do 7.** Se o `put` falhar, não há `storage_ref` e a linha
fica em `pendente` — recuperável. Ao contrário, a linha dizia `armazenado` e
apontava para um objecto que não existe, e o consumidor pedia `signUrl` de nada.
A `media_assets_armazenado_ck` impede essa linha de existir, mas a ordem é o que
impede a tentativa.

## 6. A *allowlist*, e os números que são *proposta*

| Classe | Tipos | Máximo |
|---|---|---|
| `media_audio` | `audio/ogg`, `audio/ogg; codecs=opus`, `audio/opus` | 16 MiB |
| `media_imagem` | `image/jpeg`, `image/png`, `image/webp` | 5 MiB |
| `media_documento` | `application/pdf` | 20 MiB |

**Os números todos aqui são *proposta*, e a razão não é cautela: a API de mídia
da Meta não tem evidência nenhuma.** O
[`E1`](tecnica/evidencia/E1_Meta_WhatsApp.md) não tem a página de referência e
**nem a lista como omissão** — não há limite de tamanho por tipo, nem tempo de
expiração do URL, nem o fluxo de duas etapas confirmado, nem os códigos de erro.

**Onde calibram:** no primeiro contacto com a API real, que é `ext:KAM-101`
(perguntas escritas à Meta) e `ext:KAM-102` (App Review). Até lá, um limite nosso
mais apertado do que o dela é inofensivo — recusa cedo o que ela recusaria tarde;
um mais largo é que faz uma descarga morrer a meio depois de gastar banda. E vão
em **configuração** e não num literal, pela razão que o KAM-015 escreveu para a
versão da Graph.

**Só PDF em documentos**, e a estreiteza é a defesa: a análise de malware e de
conteúdo activo «não consta de `docs/tecnica/`» (bloco do ticket) e fica para o
modelo de ameaças (KAM-065). Aceitar `.docx` era aceitar macros sem ter quem as
inspeccione.

### O `sticker` é imagem

Do ponto de vista do armazenamento e da retenção, um *sticker* é uma imagem. Uma
quarta classe multiplicava a política de retenção do KAM-071 sem mudar nada, e a
lista de classes é do **primeiro consumidor** — o §3.11 di-lo por escrito.

### Rejeitado e falhou são dois estados

E a diferença é operacional: um `rejeitado` (tipo ou tamanho) pede ao cliente
outro formato e nunca melhora sozinho; um `falhou` (três tentativas sem sucesso)
é do nosso lado ou do da Meta e pode ser retomado. Juntá-los fazia o painel
mandar a PME pedir outro ficheiro quando o problema era nosso.

## 7. O URL interno, e o X-08

O TTL é o `TTL_MAXIMO_S` da porta do KAM-011, que é **300 s** — o mesmo número
que o critério 5 pede («≤ 300 s») e que o `tecnica/08` §3.8 fixa («TTL ≤ 5
min»). **Não se escreve 300 no MED**: lê-se de lá, para que mudar o limite seja
um sítio e não dois.

**E o X-08 não é uma verificação nossa.** A chave leva o *tenant* no primeiro
segmento e é a porta que levanta `ChaveForaDoTenantError` ao assinar uma chave
fora do *tenant* do `ctx`. Isso é mais forte do que um `if` nosso, porque a porta
tem bateria de contrato própria que corre contra **três** alvos, incluindo um
SeaweedFS real.

São duas fechaduras e as duas contam: a RLS não deixa **ler** a linha de outro
*tenant*, e se deixasse a porta não a assinaria. Há um teste para cada uma.

## 8. A retenção do áudio conta da criação

O critério 7 diz «`retain_until` = criação + 24 h» e o `tecnica/08` §7.5 diz
«apagar o blob após sucesso (alvo ≤ 24 h; limite de erro 72 h)». **Fica a do
critério, e é a única leitura auto-consistente:** contar da transcrição faz o
prazo **nunca chegar** quando a transcrição nunca tem sucesso — que é
precisamente o caso em que o áudio não devia ficar.

**Uma imagem não leva prazo curto.** «Fotos de produto vivem enquanto o catálogo
viver», diz o bloco; inventar aqui um prazo era apagá-las sem ninguém decidir. A
política de retenção por classe é do KAM-071.

O gancho `onTranscribed(asset)` **agenda** e não apaga: a purga é KAM-071. O que
o MED promete é que o gancho corre com a chave certa — sem ela, quem purga não
sabe o que apagar.

## 9. As três métricas, e o que a do tempo não dá

| Métrica | Tipo | Etiqueta |
|---|---|---|
| `media_bytes_total` | *counter* | `classe` (três valores) |
| `media_rejected_total` | *counter* | `motivo` (lista fechada de três) |
| `media_download_ms` | *gauge* | nenhuma |

**Nenhuma leva identificadores.** A gramática de uma etiqueta é
`^[a-z][a-z0-9_]{1,62}$`, mas a razão não é a gramática: é a cardinalidade. O
`OBS-I` de [`seguranca/ameacas_stride.md`](seguranca/ameacas_stride.md)
proíbe-o, e um contador por *tenant* multiplica as séries pelo número de PMEs. E
a `media_bytes_total` leva a **classe** e não o `content_type`: três valores
contra uma lista que cresce sempre que a *allowlist* cresce.

**A `media_download_ms` não dá percentis.** É um *gauge* com o último valor, pela
mesma razão que o `gwy_enqueue_ms` do GWY escreveu: o formato de exposição do
Prometheus tem histogramas e estas bibliotecas não os implementam (ADR-018,
observabilidade leve no Piloto). O sufixo `_ms` do nome que o ticket fixa convida
a ler isto como uma distribuição, e **não é**. A agregação contínua é KAM-080.

**E mede-se mesmo quando a descarga falha**, de propósito: uma descarga que
demora e falha é o sinal mais útil que esta métrica dá, e medir só os sucessos
fazia um painel verde num dia em que nada chegou.

## 10. Como correr

Nesta máquina não há `make`, `node` nem `pnpm` no `PATH`.

```bash
# As três baterias do gate 4 (funções puras, a fonte e as portas)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/repo" -w /repo/packages/core-ts \
  node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66 \
  sh -c 'node --test tests/med.*.test.ts'
```

```bash
# O gate 8: as três baterias **e** o ensaio de base, com a cobertura
.venv/Scripts/python.exe db/gate_bd.py --suite tests_media
```

```bash
# O esquema e o downgrade da 0012
.venv/Scripts/python.exe db/gate_bd.py --suite tests
```

## 11. O que não está aqui, e tem dono

| O que falta | De quem é |
|---|---|
| A transcrição do áudio (STT) | KAM-036 |
| A leitura das imagens (Catálogo AI) | KAM-049 |
| O KYC a partir de documentos | KAM-087 |
| **A purga do blob**, e a política de retenção por classe | KAM-071 |
| O *crypto-shredding* por DEK de contacto | KAM-070/071 |
| A análise de malware e de conteúdo activo | KAM-065 (modelo de ameaças) |
| A remoção de EXIF/GPS | **sem dono**: o `tecnica/03` §8.2 atribui-a ao MED, o bloco do KAM-020 não a menciona, e o KAM-049 repete-a. Registado nas dívidas |
| O consumidor da fila que entrega ao Chatwoot | KAM-025 |
| O registo `X-08` em código (`registerCase`) | KAM-066 |
| **Os números da *allowlist*** | `ext:KAM-101` e `ext:KAM-102` — a API da Meta |

## 12. Controlo de versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-10-21 | Criado pelo KAM-020. |
