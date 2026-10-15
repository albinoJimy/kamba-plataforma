# Armazenamento de objectos — a porta `StorageProvider`

| Campo | Valor |
|---|---|
| Ticket | KAM-011 — StorageProvider S3-compatível (SeaweedFS ou gerido) |
| Decisões | ADR-014 (armazenamento atrás de `StorageProvider`; MinIO excluído), ADR-008 (dados pessoais e Angola), ADR-015 (isolamento de tenant) |
| Decisão aberta | **D6 — SeaweedFS auto-alojado ou S3 gerido. Não está tomada, e este módulo não a toma** |
| Desenho | [`tecnica/08_Seguranca_Conformidade.md`](tecnica/08_Seguranca_Conformidade.md) §3.1, §3.7, §3.8, §7.5 |
| Código | [`packages/core-ts/src/storage/`](../packages/core-ts/src/storage/) e [`libs/py-core/src/kamba_core/storage/`](../libs/py-core/src/kamba_core/storage/) |
| Evidência | [`evidencia/KAM-011-seaweedfs.md`](evidencia/KAM-011-seaweedfs.md) |
| Revisão | [`analises/ANALISE-09-KAM-011-storage-provider.md`](analises/ANALISE-09-KAM-011-storage-provider.md) |
| Estado | *Proposta*: nomes, limites e variáveis por ratificar (dicionário §3.11) |

> **Nada está ratificado.** O tamanho de parte (16 MiB), o tempo limite por
> pedido (120 s), o tecto de listagem (10 000) e a rotação das credenciais (90
> dias) são *proposta*. O tecto de 300 s das URLs assinadas não é: vem de
> `tecnica/08` §3.8.

---

## 1. O que é

Uma porta com seis operações — `put`, `get`, `head`, `signUrl`, `delete`,
`list` — em que **todas levam o tenant de quem chama**, e que fala com qualquer
servidor S3. O *fake* em memória dá a mesma porta aos testes.

```ts
import { criarStorageS3, lerConfig, novaChave } from "@kamba/core-ts/storage";

const storage = criarStorageS3({ config: lerConfig({ ambiente }), secrets });

const ctx = { tenantId };
const key = novaChave(ctx, "audio");
const ref = await storage.put(ctx, key, bytes, {
  contentType: "audio/ogg",
  classe: "audio",
  retainUntil,
});
const url = await storage.signUrl(ctx, ref, { ttlSeconds: 60 });
```

Do lado Python é a mesma coisa com `snake_case` (`kamba_core.storage`,
`sign_url`, `ttl_seconds`, `retain_until`), e síncrona.

O esboço do ticket tem cinco métodos. `head` é o sexto, e foi acrescentado
porque sem ele o critério «cada objecto leva metadados `classe` e
`retain_until`» só se provava do lado de quem os envia — e a purga do KAM-071
precisa de os ler.

---

## 2. Isolamento por tenant

É a camada «Storage» da defesa em camadas (`tecnica/08` §3.1): prefixo
`t/{tenant_id}/` e URLs assinadas curtas.

**A chave diz de quem é o objecto**:

```text
t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}
```

`tenant_id` em UUID canónico minúsculo; `classe` em `snake_case`, 2 a 32
caracteres; ano e mês em UTC; `uuid` aleatório. Nenhum dado pessoal entra numa
chave — nem o contacto, nem a conversa, nem o nome original do ficheiro —
porque uma chave aparece em URLs e em *logs*.

**A porta é uma só classe.** `ArmazenamentoPorTenant` (a *guarda*) embrulha um
*motor* — o S3 ou o de memória — e é a única coisa que fala com ele. O *fake* e
o S3 recusam exactamente as mesmas coisas, pela mesma ordem, porque a recusa
não é deles.

| Operação | Antes de falar com o servidor | Depois |
|---|---|---|
| `put` | contexto, forma da chave, dono da chave, metadados, classe = segmento da chave | — |
| `get`, `head`, `delete`, `signUrl` | contexto, forma, dono | `head`: a classe devolvida é a da chave |
| `list` | contexto; o prefixo começa por `t/{tenant}/`, **com a barra** | **cada** chave devolvida está sob o prefixo pedido |

