# Contratos de evento — schemas versionados, compatibilidade e gate 7

| Campo | Valor |
|---|---|
| Documento | `docs/contratos.md` |
| Ticket | KAM-007 — Catálogo de eventos: schemas versionados e teste de compatibilidade |
| Estado | 38 contratos v1 em `contratos/eventos/`; gate 7 **activo** (`make ci-7`); tipos TS e modelos Python gerados; emenda 1.11 do dicionário. As caixas marcadas e as vazias estão nomeadas na secção de verificação do bloco |
| Âmbito | O **contrato** de um evento: o que um produtor pode emitir e o que um consumidor pode esperar, e o que impede isso de mudar sem versão. Não o laço de publicação (`docs/eventos.md`) nem o de consumo (`docs/consumo.md`) |
| Fontes | `docs/tecnica/06` §4, §5, §6.6, §7.1, §7.3; `docs/tecnica/01` §6.3, §7.2; `specs/02` §3.5 (emenda 1.11); ADR-009, ADR-010, ADR-013 |

| Aprovação | Nome | Data |
|---|---|---|
| Arquitecto de Plataforma | | |
| Responsável de Segurança | | |

---

## 1. A tese, numa frase

O envelope é fixo e o que varia é o `payload` de cada `tipo`/`versao`; um
contrato em git diz qual é esse payload, e o CI impede que ele mude de forma
que parta quem já o lê.

O que isto substitui está escrito no §6.6 do documento técnico, e vale
repetir porque é uma correcção e não uma preferência: o documento exploratório
11 dizia que os consumidores «ignoram versões desconhecidas». Isso **perde
dados em silêncio** no dia em que o produtor é actualizado primeiro — que é o
dia normal, porque o produtor é quem tem a funcionalidade nova. A regra passou
a ser o contrário: uma versão sem conversor **bloqueia com alerta**.

## 2. Onde vivem, e porquê ali

```
contratos/eventos/<tipo>/v<N>.schema.json    o contrato
contratos/eventos/<tipo>/exemplo.json        um evento mínimo que o satisfaz
```

**O caminho foi uma decisão, e as fontes discordavam.** O bloco do KAM-007 diz
`packages/contracts/eventos/`; o `docs/tecnica/06` §4, o `ci/canon-lint.yaml`,
os blocos do KAM-055 e do KAM-092, o `docs/eventos.md`, o KAM-111 e dois
comentários de migração dizem `contratos/eventos/`. Pela ordem de fontes da
skill o bloco do ticket está acima do documento técnico — mas **dois outros
blocos de ticket, que estão no mesmo nível, dizem o contrário**, e é esse o
desempate: dois contra um dentro do mesmo nível, mais a configuração viva do
gate 3b, que já esperava este caminho sem precisar de alteração.

O segundo argumento é técnico: `contratos/` à cabeça é igualmente alcançável
de TypeScript e de Python, e a descrição do próprio `packages/contracts` diz
«fonte única para TypeScript e Python». Uma pasta dentro de um pacote Node não
é neutra.

Corrigiu-se o bloco do ticket. É um sítio contra oito.

## 3. O que um contrato declara

O **evento inteiro**, e não só o payload: os catorze campos de topo do
envelope, com `tipo` e `versao` fixos por `const`, e um payload fechado por
`additionalProperties: false` nos dois níveis.

Catorze, e não nove: a linha «Envelope» do dicionário listava nove nomes e o
`platform.evt_emitir` constrói catorze, com o `seq` dentro do `agregado`. A
emenda 1.9 deixou a dúvida escrita («9 ou 14, de quem aprova emendas») e a 1.11
fecha-a pelo lado do código, porque não havia escolha: um contrato com
`additionalProperties: false` e nove campos recusava **todos** os envelopes
reais.

### Os payloads são mínimos, e isso é desenho

A regra do §6.6 — campo novo opcional não custa versão, remover ou mudar custa
— faz do mínimo defensável a escolha barata e do excesso a escolha cara.
Projecta-se o que se consegue justificar hoje e cresce-se sem quebrar nada.

Onde o DDL do `docs/tecnica/03` ou do `02` dá o nome, é esse. Onde nenhum
documento especifica nada — o caso de `query.*`, cujo `assistant_queries` não
tem DDL em lado nenhum — fica o que o envelope não traz e mais nada. Cada
payload é *proposta*: o §5 dá produtor, consumidores, agregado, PII e fase, e
**não dá os campos de nenhum**.

