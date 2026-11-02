# Logs sem conteúdo — política, *logger* e verificações

| Campo | Valor |
|---|---|
| Ticket | KAM-068 — Política de logs sem conteúdo e redacção de PII |
| Fonte normativa | [`docs/tecnica/08_Seguranca_Conformidade.md`](tecnica/08_Seguranca_Conformidade.md) §7.3 (a *allowlist*), §11 (retenção) e §14 (o alvo); ADR-010 e ADR-018 em [`docs/tecnica/00_Arquitectura_Solucao.md`](tecnica/00_Arquitectura_Solucao.md) §8 |
| Código | [`libs/py-core/src/kamba_core/logger/`](../libs/py-core/src/kamba_core/logger/) e [`packages/core-ts/src/logger/`](../packages/core-ts/src/logger/) |
| Verificações | [`tools/log_policy/`](../tools/log_policy/) — *lint* no *gate* 2, X-11 no *gate* 6 |
| Estado | Em vigor no repositório. **Nada está ratificado**: as formas dos valores, o comprimento do prefixo do HMAC e o identificador opaco são *proposta* deste ticket |

> **O que este documento é.** A política («o que pode ir para um *log*»), o
> processo («como se acrescenta um campo») e os limites («o que isto não
> apanha»). O que não está aqui e está no código não é política: é
> implementação, e pode mudar sem PR a este ficheiro.

---

## 1. O princípio

Os *logs* são o sítio mais provável de uma fuga de dados pessoais: toda a equipa
os lê, ficam trinta dias guardados, e ninguém os desenha — acumulam-se, uma
linha de depuração de cada vez. O ADR-010 responde com uma regra curta: **logs
sem conteúdo**. Não «logs com o conteúdo mascarado»: sem.

Daí as três decisões que explicam o resto:

1. **Lista de campos fechada.** Uma linha de *log* tem doze campos possíveis, os
   de `docs/tecnica/08` §7.3, e mais nenhum.
2. **Não há campo de texto.** Nenhum dos doze é «mensagem». Um erro regista-se
   por código e classe, nunca pela frase que a biblioteca escreveu — que é onde
   vem o que a fez falhar.
3. **Não há redacção parcial.** Um valor tem a forma fechada do seu campo, ou o
   campo é retirado da linha. Não existe «o telefone com asteriscos»: um
   redactor que tenta adivinhar o que é sensível dentro de um texto falha no
   caso que ninguém previu, e um campo que não existe não falha.

O que se perde é conveniência de depuração, e é de propósito. Quem precisa do
conteúdo para depurar tem os traces de LLM em `staging`, com dados sintéticos
(§9).

---

## 2. A *allowlist* e a forma de cada campo

A lista é **exactamente** a de `docs/tecnica/08` §7.3. As formas da terceira
coluna são *proposta* deste ticket: o documento-fonte dá os nomes e não diz o
que cada um aceita.

| Campo | Quem o preenche | Forma aceite | Exemplo |
|---|---|---|---|
| `ts` | o *logger* | UTC, milissegundos, sufixo `Z` | `2026-10-12T08:30:15.123Z` |
| `level` | o *logger* | `debug`, `info`, `warn`, `error` | `info` |
| `svc` | o *logger* (dado uma vez, ao criá-lo) | minúsculas, dígitos e hífenes; até 32 | `worker-canal` |
| `tenant_id` | quem chama | UUID canónico (sai em minúsculas) | `0b6f1d2e-3c4a-…` |
| `contact_hmac_prefix` | quem chama | exactamente 8 hexadecimais minúsculos | `a1b2c3d4` |
| `turn_id`, `msg_id` | quem chama | UUID canónico, **ou** o resultado de `id_opaco` (`m_` + 32 hexadecimais) | `m_55dc0348…` |
| `wa_type` | quem chama | identificador (ver abaixo); até 32 | `interactive` |
| `latency_ms` | quem chama | inteiro de 0 a 99 999 999 | `42` |
| `tool` | quem chama | identificador; até 64 | `criar_pedido` |
| `outcome` | quem chama | identificador; até 64 | `recusado` |
| `error_code` | quem chama | código, ou `código:Classe`; até 96 | `entrega_falhada:ValueError` |

**Identificador** não é «letras, dígitos e sublinhados em qualquer ordem» — isso
é também a forma de um token e de um `provider_event_id`. É uma sequência de
**palavras** em minúsculas separadas por `_`, cada uma com até três dígitos no
fim (`http_404`, `v2`, `sha256`), ou um número até seis dígitos. O **código** de
`error_code` admite ainda maiúsculas (`CALLBACK_INVALIDO`), CamelCase
(`TimeoutError`), o número de um erro da Meta (`131049`) e o ponto, porque a
ponte põe lá o nome do *logger* de uma biblioteca (`uvicorn.error`).

Duas regras valem para todos os campos de texto, por cima da forma:

- **sete ou mais dígitos no total recusam o valor**, estejam onde estiverem.
  Apanha o telefone, o NIF, o IBAN e a referência de pagamento em qualquer
  arrumação que caiba no alfabeto do campo (`923.456.789`, `ok_923_456_789`,
  `923456__789`, `a923_b456_c789`), sem ser preciso saber o formato de nenhum
  deles. Não vale para os campos de forma fechada — um UUID e um `m_…` são
  hexadecimais, e têm os dígitos que tiverem (§7, ponto 3);
