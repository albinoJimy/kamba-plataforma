# Minimização de PII antes do LLM

| Campo | Valor |
|---|---|
| Âmbito | O detector e o tokenizador que correm antes de qualquer chamada ao LLM ou ao STT (KAM-112) |
| Componentes | AGR (`../services/agr/src/kamba_agr/privacidade/`), gateway de LLM (KAM-030) |
| Documentos-fonte | `tecnica/08_Seguranca_Conformidade.md` §7.4 e §7.5, `tecnica/02_Agent_Runtime_Verticais.md` §8.4 e §13.4, `tecnica/evidencia/E3_Regulatorio_Dados.md` requisitos 6, 8 e 10 |
| ADRs | ADR-007 (números são *facts*), ADR-008, ADR-010, ADR-018 |
| Nomes canónicos | `../specs/02_Dicionario_de_Dados_Canonico.md` §3.37 |
| Estado | **Proposta.** Os limiares e a sobrecarga calibram-se no Piloto (KAM-109) |

| Aprovação | Nome | Data |
|---|---|---|
| Fundador | *(por ratificar)* | — |

---

## 1. O que isto garante, e o que não garante

**Garante** que nenhum texto de um cliente chega a um modelo de linguagem sem
passar por um detector local: o `ClienteDeLlm.chamar` exige `MensagemMinimizada`,
que só se constrói a partir de um `MinimisedText`, que só o `minimise` produz.

**Não garante** que deixou de haver transferência internacional de dados
pessoais. O `tecnica/08` §7.4 e o bloco do KAM-112 dizem o mesmo e vale repeti-lo
aqui: «nomes próprios dentro de texto livre e referências a locais escapam a
*regex*; a minimização **reduz** exposição mas não prova que deixou de haver
transferência» — *(a confirmar por parecer; `E3` requisito 6)*. O gate de destino
(`tenant_destinations`) é o **KAM-069** e não existe; em `prod`, hoje, **todas**
as chamadas são negadas pela porta de destino e contadas em
`agr_llm_destino_negado_total`.

As limitações concretas estão **medidas e nomeadas**, não descritas: são os
**nove** casos de `corpus_pii.LIMITES`, e há um teste que falha no dia em que
algum deles deixar de escapar. Três entraram com a revisão adversarial deste
ticket — o IBAN e a conta bancária, o telefone com barras e o número de BI —, e
nenhum dos três está nos seis tipos que o critério 2 enumera.

---

## 2. O pipeline, e porque a ordem é a barreira

```text
1. dobrar      minúsculas, sem acentos, dígitos Unicode → ASCII
               (comprimento preservado caracter a caracter)
2. reclamar    os intervalos de NÚMEROS DE NEGÓCIO (negocio.py)
3. detectar    por tipo, do mais específico para o menos
4. recusar     todo o achado que toque um intervalo reclamado
5. substituir  tokens numerados por ordem de leitura, estáveis no thread
```

O passo 4 é o critério 4, e é a razão pela qual «0 preços alterados» é uma
**propriedade da construção** e não um resultado de medição: o detector nunca vê
um preço. A medição dos 214 casos adversariais existe para provar que a
construção é a que se diz, não para descobrir se calhou bem.

**O risco deste desenho é simétrico, e está declarado.** Um intervalo reclamado a
mais **esconde PII do detector**: um telefone escrito «912345678 Kz» não é
mascarado. É o lado certo de errar — mascarar um preço destrói o produto, porque
os números são *facts* (ADR-007) e o validador de citação (KAM-032) recusa uma
resposta que cite o que não veio de uma *tool* — e é um dos seis limites
declarados.

---

## 3. As quatro barreiras

### 3.1 O tipo (critério 1)

`minimise(texto, ctx) → (MinimisedText, Mapa)` é a única via. O `MinimisedText` é
uma classe cujo selo é um **HMAC do próprio texto** com uma chave de processo,
não um `NewType`:

```python
MinimisedText("o meu numero e 912345678")   # TextoNaoMinimizado
```

**A razão de não ser uma anotação é uma medição:** não há verificador de tipos
para Python neste repositório. O `make typecheck` é `pnpm -r run typecheck` e
cobre TypeScript; o `ci-2` corre `typecheck`, `lint-arch` e `log-lint`, e nenhum
lê anotações de Python. Uma anotação sozinha seria a «convenção documentada» que
o bloco recusa por escrito.

**A primeira versão tinha um selo que se forjava de quatro maneiras**, e a
revisão adversarial mediu-as todas. A causa era comum: o selo provava **quem
construiu**, não **o que ficou construído** — um `object()` igual para qualquer
texto copia-se de um objecto legítimo para um forjado. As quatro:

| Forja | Porque passava | Onde fecha agora |
|---|---|---|
| `dataclasses.replace(m, texto=cru)` | reinvoca o `__init__` com o selo real | a impressão não corresponde ao texto novo |
| `object.__setattr__(m, "texto", cru)` | o `frozen=True` não protege do `object` | `verificada()`, no ponto de uso |
| `MinimisedText(cru, m.selo)` | o selo era campo público | não há impressão válida para texto que não passou |
| `MensagemMinimizada("user", pato)` | a classe não validava nada | `__post_init__` dela |

Ligar o selo ao texto fecha as três primeiras; a quarta fecha na classe que a
sofria. **Não é criptografia a sério e não precisa de ser:** o que isto defende
não é contra um atacante, é contra o próximo programador desta casa a escrever,
de boa-fé, a linha que parece funcionar.

São por isso **três** verificações, e nenhuma substitui as outras:

| Via | O que protege | Onde |
|---|---|---|
| `__post_init__` com HMAC | a construção | `privacidade/minimizacao.py` |
| `verificada()` no `para_esquema` | o que **sai**, depois de construído | último ponto antes do corpo HTTP |
| política AST | o **diff** — o caminho que ninguém exercitou | `tests/politica_llm_ast.py` |

**E a política AST estava invertida**, o que também é da revisão (achado 4):
recusava `[mensagem("user", minimo)]` — a forma correcta, que a sua própria
mensagem recomenda — e aceitava as quatro forjas desde que se atribuísse a uma
variável. Hoje olha para o **valor** e não para a forma do nó, e tem seis
evasões medidas e três formas conformes como canários nos dois sentidos.

A política tem quatro regras e três canários obrigatórios. Corre no
`make test-py`, que o *gate* 4 já executa: **não se abriu *gate* novo**, pela
decisão que o `politica_ast.py` do KAM-034 escreveu — um *job* novo é um contexto
exigido novo no *ruleset* de `main`, isto é, alteração de regra de bloqueio.

### 3.2 Falha fechada (critério 7)

Erro ou tecto de tempo do detector levantam `FalhaDeMinimizacao`, que vive no
`llm/erros.py` e **é** um `ErroDeLlm` — como o `DestinoNegado` e pela mesma
razão: o `classify` do Vendedor já apanha esse tipo, o `degradacao.py` dá-lhe o
motivo `minimizacao`, e o turno responde pelo menu determinístico (KAM-037) ou vai
a *handoff*. **Não há ramo no código que devolva o texto original.**

O motivo `minimizacao` é o **sétimo** da lista fechada e **não conta no
disjuntor** — não é avaria do fornecedor, acontece antes de haver chamada.

Dois tectos, e não são a mesma coisa:

| Constante | Valor | O que é |
|---|---|---|
| `ALVO_P95_MS` | 30 ms / 2.000 caracteres | o alvo do critério 7, ***proposta***. **Nada falha por o exceder** |
| `TECTO_MS` | 250 ms | o ponto a partir do qual a minimização se **recusa**. Falha fechado |

**O `TECTO_MS` é uma verificação a posteriori e não um *timeout*, e a primeira
versão desta página afirmava o contrário.** Dizia que «um detector que demore
mais do que isso falha em vez de atrasar o turno» — e isso é falso: a duração
mede-se **depois** de o detector ter corrido, pelo que o turno **é** atrasado o
tempo inteiro. Medido pela revisão adversarial (achado 11), com um detector a
dormir 400 ms: levantou depois dos 400 ms.

O que o tecto garante, e é o que o critério 7 pede pela letra, é que uma
minimização lenta **não chega ao LLM**. O que ele não garante é que o turno não
demore. Interromper a sério obrigava a um `signal.alarm` (que não vale em
*threads*, e o AGR corre um `asyncio.Task` por conversa) ou a outro processo —
muito mais caro do que o problema, com um p95 medido de 21,5 ms contra um tecto
de 250. **Fica como lacuna declarada, não como propriedade afirmada.**

### 3.3 O mapa nunca sai do AGR (critério 6)

Vive em `ConversaState["pii_map"]`, com a retenção do *checkpointer*. Não entra em
`dat.llm_call_log` (que não tem coluna de texto), nem em métrica, log, *trace* ou
evento. O `Mapa.__repr__` mostra **contagens por tipo** e nem os tokens:

```python
f"{mapa}"      # Mapa(morada=1, telefone=2)
```

É a barreira mais barata que há, e fecha o vazamento real — o modo como isto
sairia é um `f"{mapa}"` num `extra` de *logger* ou numa mensagem de excepção.