### Dinheiro, e a decisão que já estava tomada

`*_minor` inteiro mais `currency`. O bloco do KAM-007 manda escolher entre isso
e `valor_kz` e diz que o §4 «mostra `valor_kz`» — **não mostra**: o §4 usa
`valor_minor` + `currency` nos dois sítios, e a emenda 1.1 do documento regista
a decisão como já feita pelo KAM-111. O dicionário §2 confirma e lista
`valor_kz` como a variante substituída. Não havia nada a decidir; havia a
registar que estava decidido.

## 4. O que impede um contrato de partir

Quatro verificações, em `tools/contract_diff/`, que correm como `make ci-7`.

### 4.1 Compatibilidade

Compara cada contrato com o do ramo principal e classifica cada diferença:

| Diferença | Classe |
|---|---|
| Campo novo **opcional** | aditivo |
| Campo removido, renomeado, com outro tipo | quebrante |
| Campo que passa a obrigatório, ou deixa de o ser | quebrante |
| Valor acrescentado ou removido de um `enum` | quebrante |
| `additionalProperties` aberto ou fechado | quebrante |
| **Qualquer outra coisa** | quebrante |

A última linha é a que importa. **Falha fechada:** uma diferença que o
classificador não saiba ler conta como quebrante. A alternativa — «não sei,
deixa passar» — aprova exactamente as mudanças que ninguém previu, que são as
que precisam de olhos. Um falso quebrante custa uma versão a mais; um falso
aditivo custa consumidores partidos em produção.

E uma que parece contra-intuitiva: **acrescentar um valor a um `enum` é
quebrante**. Um consumidor que trate os valores de forma exaustiva — um
`switch` sem ramo por omissão, uma tabela de conversão — deixa de saber o que
fazer com o valor novo. O §6.6 chama-lhe «mudança de significado»; alargar o
domínio é uma promessa nova, e promessas novas levam versão nova.

Quem quer quebrar escreve `v<N+1>` e deixa o `v<N>` como estava. O `v<N>`
retira-se ≥ 90 dias depois de o último consumidor migrar.

### 4.2 PII

Nenhum nome de campo contém um dos sete do §7.3 — telefone, nome, morada,
texto, email, msisdn, bsuid — e nenhum ficheiro casa um padrão de telefone.

**A «lista aprovada» do §7.3 não existia.** O documento fala dela e nunca a
enumera; nasce em `ci/contratos-allow.yaml`, e nasce **vazia**: nenhum dos 38
contratos precisa de excepção, e uma lista com entradas «por precaução» é uma
lista que ninguém revê.

**Três padrões de telefone, e usa-se o do código.** O §7.3 escreve
`\+?244\d{9}`; o `evt_emitir` e o `pii.ts` implementam `\+?244 ?9[0-9]{8}` e
`"\+[0-9]{9,15}"`. Usam-se os do código, por paridade: um exemplo que este
lint aprovasse e a base recusasse seria um contrato que não se pode emitir. A
divergência fica por fechar — ver §6.

A regra tem **três** implementações independentes: aqui, na bateria do
`packages/contracts` e na do `libs/py-core`. Não é desperdício: o dia em que
uma se desligar, as outras continuam a gritar. E há uma quarta barreira que
não é um lint — nenhum dos sete nomes é canónico no dicionário, pelo que um
contrato que os usasse falharia **também** no gate 3b.

### 4.3 Exemplos

Um exemplo por contrato, validado contra o próprio contrato com o
`jsonschema` 4.26.0 que já estava fixado com hashes.

É a verificação mais barata e a que apanha o erro mais comum: um schema que
ninguém conseguiu satisfazer. Um `required` esquecido, um `const` com o tipo
errado, um `enum` sem o valor que o produtor vai usar — nada disso aparece a
ler o schema, e tudo aparece a tentar escrever um exemplo.

### 4.4 `versao_max` das subscrições

Cada subscrição declara a versão que o seu consumidor sabe ler, e essa versão
tem de existir em contrato.