- **as formas de segredo com prefixo publicado** que cabem no alfabeto de um
  campo (`EAA…` da Meta, `eyJ…` de um JWT) recusam o valor.

### 2.1 Porque é que `turn_id` e `msg_id` não aceitam um `wamid`

`docs/tecnica/02` define `turn_id = wamid`, e o `msg_id` natural de uma mensagem
é também o seu `wamid`. O identificador de mensagem da Meta tem a forma
`wamid.` seguido de base64, e o que está codificado inclui o número do
interlocutor (**INDÍCIO**: é observação comum de quem integra a API, sem fonte
primária no canon — [`E1`](tecnica/evidencia/E1_Meta_WhatsApp.md) não o trata).
Um varrimento por `9\d{8}` não o vê, porque em base64 não há ali nove dígitos.

A decisão deste ticket, *proposta*, é não esperar pela confirmação: um `wamid`
em claro é **recusado**, e quem o tem regista `id_opaco(wamid)` — o SHA-256
truncado, que serve para correlacionar (quem tem o `wamid` recalcula-o) e não
deixa ver o número. O varrimento X-11 descodifica o que tiver cara de base64 e
procura lá dentro (§4.2).

`id_opaco` **nunca** recebe um telefone, um NIF ou outra coisa enumerável: um
resumo sem chave de um espaço pequeno inverte-se por enumeração, que é o
argumento do próprio ADR-010.

### 2.2 O que não existe como campo

Texto de mensagem, transcrição, telefone, morada, nome, e-mail, NIF, `contact_id`,
BSUID, referência de pagamento, `provider_event_id`, cabeçalhos, anfitrião, porta
e URL. Uma tentativa de os registar — por qualquer das portas do §3.2 — não
escreve nada e conta em `log_field_rejected_total`.

---

## 3. Como se usa

```python
from kamba_core.logger import instalar

log = instalar("agr")                     # uma vez, no arranque
log.info(outcome="service_started")
log.error(tenant_id=tenant, tool="criar_pedido", outcome="recusado",
          error_code="stock_insuficiente", latency_ms=42)
try:
    ...
except Exception as erro:
    log.excepcao(erro, "callback_invalido", tenant_id=tenant)
```

```ts
import { instalar } from "@kamba/core-ts/logger";

const log = instalar("gwy");
log.info({ outcome: "service_started" });
log.excepcao(erro, "callback_invalido", { tenant_id });
```

Cada chamada escreve **uma linha JSON** no `stdout`, com os campos pela ordem da
lista. `excepcao` regista `error_code = "<código>:<Classe>"` e nível `error`; a
mensagem, a causa, a pilha e as propriedades do erro não são lidas.

### 3.1 Um campo fora da lista

| Onde | O que acontece |
|---|---|
| TypeScript, ao compilar | **erro de compilação** — num literal, numa variável cujo tipo diga as chaves a mais, num objecto espalhado, num `object` sem chaves, e com um texto no lugar dos campos |
| TypeScript, o que o compilador **não** vê | um `any` (o resultado de um `JSON.parse`); um tipo com assinatura de índice; e um objecto com chaves a mais **atribuído primeiro a uma variável do tipo `CamposDeLog`** (`const f: CamposDeLog = e; log.info(f)`) — a atribuição esquece as chaves a mais, e é assim que o TypeScript funciona (§7.14). Um `object` e um `{}` já não compilam (revisão adversarial, A3) |
| Em execução, nas duas linguagens | o campo é **retirado** da linha e conta em `log_field_rejected_total:<motivo>`; a linha sai com o que sobrar |
| Em modo estrito (`KAMBA_LOG_ESTRITO=1`) | levanta `CampoRejeitado` / `CampoRejeitadoError` e **não escreve nada** |

O modo estrito é o «modo de teste» do ticket: existe para que um campo errado
apareça como teste vermelho e não como uma métrica que ninguém olha. **Nunca em
`prod`**: um *logger* que levanta derruba o pedido que estava a registar.

**Hoje não está ligado em bateria nenhuma.** Nenhum `Makefile`, `package.json`
ou configuração de testes define a variável; os testes que o exercitam passam
`estrito=True` à mão. Os serviços ainda só têm a sonda e o arranque, e não há
chamadas de negócio a que o ligar — o primeiro ticket que as trouxer (KAM-013)
liga-o nas suas baterias.

A verificação em execução existe mesmo em TypeScript porque um `as any`, um
`JSON.parse` ou um ficheiro `.js` chegam ao *logger* sem passar pelo compilador.

### 3.2 Os motivos de rejeição

| Motivo | Quando |
|---|---|
| `campo_desconhecido` | o nome não está na *allowlist* |
| `campo_reservado` | `ts`, `level` ou `svc` dados por quem chama |
| `valor_invalido` | o campo existe, o valor não tem a sua forma (ou é um objecto, uma lista, um nível desconhecido) |
| `mensagem_livre` | um argumento posicional, ou um texto no lugar dos campos |

O motivo é o sufixo da métrica, e é só isso: **o nome do campo recusado nunca
entra numa métrica**, porque um dicionário espalhado em argumentos
(`**corpo_do_pedido`) traz conteúdo nas chaves. A mensagem do modo estrito diz o
nome quando ele é curto e feito de palavras, e `<nome ilegivel>` quando não é.
O valor, nunca.