Quatro coisas que vale a pena saber antes de usar:

- **A validação é por lista fechada de caracteres**, não por lista de
  proibidos. `..`, `//`, `%2f`, espaço, maiúscula e byte nulo não passam porque
  não estão no alfabeto. Uma chave que não precisa de *escaping* em parte
  nenhuma não tem uma segunda leitura que um servidor possa fazer diferente da
  nossa.
- **A ordem das recusas é contexto, forma, dono.** Uma chave de outro tenant dá
  `ChaveForaDoTenantError`, exista ou não o objecto: a mensagem não diz de
  quem é, nem se existe.
- **A listagem confere o que o servidor devolve.** Se vier uma chave fora do
  prefixo pedido — por defeito de paginação, de prefixo ou de *proxy* — a
  listagem **falha inteira**, em vez de devolver «as boas». É a segunda camada
  do X-08, e existe para o dia em que a primeira falhar.
- **Não há modo sem tenant.** Trabalho que atravessa tenants (a purga do
  KAM-071) itera tenants e chama a porta uma vez por cada um.

> **O isolamento é da porta, não do servidor.** Há um par de credenciais S3 por
> ambiente, e quem o tem lê e escreve os objectos de todos os tenants. Um
> serviço que construa um motor à mão, ou que fale com o servidor sem passar
> por aqui, saltou a camada inteira. As fábricas (`criarStorageS3`,
> `criarStorageFake`) devolvem a porta já com a guarda, e os motores não são
> exportados pelo índice do módulo — mas isso é convenção, não mecanismo.
> Credenciais por tenant no servidor não estão no desenho do Piloto.

### X-08 e a suite do KAM-066

O X-08 da matriz (`tecnica/08` §3.7: «A pede URL assinada de objecto de B e
lista prefixos») está na bateria de contrato, e corre sobre os três alvos. A
suite ponta a ponta do KAM-066 ainda não existe; quando existir, o caso
regista-se lá (`registerCase`), como o bloco do KAM-066 pede. O X-07 não é
deste ticket: é um identificador reservado pelo KAM-066.

---

## 3. URLs assinadas

`signUrl` devolve uma URL de leitura (`GET`) que expira. **O TTL é um inteiro
entre 1 e 300 segundos**; fora disso, `TtlInvalidoError`.

Quem tem a URL tem o objecto até ela expirar: uma URL assinada é uma credencial
com prazo. Por isso não se persiste, não se regista, e nenhuma mensagem de erro
deste módulo a contém. O que se persiste é a `ObjectRef`.

As URLs da Meta de onde a média vem **nunca passam por aqui**: o módulo recebe
bytes e devolve referências. Não as persistir é do MED (KAM-020).

---

## 4. Metadados e retenção

Todo o objecto leva `classe` e `retain_until`, obrigatórios na escrita. No
servidor S3 são metadados do utilizador (`classe` e `retain-until`, este com
hífen por ser um cabeçalho HTTP), com o instante em UTC.

**Este módulo só regista o prazo.** Apagar é do KAM-071. E a *lista* de classes
também não é daqui: cada consumidor traz as suas, com a política de retenção
por classe no KAM-071 (o áudio, por exemplo, tem alvo de 24 h e limite de 72 h,
`tecnica/08` §7.5).

> **Uma consequência por decidir.** O critério de aceitação diz «cada objecto
> leva `retain_until`», pelo que o campo é obrigatório — e o esboço do mesmo
> ticket escrevia-o opcional. Um objecto sem prazo legal (uma foto de
> catálogo) tem, hoje, de levar uma data. Que data é uma decisão do consumidor
> ou do KAM-071, não desta porta.

A cifra por objecto com a chave do contacto (`tecnica/06` §7.6) **não está
implementada**: é do KAM-070/KAM-071. O ponto de entrada é o corpo do `put`,
que aceita um fluxo — quem cifra entrega o fluxo já cifrado. A cifra em repouso
é do servidor, e não foi verificada (§7).