**O mapa atravessa turnos**, e fica fora de **duas** tabelas (do `CAMPOS_DO_TURNO`
e do `estado_inicial`), que é a assimetria do `turn_seq` do KAM-114. A razão é
própria: a janela de mensagens leva as mensagens **minimizadas** dos turnos
anteriores, pelo que um `TELEFONE_1` do turno 1 reaparece no *prompt* do turno 3;
com um mapa por turno, a re-identificação **removia** o token e a resposta ao
cliente perdia o telefone que ele próprio deu.

**Nenhuma migração entra com este ticket.** É a lição do KAM-160: «um terceiro
sítio para o mesmo facto seria uma terceira verdade». A purga é o KAM-071; o
`adelete_thread` do *checkpointer* leva o mapa com o *thread*.

### 3.4 Zero dados reais no corpus

Os 342 casos são sintéticos: telefones escritos dígito a dígito, topónimos
públicos, nomes próprios comuns, `exemplo.co.ao`. Os Termos da Meta §4.7 proíbem
usar dados da plataforma para treinar ou melhorar ML (ADR-018, `E1` §4), e um
corpus feito de conversas de clientes era exactamente isso — a montante de
qualquer modelo, porque é este corpus que **calibra** o detector.

As métricas levam **o tipo e a duração, nunca o texto detectado**:
`agr_pii_mascarada_total{tipo}` e `agr_minimise_latency_ms`.

---

## 4. O que se mede, e o que a medição não diz

Medido nesta máquina, com `./.venv/Scripts/python.exe -m unittest discover -s
services/agr/tests -t services/agr/tests -k minimizacao` (exit 0, 75 ensaios).
Publicado em `ci/pii/recall.json` e `ci/pii/latencia.json`, que são **gerados** e
estão no `.gitignore` como o `ci/x11/`.

| Tipo | Apanhados | Limiar do critério 3 |
|---|---|---|
| `TELEFONE` | 165/165 — 100% | ≥ 99% *(proposta)* |
| `BSUID` | 21/21 — 100% | ≥ 99% *(proposta)* |
| `EMAIL` | 54/54 — 100% | ≥ 99% *(proposta)* |
| `NIF` | 30/30 — 100% | ≥ 99% *(proposta)*, **com padrão de ensaio** — ver §5 |
| `MORADA` | 70/70 — 100% | ≥ 90% *(proposta)* |
| `PESSOA` | 40/40 — 100% | ≥ 90% *(proposta)* |

Corpus: **376** casos etiquetados, 0 dados reais (a letra pede ≥ 300).

| Critério 4 | Resultado |
|---|---|
| Casos adversariais | **277** (a letra pede ≥ 200) |
| Cadeias que tinham de sobreviver | 326 |
| **Alteradas** | **0** |

| Critério 7 | Resultado |
|---|---|
| p50 / p95 / máx para 2.000 caracteres, 40 execuções | 18,0 / **21,5** / 27,1 ms |

**A margem do p95 encolheu, e vale dizê-lo.** A primeira versão media 5,0 ms; as
correcções da revisão adversarial — a detecção em duas fases, o contexto de
negócio com duas janelas, o contexto forte de pessoa — custaram quatro vezes
isso, e o p95 passou a 21,5 ms contra um alvo *proposto* de 30. **Continua
abaixo, e já não com uma ordem de grandeza de folga.** Quem calibrar no KAM-109
tem aqui o número de partida; se o alvo passar a vinculativo, este é o sítio onde
se paga.

**O que estes números não dizem.** O recall é sobre um corpus **que o executor
escreveu**: diz que o detector apanha o que **este corpus** tem, e não o que um
cliente angolano escreve. 0 falhas em 214 casos limita o risco a cerca de **1,5%
com 95% de confiança** — e «0 alterados neste conjunto» não é «0 alterados em
produção». A medição de latência é nesta máquina e **não no *runner***.

Os limiares não são requisitos cumpridos: são **propostas**, e o próprio critério
3 e o critério 7 o dizem. Calibram-se no **KAM-109**.

---

## 5. O NIF, e porque o recall dele é 0% por omissão

O `tecnica/08` **não define** o formato do NIF angolano, e o bloco do KAM-112
manda **não o inventar**. Por isso o `detector.PADRAO_DE_NIF` nasce `None`, e com
`None` **o NIF não é detectado por padrão próprio**.

É o precedente exacto do `make x11 X11_NIF='<regex>'` do KAM-068, que resolveu a
mesma ausência no mesmo documento da mesma maneira. Quem souber o formato
passa-o; a medição acima foi feita com um **padrão de ensaio**
(`corpus_pii.PADRAO_DE_NIF_DE_ENSAIO`), que é parâmetro de medição e **não é
canon** — e sem ele o recall de NIF é 0%, que é o que o limite
`nif_sem_padrao` declara.

---

## 6. Os nomes do catálogo do tenant (critério 5), e o que fica parcial