Um valor nulo (`None`, `null`, `undefined`) não é uma rejeição: o campo
simplesmente não sai.

### 3.3 O que não passa pelo *logger*

Um serviço escreve por mais caminhos do que o seu *logger*, e `instalar` fecha-os:

| Caminho | Python | Node |
|---|---|---|
| *Logging* de bibliotecas | a raiz do `logging` fica só com a ponte, e os *loggers* que já tinham manipulador próprio perdem-no: sai `outcome="log_biblioteca"` e `error_code=<nome do logger>[:Classe]` | não há equivalente ao `logging`: cada biblioteca escreve como quer (ver abaixo) |
| Erro num tratador de pedido | apanhado pelo Starlette e registado pelo `logging` do uvicorn → ponte | **o Hono faz `console.error(err)` por omissão.** Cada serviço substitui-o em `createApp` (`app.onError`): sai `tratador_falhou:<Classe>` e a resposta é um 500 sem pormenor |
| Avisos | `warnings` → ponte (`py.warnings`) | `instalar` tira o ouvinte de origem do Node e regista `aviso_do_processo:<Classe>` |
| Excepção por tratar | `sys.excepthook`, `threading.excepthook` e `sys.unraisablehook`: sai `excepcao_nao_tratada:<Classe>` | `uncaughtException` e `unhandledRejection`: sai o mesmo e o processo termina com 1 |

Em nenhum deles sai a mensagem, os argumentos, o `extra`, a pilha ou o
*traceback*. O uvicorn do AGR arranca com `log_config=None` para **não**
instalar os seus manipuladores, que escreveriam texto livre ao lado das linhas
JSON; o registo de acessos já estava desligado.

> **A primeira versão deste quadro dizia «as dependências de hoje não
> escrevem», e era falso.** A revisão adversarial mostrou a mensagem e a pilha
> de um erro de tratador a sair em claro pelo `console.error` do Hono, sem
> passar pelo *logger* nem pelos ganchos do processo
> ([`ANALISE-11`](analises/ANALISE-11-KAM-068-logs-sem-conteudo.md), A1). Hoje
> os serviços só têm `/healthz`, pelo que não houve fuga; o padrão é que estava
> errado, e era o que o primeiro tratador a sério ia herdar. O `@hono/node-server`
> tem outros `console.*` em caminhos de erro do próprio servidor, que **não**
> estão fechados (§7, ponto 6).

O que se perde, e está medido: as quatro linhas de arranque do uvicorn saem
todas como `{"level":"info","svc":"agr","outcome":"log_biblioteca","error_code":"uvicorn.error"}`.
Sabe-se que o uvicorn falou e em que nível; não se sabe o que disse.

### 3.4 Métricas

| Métrica | O que conta |
|---|---|
| `log_field_rejected_total:<motivo>` | campos recusados, por motivo |
| `log_write_failed_total` | linhas que não se conseguiram escrever (o destino falhou, ou a ponte falhou) |

São contadores em memória (`kamba_core.logger.CONTADORES`, o mesmo tipo que o
`tenant_guard` usa). **Ainda não há pilha de métricas** que os recolha: isso é o
KAM-080. Até lá, existem, são testados, e ninguém os vê em `prod`.

---

## 4. Verificações por máquina

### 4.1 *Lint* de arquitectura — *gate* 2

`make log-lint`, dentro do `make ci-2`. O *logger* só garante alguma coisa se for
o **único** caminho até ao `stdout`; um `console.log(pedido)` ao lado dele anula
a lista inteira, e nenhum teste do *logger* o vê.

| Regra | Linguagem | O que apanha |
|---|---|---|
| `console_directo` | TS/JS | qualquer uso de `console` |
| `stdout_directo` | TS/JS | os nomes `stdout` e `stderr`, venham de onde vierem, e `emitWarning` |
| `print_directo` | Python | `print`, `pprint` |
| `logging_directo` | ambas | importar uma biblioteca de registo: `logging`, `loguru`, `structlog`; `pino`, `winston`, `bunyan`, `morgan`, `debug` e o *middleware* `hono/logger` |
| `uvicorn_com_registo_proprio` | Python | `uvicorn.run(...)` ou `uvicorn.Config(...)` sem `log_config=None` |
| `stdout_directo` | Python | `.stdout` e `.stderr`, em qualquer objecto |
| `traceback_directo` | Python | importar `traceback` (a pilha traz a mensagem) |
| `saida_com_texto` | Python | `sys.exit`/`SystemExit` com texto: o interpretador escreve-o no `stderr` |
| `registar_directo` | ambas | chamar `.registar(...)`, a porta sem tipos do *logger* |
| `ficheiro_ilegivel` | ambas | o que não se consegue ler ou analisar, e um `/*` que não fecha |

**Âmbito:** tudo o que está em `services/*`, `packages/*` e `libs/*`, menos as
pastas `tests` — e não só `src/`, porque um ficheiro ao lado dele corre no
mesmo processo. Ficam de fora `tools/` e `db/`: ferramentas de linha de
comandos e orquestradores de *gates*, cujo trabalho é escrever no terminal e
que não tratam dados de clientes. A única isenção dentro do âmbito é o próprio
*logger*, e está no código (`ISENTOS`), não num ficheiro de configuração.