---

## 5. Configuração e destino dos dados

| Variável | Obrigatória | O que é |
|---|---|---|
| `KAMBA_STORAGE_ENDPOINT` | sim | origem do servidor: `http(s)://anfitrião[:porta]`, sem caminho nem credenciais |
| `KAMBA_STORAGE_BUCKET` | sim | nome do *bucket* |
| `KAMBA_STORAGE_REGION` | sim | região, para a assinatura |
| `KAMBA_STORAGE_DESTINO_COUNTRY` | sim | país onde os bytes ficam, ISO 3166-1 alfa-2 |
| `KAMBA_STORAGE_DESTINO_PROVIDER` | sim | identificador do fornecedor |
| `KAMBA_STORAGE_DESTINO_APD_REF` | em `prod`, fora de `AO` | referência do procedimento na APD |

Sem `destino.country` ou `destino.provider` **o serviço não arranca**, em
nenhum ambiente. Em `prod`, com `country` diferente de `AO` e sem `apd_ref`,
`lerConfig` lança `DestinoSemApdRefError` — é o «aviso bloqueante no arranque»
do critério de aceitação 7. Em `dev` e `staging` a mesma combinação arranca,
com um aviso em `config.avisos`.

**O ambiente tem de ser exactamente `dev`, `staging` ou `prod`.** Qualquer
outro valor — `PROD`, `production`, vazio — é recusado, e não tratado como
«não é `prod`»: a primeira versão comparava com `"prod"` e deixava a regra
falhar aberta para tudo o resto (`ANALISE-09`, A1).

Os valores lêem-se da mesma maneira dos dois lados, por construção: o
endpoint é conferido por **uma expressão regular igual em TypeScript e em
Python**, sem analisador de URL (os dois analisadores discordam em dezenas de
casos de fronteira), e das pontas de um valor só se tiram espaço, tabulação e
mudança de linha.

O que este módulo **não** faz: não decide se um país é «adequado». Não há lista
pública (`tecnica/08` §8.3.1, NÃO VERIFICADO), e o código não infere adequação
do país. E o país é **declarado**, não verificado: o módulo confia em quem
configura — `AO` com um endpoint noutro continente arranca. A `apd_ref` também
é só uma cadeia com forma: que exista na APD ninguém aqui confere. E não se
exige `https` em `prod`: TLS até ao servidor está por verificar (§7) e por
decidir com o alojamento. O *gate* de transferência por tenant (`tenant_destinations`) é do
KAM-069, que ainda não existe; quando existir, lê `config.destino`.

**As credenciais não são configuração.** Vêm do `SecretProvider` (KAM-010),
pelas referências `storage_access_key_id` e `storage_secret_access_key` de
[`ops/secrets-inventory.yaml`](../ops/secrets-inventory.yaml), e são pedidas em
cada operação: uma rotação no cofre chega aqui sem reiniciar o processo.

---

## 6. O motor S3

Fala o subconjunto da API que a porta precisa — `PUT`, `GET`, `HEAD`,
`DELETE`, envio em partes, `ListObjectsV2` e URL pré-assinada — com assinatura
**SigV4 escrita à mão**, em TypeScript e em Python.

Não se usou o SDK da AWS nem o `boto3`, e vale dizer porquê: os dois pacotes
partilhados não têm dependências de execução, por desenho, e o SDK traria mais
de cem pacotes para fazer cinco pedidos HTTP. O risco de escrever SigV4 à mão é
errar a canonicalização — e por isso a prova de que está certo não é um teste
nosso contra nós próprios, é um servidor real a aceitar os pedidos e a recusar
os de chave errada ([`evidencia/KAM-011-seaweedfs.md`](evidencia/KAM-011-seaweedfs.md) §4).

Limites assumidos:

- **endereçamento por caminho** (`{endpoint}/{bucket}/{chave}`). O estilo
  *virtual-hosted* não está implementado;