**Hoje passa sobre zero, e di-lo.** Não há nenhuma subscrição no repositório —
`registry/` tem um `README.md` e os ficheiros nascem com o KAM-038. A
alternativa era passar vacuamente, que é a forma de uma caixa parecer cumprida
sem nada a sustentar, ou inventar a fonte, que é de outro ticket. Faz-se a
terceira: lê `registry/*.yaml` se existirem, imprime **sempre** quantas leu, e
o canário prova com uma subscrição em memória que a verificação morde.

### 4.5 O canário

Oito negativas e quatro positivas que correm em cada execução. Sem ele, um
`return []` em qualquer das quatro verificações passava o CI inteiro a verde.

## 5. Tipos gerados, e o que a validação não faz

`python -m contract_diff gerar` escreve dois ficheiros a partir dos contratos:

```
packages/contracts/src/eventos.gerado.ts          interfaces + catálogo
libs/py-core/src/kamba_core/eventos/contratos.py  TypedDict + catálogo
```

O gate falha se estiverem desactualizados.

**O gerador é nosso**, e tem precedente: o `tools/kamba_yaml.py` recusou o
PyYAML pela mesma razão. O subconjunto de JSON Schema que os contratos usam não
é «o que algum dia venha a aparecer» — é o que este mesmo pacote escreve e o
`canon_lint` verifica, nove palavras-chave. Um gerador de uso geral traria
`oneOf`, `$ref` externos e mais trinta coisas que os contratos não podem ter, e
com elas o SBOM, a licença e a actualização a cada CVE. O custo fica fechado
pelo lado ruidoso: o gerador **recusa** a palavra-chave que não sabe traduzir.

O `validarPayload` de `@kamba/core-ts` corre antes de `evt_emitir` e verifica a
forma que o contrato fecha: tipo conhecido, versão certa, nenhum campo a mais,
nenhum obrigatório em falta.

**Não verifica tipos nem formatos.** Isso é JSON Schema completo em execução, e
é uma dependência que não há. Essa metade é do compilador, pelo tipo gerado: um
`valor_minor: "24500000"` não compila. As duas juntas são a validação; cada uma
sozinha tem um buraco, e os buracos não se sobrepõem. Há um teste que exercita
o limite, para que ele seja uma decisão registada e não uma surpresa de quem
leu o nome da função.

## 6. O que fica por decidir

| # | Decisão | Estado |
|---|---|---|
| 1 | **Três padrões de telefone em três sítios.** O §7.3 escreve `\+?244\d{9}`; o `evt_emitir` e o `pii.ts` implementam `\+?244 ?9[0-9]{8}` e `"\+[0-9]{9,15}"`. São semanticamente diferentes, e o do código tem falsos positivos documentados (`docs/eventos.md` §11, ressalva 11) que fizeram uma transacção de negócio falhar numa medição de carga | Devolvida. Este ticket usa o do código, por paridade com a base; apertar o padrão muda o §6.1 e é alteração ao documento técnico |
| 2 | **Os payloads são *proposta*.** Nenhum documento especifica os campos de 37 dos 38 tipos; derivaram-se do DDL e dos epics | Calibra-se com o primeiro produtor de cada tipo (KAM-038, KAM-041 e seguintes). O §6.6 torna isto barato: um campo que falte acrescenta-se sem versão nova |
| 3 | **`tenant.activated` como gatilho do provisioning.** O dicionário diz `tenant.approved` e nomeia os documentos a corrigir; o `docs/00-KAMBA-documento-mestre.md` continua a usar o outro e **não está** na lista | Resíduo documental, registado. O documento mestre é artefacto compilado e não é fonte |
| 4 | **Os tipos de Fase C e D não têm contrato** — `review.removed`, `placement.impression`, `placement.conversion_proven`, `score.computed`, e os `delivery.*` do `docs/tecnica/07` | Por desenho: o critério 1 pede Fase P. Nascem com os tickets que os emitem |
| 5 | **A parte dos webhooks do gate 7** (contratos da Meta) continua por fazer | É o KAM-024; o alvo `ci-7` diz onde se acrescenta |

## 7. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-007): 38 contratos v1, o classificador de diferenças com falha fechada, o *lint* de PII com a lista aprovada que o §7.3 nomeava e nunca enumerou, os exemplos validados, a `versao_max` das subscrições, os tipos gerados e o gate 7 activo. Fecha as decisões abertas 1 e 6 de `docs/eventos.md` e a dúvida «9 ou 14» da emenda 1.9. | Equipa KAMBÁ |