O segundo passo do alvo é o **canário**: 29 *fixtures* negativas têm de falhar,
cada uma pela regra que tem no nome e só por ela, e seis positivas têm de
passar. As regras obrigatórias estão fixas no código — um manifesto que se
esvazia dava «zero negativas, tudo verde»
([`ANALISE-05`](analises/ANALISE-05-KAM-111-dicionario-canonico-e-lint.md), B1).

Metade destas regras, e o âmbito alargado, vêm da revisão adversarial, que
mostrou cada evasão a passar (`ANALISE-11`, A2): o fluxo importado por nome ou
tirado de `process`, `sys` com outro nome, `traceback`, `sys.exit` com texto, e
uma expressão regular com `/*` lá dentro, que fazia o leitor de comentários
apagar o resto do ficheiro.

### 4.2 X-11 — *gate* 6

`make x11`, primeiro passo do `make ci-6`. É o X-11 da suite cruzada de
`docs/tecnica/08` §3.7 e §14.

1. **Geram-se 1 000 *fixtures*** — chamadas ao *logger* com telefone (dez
   formatos, incluindo os três do critério), NIF, e-mail, texto de mensagem,
   nome, morada, token, IBAN, referência de pagamento e `wamid`, por onze rotas:
   em cada campo da lista, em campos proibidos, como nome de campo, aninhado,
   em lista, em posicional, na mensagem de um erro, no nome da classe, nos
   campos reservados, embutido num identificador e como código de erro. O
   gerador recusa-se a produzir um conjunto em que falte uma combinação.
   Juntam-se-lhes **30 *fixtures* de forma**, que não levam um canário a
   passear e sim um valor que só **uma** regra recusa: um telefone como
   inteiro em `latency_ms` (o tecto), um identificador com dígitos pelo
   meio sem chegar aos sete (a forma por palavras), e um segredo que cabe no
   alfabeto de `error_code` (as formas de segredo). Sem elas, as três regras
   podiam sair das duas linguagens ao mesmo tempo e o X-11 continuava verde
   (`ANALISE-11`, §6).
2. **As duas linguagens fazem as mesmas chamadas**, com o relógio parado.
3. **A saída de Python e a de TypeScript têm de ser iguais byte a byte**, e os
   contadores de rejeição também. É a prova de paridade mais forte que há: não
   são dois testes parecidos, é a mesma entrada e a mesma saída.
4. **Controlo positivo:** o varrimento tem de ver, só com os padrões, os
   identificadores **na entrada**. Se os padrões deixarem de ver telefones, o
   zero do passo seguinte não quer dizer nada.
5. **Varrem-se os *logs***: zero achados, e exactamente 1 030 linhas por
   linguagem. Do lado Python varre-se ainda a saída da ponte (§3.3).

Os padrões: telefone angolano com e sem indicativo (`+244 9XX XXX XXX`,
`244 9…`, `9\d{8}`), com até dois caracteres quaisquer que não sejam letra nem
dígito entre cada dois dígitos; e-mail; IBAN; qualquer sequência de nove ou mais
dígitos, com a mesma tolerância; as formas de segredo do *gate* 9; telefone dentro de
base64; e a cadeia exacta de cada canário (é assim que se procura um nome ou
uma frase, que não têm padrão).

Antes de procurar, o texto é **normalizado**: dígitos de largura total e
árabe-índicos passam a ASCII, e os caracteres de largura zero saem — é o mesmo
telefone para quem lê o *log*. E a linha é lida **par a par**, não como
dicionário: uma chave repetida não esconde a primeira.

**O varrimento conhece a forma da linha**, e não é por conveniência. Um
`tenant_id` é um UUID, e cerca de 0,6% dos UUID aleatórios têm nove dígitos
seguidos começados por 9. Um varrimento cego dava falsos positivos todos os dias
em `prod`, e um varrimento que dá falsos positivos é desligado. Por isso os
campos de forma fechada (`ts`, `tenant_id`, `turn_id`, `msg_id`,
`contact_hmac_prefix`) são conferidos **pela forma**; se o valor não a tiver à
letra, é varrido como texto. Tudo o resto — os outros campos, as chaves, e
qualquer linha que não seja um objecto JSON — é varrido por inteiro.

**O padrão do NIF é um parâmetro** (`make x11 X11_NIF='<regex>'`,
`--nif-padrao` na linha de comandos). Nenhum documento define o formato
([`seguranca/lacunas.md`](seguranca/lacunas.md), Q-A), e o ticket manda não o
inventar. Sem ele, a saída diz em voz alta que o NIF não é medido por padrão
próprio; o que o apanha na mesma é a sequência de nove ou mais dígitos.

**O varrimento não importa o *logger*.** Um oráculo que usasse as formas de quem
está a verificar concordava com ele por construção. Partilham só a lista dos
doze campos, que um teste confere contra os três sítios onde está escrita.

### 4.3 Amostragem de `prod` — **só a ferramenta**

`docs/tecnica/08` §7.3 pede «amostragem semanal em `prod`», e o ticket fixa-a em
100 linhas aleatórias por serviço.

```bash
python -m log_policy amostra <pasta com um <servico>.log por serviço> \
    --registo <ficheiro>.jsonl [--linhas 100] [--nif-padrao '<regex>']
```