- um corpo até 16 MiB vai num pedido; acima disso vai em partes. O objecto não
  é junto em memória, mas **«uma parte de cada vez» seria dizer de mais**: a
  revisão mediu, em Python, cerca de três partes de pico com blocos pequenos,
  e quem entrega o objecto num só bloco tem-no inteiro em memória;
- a *query* vai na rede em RFC 3986, igual dos dois lados;
- sem `aws-chunked`, sem *session tokens*, sem SigV4A;
- um envio em partes que falha é abortado no servidor; o erro que sobe é o
  original.

---

## 7. O que foi verificado, e o que não foi

| Item | Estado | Onde |
|---|---|---|
| A bateria de contrato passa no *fake* e no motor S3 sobre um servidor em memória | CONFIRMADO, em cada PR (*gate* 4) | `packages/core-ts/tests/storage.contrato.test.ts`, `libs/py-core/tests/test_storage_contrato.py` |
| A mesma bateria passa contra SeaweedFS 4.48 | CONFIRMADO por execução, nó único, em `tmpfs` | [`evidencia/KAM-011-seaweedfs.md`](evidencia/KAM-011-seaweedfs.md) |
| O servidor verifica a assinatura (chave errada e pedido anónimo → 403) | CONFIRMADO por execução | idem §4 |
| Envio em partes, expiração de URL | CONFIRMADO por execução | idem §3 |
| *Object lock* (retenção `COMPLIANCE`) | INDÍCIO: uma sonda pela API S3, num nó, sem reinício | idem §3.3 |
| **Qualquer S3 gerido** | **NÃO VERIFICADO** — nenhum foi contactado | — |
| Preços e disponibilidade de S3 gerido para Angola | NÃO VERIFICADO (E4 §2.11) | — |
| Cifra em repouso no servidor | NÃO VERIFICADO | — |
| TLS até ao servidor; nós múltiplos; persistência entre reinícios; carga | NÃO VERIFICADO | — |

Para correr a prova contra um servidor real:

```sh
make storage-contrato        # ou: python infra/storage/contrato.py
```

Levanta um SeaweedFS fixado por *digest*, com os dados em `tmpfs` e credenciais
geradas para essa execução, corre as duas baterias e os testes de capacidade, e
apaga tudo. **Não é um *gate* de CI**: o ticket não pede um, e o *gate* 5
continua reservado. Leva de três a sete minutos, conforme a carga da máquina —
dois deles a esperar que uma URL de 60 s expire a sério.

A prova por mutação dos testes de isolamento e de recusa:

```sh
python infra/storage/mutacoes.py --aplicaveis   # segundos: as mutações ainda se aplicam?
python infra/storage/mutacoes.py                # todas, em cópia fora do repositório
```

---

## 8. O que este módulo deixa em aberto

1. **A D6.** O código não escolhe. O que a escolha precisa de saber e ainda não
   se sabe está em [`evidencia/KAM-011-seaweedfs.md`](evidencia/KAM-011-seaweedfs.md) §6.
2. **O ADR da D6**, que o critério de aceitação 6 pede: não existe, porque a
   decisão não existe.
3. **A forma da chave no KAM-020**, que escreve um segmento `media/` que esta
   forma não tem (dicionário §3.11).
4. **O registo do X-08 na suite do KAM-066**, quando ela existir.
5. **O consumo de `config.destino` pelo KAM-069**, quando ele existir.
6. **Um endereço público para as URLs assinadas.** Há um só `endpoint`: a URL
   assinada aponta para onde o serviço fala com o servidor. Um consumidor fora
   dessa rede precisa de um segundo endereço — e isso depende do alojamento.

---

## 9. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-011): porta, guarda de isolamento, motor S3 e *fake*; configuração com destino; prova contra SeaweedFS 4.48. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Depois da revisão adversarial ([`ANALISE-09`](analises/ANALISE-09-KAM-011-storage-provider.md)): ambiente fora do domínio recusado (§5); o que o país e a `apd_ref` **não** garantem (§5); memória do envio em partes dita como foi medida (§6). | Equipa KAMBÁ |