O critério 5 manda não mascarar os nomes que são *facts* do catálogo — «marcas,
produtos, recursos e profissionais de Serviços» —, com a lista «lida da porta
`CommerceRegistry`». Duas medições:

1. o **`CommerceRegistry` não está implementado**: é o KAM-042, aberto. Em código
   há uma ocorrência do nome, num comentário de `../services/com/src/app.ts`;
2. o contrato proposto em `tecnica/03_Core_Comercio_Medusa.md` §3.2 **não tem
   operação que devolva uma lista de nomes** — o `getOfferView` é por `sku`.

Logo o critério **não se cumpre à letra hoje nem se cumpriria no dia em que o
KAM-042 fundisse**, sem lhe acrescentar um método. Isso é informação para quem
escreveu o critério.

O que se fez: uma porta **do lado do consumidor** (`PortaDeCatalogo.nomes`), com
a pergunta que o detector precisa de fazer, e um adaptador mínimo sobre as
tabelas que existem. **Não é o `CommerceRegistry`, não se chama assim, e não
decide o contrato dele**; o credor é o KAM-042, que substitui o adaptador e não a
assinatura.

| Classe do critério 5 | Fonte hoje | Estado |
|---|---|---|
| marcas | `platform.tenants.nome` | **existe** — o grafo já a lê por `get_store_info` |
| recursos e profissionais | `servicos.resources.nome` | **existe** desde o KAM-035 |
| serviços oferecidos | `servicos.services.nome` | **existe** desde o KAM-035 |
| **produtos** | — | **não existe**: sem tabela e sem porta. KAM-042, KAM-043 |

Por isso a caixa do critério 5 fica **parcial**: três das quatro classes têm
fonte, os produtos não.

**Os nomes entram no `minimise` pelo contexto, já carregados.** Uma consulta por
mensagem não cabe nos 30 ms do critério 7 e punha o detector a falhar quando a
base falhasse — e um nome do catálogo mascarado por engano é um *fact* perdido
(que o validador apanha), não uma transferência.

---

## 7. O que fica fora, por decisão do bloco

| Fora | Ticket |
|---|---|
| Gate de destino (`tenant_destinations`) e inventário de subprocessadores | KAM-069 |
| Logs sem conteúdo e redacção de PII em log | KAM-068 (fechado) |
| Classificador de dados sensíveis | KAM-033 |
| Agregados anonimizados | — |
| *Golden* PT-AO e o **gate 13** | KAM-040 |
| Calibração dos limiares e dos dicionários | KAM-109 |

E duas coisas que **não** são deste documento mas constam dele por serem
perguntadas:

- **o áudio não se mascara antes do STT.** A minimização ali é não enviar
  metadados com o *blob* (contacto, telefone, *tenant*) e passar o destino pelo
  gate (`tecnica/08` §7.5); a transcrição entra **neste** pipeline antes de
  chegar ao LLM, pelo gancho do KAM-036;
- **o contacto do turno é sempre «Cliente»** (`tecnica/02` §8.4), e isso
  cumpre-se por construção: o `ContextoDeMinimizacao` **não tem** `contact_id`,
  telefone nem BSUID, pelo que não há caminho que ponha o contacto no *prompt*. O
  telefone dele continua só em `contact_endpoints`, cifrado (KAM-008).

---

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial, KAM-112. O pipeline, as quatro barreiras, as medições do corpus de 342 casos e dos 214 casos adversariais, o NIF sem padrão, a porta de catálogo e o que fica parcial. **Proposta.** | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | **KAM-112, revisão adversarial: catorze achados, todos reproduzidos antes de gerar trabalho.** Oito eram furos em critérios e estão corrigidos: o `sku` reclamava a parte local de um e-mail com dígitos e o endereço saía em claro (**critério 2 e 3**); um total de nove dígitos **sem** marcador de moeda era mascarado como telefone, e o corpus não tinha o caso (**critério 4**); o selo do `MinimisedText` forjava-se de quatro maneiras (**critério 1**); a política AST recusava a forma correcta e aceitava as evasões (**critério 1**); um nome de catálogo com mais do que uma palavra não protegia nada, que é precisamente a forma de um `servicos.resources.nome` (**critério 5**); e o recall de morada, pessoa e NIF era medido sobre o dicionário do próprio detector. O corpus passa a 376 casos de PII e 277 adversariais, com e-mails com dígitos, topónimos fora do dicionário, nomes fora da lista e totais sem moeda. Três limites novos declarados (IBAN, telefone com barras, BI). Duas afirmações falsas corrigidas no sítio: o tecto de tempo **não** interrompe nada, e a falha fechada cobria só a chamada ao detector. O p95 subiu de 5,0 para 21,5 ms, contra um alvo *proposto* de 30. | Equipa KAMBÁ |