Tira a amostra, varre-a com o X-11 e **acrescenta uma linha JSON** ao registo:
quando, quantas linhas havia e quantas se amostraram por serviço, e quantos
achados por padrão — identificadores para um lado, desvios de formato para o
outro. Nunca a linha nem o valor. Sai com 1 se houver achados.

**O que não existe:** o agendamento. Não há `prod`, não há Loki de onde tirar
os *logs* (KAM-080), e não há pilha de métricas onde pôr «identificadores
directos em logs = 0» como métrica de OBS. A ferramenta está feita e testada; o
critério de aceitação que pede a amostragem **automatizada** não está cumprido.

### 4.4 O que os testes provam

- **Vectores de paridade** — uma tabela (`packages/core-ts/tests/fixtures/logger_paridade.json`)
  lida pelas duas baterias: 141 valores campo a campo, 21 nomes de serviço, 20
  chamadas com a linha esperada, `id_opaco` e a máscara. Os valores esperados foram escritos à mão.
- **Canários** — vinte, por todas as portas: nenhum aparece na saída, nem na
  mensagem do modo estrito.
- **A cablagem** — `tools/log_policy/tests/test_cablagem.py` lê o `Makefile` e
  o arranque de cada serviço: o *lint* está no `ci-2`, o X-11 no `ci-6`, e os
  serviços instalam o *logger* e ligam o tratador de erro. `services/agr/tests/test_arranque.py`
  corre o `main()` do AGR e confere o que o uvicorn recebe.
- **A lista é a do documento** — os dois lados leem o §7.3 de `docs/tecnica/08`
  e comparam; mudar um sem o outro falha.
- **Compilação** — 23 linhas marcadas `@ts-expect-error`: se uma passar a
  compilar, o `tsc` do *gate* 2 falha.

---

## 5. Como se acrescenta um campo

«Excepções: nenhuma sem ADR; um campo novo exige PR com justificação de
finalidade» (ticket). Em concreto:

1. **A finalidade, escrita.** Para que serve o campo, quem o vai ler, e porque
   é que nenhum dos doze serve. «Dava jeito para depurar» não é uma finalidade.
2. **O campo não é conteúdo nem identificador directo.** Se for dado pessoal
   pseudonimizado, diz-se a base (ADR-010) e o que acontece na rotação da chave.
3. **A forma fechada.** Um campo novo entra com a expressão que o valida. Um
   campo «de texto» não entra.
4. **O PR toca, juntos:** `docs/tecnica/08` §7.3; o dicionário (§3.10);
   `politica.py` e `politica.ts`; os vectores de paridade; `tools/log_policy/x11.py`;
   e este documento (§2). Os testes que comparam as listas falham se faltar um.
5. **Revisão do Responsável de Segurança.** O ticket exige-a para a troca de
   `contact_hmac_prefix`, e vale para qualquer campo. Hoje **não é imposta por
   máquina** (`docs/ci.md` §7, lacuna 16).

Retirar um campo segue o mesmo caminho. Alargar a forma de um campo existente
também: é uma alteração de política, não de implementação.

---

## 6. Referências de pagamento e cabeçalhos — o que falta, e porquê

Dois critérios de aceitação do ticket não se conseguem cumprir à letra ao mesmo
tempo que o primeiro, e a decisão não é deste ticket.

**Referências de pagamento.** O critério pede que «apareçam mascaradas (últimos
3 caracteres)» nos *logs* de PAY. A função existe nas duas linguagens
(`mascarar_referencia` / `mascararReferencia`: `***` mais os últimos três, com
máscara de comprimento fixo). Mas a *allowlist* é **exacta** e não tem campo
para uma referência, mascarada ou não — e um teste prova que o que a máscara
devolve não cabe em campo nenhum. Para a referência *aparecer* é preciso um
campo novo (§5), e isso é um PR do Responsável de Segurança a `docs/tecnica/08`.
O que está garantido hoje é a metade negativa: uma referência e um
`provider_event_id` **nunca saem em claro**, por nenhuma porta.

**Cabeçalhos.** O critério pede que os cabeçalhos «sejam registados por
*allowlist*». Não há campo para cabeçalhos, pelo que nenhum é registado — o que
é uma *allowlist* vazia, e não a que o critério descreve. O que está garantido é
também a metade negativa: `Authorization`, `X-Signature`, `Cookie` e
`webhook_token` dão zero, por qualquer porta, e o teste com cabeçalhos de
segredo está feito nas duas linguagens.

As duas caixas ficam por marcar no ticket, com esta razão.

---

## 7. Limites — o que isto **não** apanha

Os pontos 11 a 16 vêm da revisão adversarial
([`ANALISE-11`](analises/ANALISE-11-KAM-068-logs-sem-conteudo.md)): foram
reproduzidos, não se corrigiram, e ficam aqui em vez de num comentário.

1. **Texto passado a identificador.** `outcome=slug(mensagem)` — a frase de um
   cliente em `snake_case` — tem a forma de um identificador legítimo e passa.
   O mesmo vale para um nome próprio numa só palavra. A forma fecha o descuido
   (pôr a mensagem no campo); não fecha quem a transforma de propósito. A
   resposta completa seria um vocabulário fechado por serviço, que o ticket não
   pede.
2. **Um segredo só com letras.** As formas recusam o que tem dígitos pelo meio
   e os prefixos conhecidos; uma chave feita só de letras passa como `outcome`
   ou como código. Um *logger* não é um detector de segredos — o *gate* 9 varre
   o repositório, não os *logs*.
3. **Um telefone escondido dentro de um UUID ou de um `m_…` válidos.**
   `00000000-0000-4000-8000-000923456789` é um UUID canónico e
   `m_923456789` seguido de 23 zeros tem a forma de um `id_opaco`; nem o
   *logger* nem o X-11 os distinguem dos legítimos. É o preço de o varrimento
   não dar falsos positivos (§4.2). Exige construir o valor de propósito.
4. **O `wamid` leva o telefone: INDÍCIO, não facto verificado** (§2.1). Se for
   falso, a recusa de `wamid` em claro é mais estrita do que precisava; se for
   verdadeiro e alguém o registar por outro caminho, o X-11 só o vê em base64
   alinhado e com 16 ou mais caracteres.
5. **O *lint* é um *lint*.** Não segue `globalThis["con" + "sole"]`, nem
   `getattr(builtins, "pr" + "int")`, nem `os.write(1, …)`, nem um alias
   (`const p = process; p.stdout` é apanhado pelo nome `stdout`, mas
   `const escrever = p.stdout.write` usado mais abaixo só é visto na linha da
   atribuição), nem um módulo de terceiros que escreva por conta própria. O
   leitor de comentários de TypeScript sabe que uma barra precedida de uma
   barra invertida está dentro de uma expressão regular, e pouco mais.
6. **O que as dependências escrevem.** O *lint* não lê `node_modules` nem o
   `site-packages`. O Hono está tratado (§3.3); o `@hono/node-server` tem
   `console.*` em caminhos de erro do próprio servidor, e uma dependência nova
   pode trazer os seus. Do lado Python, uma biblioteca que escreva
   directamente no `stderr` em vez de usar o `logging` também escapa.
7. **O que os outros processos escrevem.** O Postgres, a fila, o Chatwoot e o
   Medusa têm os seus *logs*, que não passam por aqui. A amostragem (§4.3)
   vê-os se lhos derem; ninguém lhos dá ainda.
8. **O X-11 sobre a suite cruzada ponta a ponta.** O ticket pede o varrimento
   também «sobre os logs de uma execução ponta a ponta da suite cruzada». Essa
   suite é o KAM-066 e não existe; a que há no *gate* 6 é a camada SQL, que não
   escreve pelo *logger*. Quando o KAM-066 existir, regista o X-11 como caso.
9. **Atributos de tracing OTel.** O ticket diz que levam a mesma *allowlist*.
   Não há tracing no repositório, pelo que não há o que verificar; a regra fica
   escrita (§9) para o ticket que o trouxer.
10. **A paridade é a dos vectores e das 1 000 *fixtures*.** Fora deles as duas
    implementações podem divergir. Conhecidos: `12.0` é um inteiro em JavaScript
    e um `float` em Python, que o recusa; e, no modo estrito, a **ordem** das
    rejeições na mensagem difere quando há chaves que são números (o JavaScript
    ordena-as primeiro).
11. **Um *logger* de biblioteca configurado depois de `instalar`.** A ponte tira
    os manipuladores próprios dos *loggers* que existem quando é ligada; um que
    seja criado depois, com manipulador seu e `propagate=False`, escreve por
    ele. O *lint* proíbe-o no nosso código; numa dependência, não o vê.
12. **Processos-filho.** Um filho de `multiprocessing` (ou um `child_process`)
    não herda os ganchos: uma excepção lá dentro imprime a pilha e a mensagem.
    Nenhum serviço lança filhos hoje.
13. **Formas que o X-11 não vê.** Oito dígitos ou menos; um telefone em base64
    com menos de 16 caracteres ou desalinhado; e texto livre num campo que não
    é de forma fechada — `level`, `svc`, `outcome` — desde que não tenha
    padrão: um nome de pessoa em `svc` passa no varrimento (não passa no
    *logger*). Isto pesa na amostragem de `prod`, onde não há canários.
14. **`[k: string]: never`, `any` e uma variável do tipo `CamposDeLog`
    compilam.** A metade de compilação do critério fecha os tipos que dizem que
    chaves têm e os que dizem que não têm nenhuma. Não fecha o `any`, que em
    TypeScript desliga a verificação; nem `const f: CamposDeLog = objectoComMais`,
    porque a atribuição a uma interface não confere propriedades em excesso
    fora de um literal, e depois dela o tipo já não as conhece. Em execução o
    campo é retirado na mesma.
15. **`Array.prototype.includes` poluído.** Um código que substitua métodos
    nativos antes de chamar o *logger* consegue fazê-lo aceitar um campo. Quem
    consegue fazer isso no processo não precisa do *logger* para escrever.
16. **O modo estrito não corre em bateria nenhuma** (§3.1).
17. **Uma aplicação Hono criada fora de `createApp`.** O tratador de erro que
    substitui o `console.error` do Hono está em `createApp` de cada serviço, e
    um teste confere que os quatro o têm. Um `new Hono()` noutro ficheiro —
    uma sub-aplicação montada sem o seu `onError` — herda o da aplicação-mãe
    quando é montado com `route`, e não o herda se for servido à parte. O
    *lint* não o vê.
18. **Um ficheiro novo na pasta do *logger* herda a isenção do *lint*.** Não é
    regra do *lint*: é um teste (`test_a_pasta_isenta_do_lint_so_tem_o_logger`)
    que prende a lista de ficheiros, para que acrescentar um seja uma decisão
    visível.
19. **O X-11 só prova o que as *fixtures* levam.** As trinta de forma fecham
    três regras; as restantes formas do *logger* (limites de comprimento,
    classe do erro, prefixo do HMAC) são provadas pelos vectores de paridade
    e pelas mutações, não pelo varrimento.

---

## 8. Medições

Medido neste ticket; cada número tem ao lado o comando que o reproduz.

**Cobertura do *logger*** (o DoD pede ≥ 90% no módulo). Medida num contentor
`node:24.21.0-trixie-slim` com Python 3.13 e `coverage.py`, só sobre as
baterias do *logger*:

| Ficheiro | Linhas | Ramos |
|---|---|---|
| `libs/py-core/src/kamba_core/logger/__init__.py` | 99% (uma linha por cobrir) | 37 de 38 |
| `libs/py-core/src/kamba_core/logger/politica.py` | 125 de 125 (100%) | 56 de 56 |
| `libs/py-core/src/kamba_core/logger/ponte.py` | 60 de 60 (100%) | 18 de 18 |
| `packages/core-ts/src/logger/index.ts` | 98,97% | 98,77% |
| `packages/core-ts/src/logger/politica.ts` | 100% | 97,83% |

Medido depois das correcções da revisão adversarial e antes do último acerto
ao tratamento de um destino que falha (que retirou linhas, não acrescentou): a
ordem de grandeza é esta, o número exacto de cada execução está no artefacto
`cobertura` do *gate* 4.

```bash
coverage run --branch --source=libs/py-core/src -m unittest discover -s libs/py-core/tests -t libs/py-core/tests
coverage report --include='*/logger/*'
cd packages/core-ts && node --test --experimental-test-coverage tests/logger.test.ts
```

O *gate* 4 mede outra coisa — o estrato `critico` **agregado**, onde o *logger*
está com o `tenant_guard` — e é esse o número que bloqueia um PR. As
ferramentas de `tools/log_policy/` ficam no estrato `restante`: 99% (750 de 756
linhas), medido da mesma forma.

**X-11** (`make x11`):

| O quê | Valor |
|---|---|
| *Fixtures* | 1 000 (10 classes por 11 rotas: 96 pares, porque sete classes sem dígitos não percorrem as duas rotas transformadas; semente 68) |
| *Fixtures* de forma | 30 (dez por regra) |
| Canários procurados por cadeia exacta | 1 430 |
| Linhas geradas por linguagem | 1 030 |
| Saída de Python e de TypeScript | iguais byte a byte (159 245 bytes) |
| Rejeições contadas, iguais nas duas | 952 — 398 `valor_invalido`, 293 `campo_desconhecido`, 157 `mensagem_livre`, 104 `campo_reservado` |
| Linhas da ponte de Python varridas | 14 300 |
| **Achados** | **0** |
| Controlo positivo, só por padrões | telefone 100/100, NIF 100/100, e-mail 100/100, IBAN 100/100, `wamid` 100/100; referência 77/100; token 55/100; texto, nome e morada 0/100 |

A última linha diz o que os padrões **não** veem sozinhos: uma frase, um nome e
uma morada não têm forma, e um token sem prefixo publicado também não. Esses
são procurados pela cadeia exacta do canário — o que serve no CI, onde se sabe
o que se pôs, e **não serve na amostragem de `prod`**, onde não se sabe.

**Baterias:** 73 testes do *logger* em Python (52 em `test_logger.py`, 21 em
`test_logger_ponte.py`), 43 em TypeScript (`logger.test.ts`), 114 das
ferramentas (`tools/log_policy/tests/`), dois do arranque do AGR e dois por
serviço Node para o tratador de erro.

**Prova por mutação** (`python tools/log_policy/tests/mutacoes.py`): 185 mutações na lista, em cópia fora do repositório, com linha de base verde nos três corredores (Python, `node --test` e `tsc`); 0 sobreviventes. As 185 não correram numa só execução: 173 antes do seguimento à primeira revisão, e depois dele as 97 que tocam no que ele alterou (`ANALISE-11`, §3.2 e §6).
Seis mutações equivalentes ficaram fora da lista, com a razão escrita ao lado.
O detalhe, incluindo o que a revisão adversarial acrescentou, está em
[`ANALISE-11`](analises/ANALISE-11-KAM-068-logs-sem-conteudo.md).

**O que não está medido:** o custo do *logger* por linha; o comportamento sob
carga; e o alvo «identificadores directos em logs = 0» em `prod`, que não
existe.

---

## 9. Política de traces e retenção

Esta secção é o critério de aceitação «a política de traces está escrita». Não
decide nada de novo: junta num sítio o que `docs/tecnica/08` §7.3 e §11,
`docs/tecnica/09` §9.3 e o ADR-018 já dizem.

| Regra | Fonte |
|---|---|
| **Sem traces de LLM em `prod` no Piloto.** Não há Langfuse em produção; a observabilidade de IA faz-se por `llm_call_log` (sem conteúdo), pelos *spend logs* do LiteLLM e por avaliações offline | ADR-018; `docs/tecnica/09` §9.3 |
| **Em `staging`, traces só com dados sintéticos.** Os traces contêm o conteúdo das conversas — é para isso que servem —, e por isso só existem onde não há conversas reais | `docs/tecnica/08` §7.3; `docs/tecnica/09` §9.3 |
| **Langfuse só em Clusters, auto-hospedado.** A versão Cloud seria uma transferência internacional sob o ADR-008 | ADR-018 |
| **Retenção de *logs* técnicos: 30 dias**, por rotação; a excepção é um incidente em investigação | `docs/tecnica/08` §11 (*proposta*; os prazos legais estão por confirmar — a confirmar por parecer) |
| **Atributos de tracing (OTel), quando existir:** a mesma *allowlist* dos *logs*. O conteúdo de LLM só em ambientes sintéticos | ticket KAM-068, Detalhes Técnicos |
| **Dados do WhatsApp não treinam nem melhoram modelos.** O *golden set* admite as **três origens do KAM-040** — `sintetico`, `t2_anonimizado` e `real_consentido` — e nenhum caso `real_consentido` entra sem registo de consentimento | ADR-018; `adr/ADR-L006-origem-do-golden-set.md`; Termos da Meta |

O que **não** está imposto por máquina: nenhuma destas regras tem hoje um teste,
porque não há Langfuse, não há Loki e não há `prod`. A retenção de 30 dias é
configuração do Loki (KAM-080); a ausência de traces em `prod` é uma decisão de
topologia (KAM-079). Este documento é o sítio onde a regra está escrita para
que esses tickets a implementem.

---

## 10. Desvios ao ticket

| O ticket diz | O que está feito | Porquê |
|---|---|---|
| (nada sobre o tratador de erro HTTP) | `createApp(log)` com `app.onError` nos quatro serviços Node; resposta 500 genérica | Sem isso a mensagem de qualquer erro de tratador saía pelo `console.error` do Hono (revisão adversarial, A1) |
| Pacotes `libs/logger` (TS) e `libs/logger_py` | `packages/core-ts/src/logger/` e `libs/py-core/src/kamba_core/logger/` | A árvore do KAM-001 (`tools/lint_arch/structure.py`) fixa `packages/core-ts` e `libs/py-core` como as bibliotecas partilhadas; um pacote novo obrigava a mexer no `pnpm-workspace`, nos cinco `Dockerfile`, no `Makefile` e no `PYTHONPATH`, para o mesmo código. O `tenant_guard` (KAM-004) fez a mesma escolha |
| Teste em `security/logs/x11_scan`; regras em `ci/lint/` | `tools/log_policy/` | As ferramentas dos *gates* vivem em `tools/`, onde as suites se descobrem sozinhas e contam para a cobertura |
| «em Python, é removido com a métrica `log_field_rejected_total`» | removido e contado nas **duas** linguagens, com o motivo como sufixo | Um `as any` chega ao *logger* em TypeScript sem passar pelo compilador |
| Erros «por `error_code` e classe» | a classe vai **dentro** de `error_code` (`código:Classe`) | A *allowlist* é exacta e não tem campo para a classe |
| *Lint* de `console.log`/`print` | também `logging`, `process.stdout`/`stderr`, `sys.stdout`/`stderr` e `pprint` | São o mesmo caminho por outro nome |

---

## 11. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão (KAM-068): política, *allowlist* com a forma de cada campo, *logger* nas duas linguagens, *lint* no *gate* 2, X-11 no *gate* 6, ferramenta de amostragem, política de traces e limites. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | Depois da revisão adversarial ([`ANALISE-11`](analises/ANALISE-11-KAM-068-logs-sem-conteudo.md)): tratador de erro do Hono e avisos do Node (§3.3, onde a primeira versão afirmava o contrário); regra dos sete dígitos **no total** (§2); *lint* com mais quatro regras e âmbito alargado (§4.1); X-11 com normalização e chaves repetidas (§4.2); o modo estrito dito como está (§3.1); seis limites novos (§7); números corrigidos (§8). | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | Depois da **primeira** revisão, cujo relatório chegou com o PR já fundido (`ANALISE-11`, §6): 30 *fixtures* de forma no X-11 (§4.2); duas regras novas no *lint* — bibliotecas de registo de Node e `uvicorn` sem `log_config=None` (§4.1); um objecto com classe no lugar dos campos conta como mensagem livre também em TypeScript; a amostragem recusa um *log* vazio; a frase «numa variável» corrigida (§3.1) e três limites novos (§7.14 alargado, §7.17 a §7.19). | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-169: a última regra do §9 dizia que o *golden set* «é feito por reescrita sintética», e passa a nomear as **três origens do KAM-040** (`sintetico`, `t2_anonimizado`, `real_consentido`) com a barreira do registo de consentimento. A primeira metade da regra — os dados do WhatsApp não treinam nem melhoram modelos — **não muda**, porque é o que os Termos proíbem; o que mudou foi a origem do conjunto de avaliação, por decisão do fundador a 2026-10-30 (`adr/ADR-L006-origem-do-golden-set.md`). | Equipa KAMBÁ |
