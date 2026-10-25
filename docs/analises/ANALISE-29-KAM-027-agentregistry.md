# ANÁLISE-29 — KAM-027: o registo que valida tudo e não liga nada

| Campo | Valor |
|---|---|
| Ticket | KAM-027 — AgentRegistry e validação no arranque (YAML, nós obrigatórios, licenças) |
| Âmbito | O pacote `kamba_agr/registo/` (`__init__.py`, `esquema.py`, `validar.py`), os três ficheiros novos de `registry/` (`vendedor.yaml`, `servicos.yaml`, `gates.yaml`), a guarda do SBOM em `egresso.py`, o arranque em `__main__.py`, as três baterias (`test_registo.py`, `test_egresso.py`, `test_arranque.py`), a terceira forma do *gate* 3b, as 15 mutações, o fecho de dependências do AGR, a emenda 1.35 do dicionário, a nota do ADR-L001 §4 e a secção de verificação do próprio bloco |
| Método | Revisão adversarial independente do *diff* em *stage* mais a árvore de trabalho (26 ficheiros, ~3,9k linhas), por um agente que recebeu o código e os requisitos e **não** as justificações do autor. Dois instrumentos na mesma passagem (`code-review high` e `ponytail-review`), oito perguntas dirigidas, com obrigação de responder por extenso também onde não encontrasse nada. A secção «Verificação dos Critérios de Aceitação» foi tratada como **afirmação a verificar** e não como contexto |
| Resultado | 25 achados — **3 críticos, 8 importantes, 11 menores, 3 nice-to-have** |
| Veredicto | **REPROVADO**. Três dos oito critérios estão marcados «satisfeito» com evidência que mede outra coisa, e um deles — o «emite alerta» do critério 6 — está provado contra um duplo que aceita um nome de métrica que o objecto real **recusa** |

| Aprovação | Nome | Data |
|---|---|---|
| Engenheiro de Runtime/IA | | |
| Arquitecto de Plataforma | | |

---

## 1. O achado que justifica o veredicto

**A métrica `agr_registry_denied_total` não pode ser contada, e o critério 6
está marcado «satisfeito» por causa de um duplo.**

O `registo._negar` faz `self._metricas.contar(METRICA_NEGADAS, motivo)`. O
`MetricasDoAgr.contar` de `services/agr/src/kamba_agr/metricas.py` — ficheiro
que este *diff* **não toca** — decide assim:

```python
if metrica in _CONTADORES_SEM_ETIQUETA: ...
elif metrica in _VALORES_DA_ETIQUETA:   ...
else: raise EtiquetaInvalida(f"{metrica}: contador desconhecido")
```

`agr_registry_denied_total` não está em nenhum dos dois dicionários, nem em
`_AJUDA`. O caso concreto, com o objecto real do módulo:

```
AgentRegistry(ler_entitlement=ler, metricas=METRICAS).resolve(ctx)
→ EtiquetaInvalida: agr_registry_denied_total: contador desconhecido
```

Um *tenant* sem plano activo é o caminho **previsto** do critério 6 — «devolve a
resposta estática "serviço indisponível" e emite alerta». Com o objecto real
ligado, esse caminho passa a excepção: exactamente a confusão que a *docstring*
do `Resolucao` diz existir para evitar («levantar uma excepção punha o caminho
normal de um *tenant* sem plano a passar por um `except`»). E mesmo que não
levantasse, o `exposicao()` nunca emitiria a série, porque só itera `_AJUDA`.

O que faz disto o achado do veredicto não é o esquecimento — é **a forma como o
teste o esconde**. O `TestResolve` usa `MetricasEspia`, um duplo que aceita
qualquer nome, e mede «uma contagem de `agr_registry_denied_total{motivo}`». E
o teste que parece confrontar a classe real faz isto:

```python
from kamba_agr.metricas import ETIQUETA, MetricasDoAgr
...
self.assertTrue(issubclass(MetricasDoAgr, object))
```

Uma asserção sempre verdadeira, com a aparência de medir compatibilidade. É a
mesma figura do KAM-026 — um varrimento de privacidade que devolvia zero
ocorrências porque procurava texto num campo `msgpack` —, e desta vez o nome
entrou no dicionário canónico (§3.26, emenda **1.35**, parte deste *diff*) a
dizer «Etiqueta `motivo`», quando o `_etiqueta_de()` daquele módulo devolveria
`outcome` para qualquer métrica que não seja o `agr_admitted_rejected_total`.

## 2. Os outros dois críticos

**Os critérios 2 e 3 não são satisfeitos, e o mecanismo que os adia apaga-se a
si próprio no dia em que o credor chegar.** A letra do bloco: o critério 1 pede
que *qualquer* das seis falhe o arranque, o critério 2 diz «reprova o arranque»
para a tool, o critério 3 diz «reprova o arranque» para os nós, e o critério 8
isenta **só** a (6). Com o `registry/gates.yaml` entregue, `tools` e `grafo`
estão em `aviso` e nenhum reprova nada. Isso, hoje, é defensável — as fontes não
existem. O que **não** é defensável é o mecanismo: o `carregar` só constrói uma
`Adiada` quando `problemas` não é vazio.

```python
problemas = validar(vertical, env)
if problemas and modo is not None and modo.modo == "aviso":
    adiadas.append(Adiada(nome, identificador, modo.credor)); continue
```

No dia em que o KAM-028 ligar o catálogo, `validar_tools` devolve `()` para um
registo correcto: não há erro **nem aviso**, e a linha
`tools: { modo: aviso, credor: KAM-028 }` sobrevive sem que nada a denuncie —
nem o `gates.yaml`, nem o CI, nem o registo de arranque. A partir desse dia, o
caso concreto: o KAM-028 renomeia `get_order_status` para `get_order`,
`registry/vendedor.yaml` fica com o nome antigo, e o arranque emite um aviso
que ninguém lê em vez de falhar o *deploy*. O mesmo vale para o caso que o
ADR-015 paga — uma tool que exponha `tenant_id` no esquema visível ao modelo
passa a aviso. O `registry/README.md` diz «fechar uma é apagar a sua linha»;
não há nada que o imponha.

Há uma forma mais simples que preserva o significado e fecha os dois critérios
à letra: a validação distingue «a fonte não existe» de «encontrei um achado», e
o `aviso` suprime **só** o primeiro. As linhas do `gates.yaml` passam a ser
inofensivas quando o credor chegar, os critérios 2 e 3 ficam satisfeitos à
letra desde já, e o `gates.yaml` deixa de ser uma coisa que se esquece ligada.

**O `validar_fase` é lista de proibidos onde o canon é lista de permitidos, e a
*docstring* afirma o contrário do que o código faz.**

```python
if vertical.phase != "D": return ()
if env.fase and env.fase != FASE_PILOTO: return ()
```

Qualquer valor não vazio que não seja `piloto` deixa passar uma vertical
`phase: D`. A *docstring* cita por extenso a fonte que diz o oposto: «o
`fluxo_piloto` do KAM-003 já escreveu a razão — `piloto` é o único valor que o
canon define, e **ausente, vazia ou com outro valor**, a guarda levanta». E é
mesmo assim: o `verificar_arranque` daquele módulo levanta `FaseNaoDefinida`
para todo o `fase != FASE_PILOTO`. O que esta validação implementa são **dois**
dos três casos.

Isto importa porque o AGR **não chama** aquela guarda — um `grep` por
`verificar_arranque` em `services/agr/` não devolve nada —, pelo que o
`validar_fase` é a única guarda de fase deste processo. Caso concreto: um
`KAMBA_FASE=Piloto` (maiúscula) ou `KAMBA_FASE=producao` num *deploy*, com um
`registry/assistente.yaml` em `phase: D`, carrega e resolve. É o Fluxo B em
produção no Piloto, que é o que o ADR-011 difere. Hoje não morde porque aquele
ficheiro não existe — e é precisamente o ficheiro que o Fluxo B traz.

E o teste consagra o buraco: `test_5_phase_d_fora_do_piloto_passa` usa
`fase="clusters"`, um valor que o canon não define e com que nenhum serviço
desta casa arranca.

## 3. As afirmações que o código desmentia

**A isenção do *gate* 3b justifica-se com um teste que não existe.** O
`ci/canon-lint.yaml` tira `services/agr/src/kamba_agr/registo/*` do âmbito da
superfície 3 e escreve como contrapartida: «há um teste de arquitectura que
prende os seis nós obrigatórios e as onze tools ao dicionário, lido como
texto». O `TestArquitectura` tem quatro testes — literais, `id` inventado,
lista de importações permitidas, independência do resto do AGR. **Nenhum** lê
`specs/02_Dicionario_de_Dados_Canonico.md` nem `canon/dicionario.yaml`. O único
confronto que existe (`test_as_seis_validacoes_do_codigo_sao_as_que_o_gate_3b_aceita`)
prende os *nomes das validações* ao `canon_lint`, não os nós nem as tools ao
dicionário. Caso concreto: trocar `handoff_wait` por `handoff_esperar` em
`NOS_OBRIGATORIOS` — nenhum *gate* e nenhum teste objecta, e o dicionário §3.26
passa a descrever outra coisa. Uma isenção de um *gate* pagou-se com uma
promessa.

**O critério 8 está «satisfeito» com evidência que mede outra validação.** A
afirmação: «a passagem a bloqueante não precisa de código: `bloqueio` é a
omissão, pelo que fechar o gate é **apagar** a linha —
`test_apagar_a_linha_do_gates_torna_a_validacao_bloqueante` mede-o». Esse teste
apaga a linha do **`tools`**. Para o `golden` — a única validação de que o
critério 8 trata — apagar a linha torna o AGR **impossível de arrancar**,
porque o `validar_golden` acrescenta **sempre** «não há eval harness que diga
se o gate golden está verde». O `shortcut:` novo em `validar.py` já o admite
(«nesse dia esta linha sai daqui **e** a linha `golden` sai de
`registry/gates.yaml`»), mas o `registry/gates.yaml` e o `registry/README.md`
continuam a afirmar, os dois, «não há interruptor nenhum no código».

**O `turno.py` e o `__main__.py` continuam a nomear o KAM-027 como quem liga o
que ele não ligou.** `sem_grafos`: «A porta `grafos` por omissão: levanta.
Substituída pelo KAM-027». `__main__.py`: «Quem o passa ao
`compile(checkpointer=...)` é o KAM-027 — aqui ele serve a guarda do arranque e
o encerramento, e nada mais». A decisão de não ligar está argumentada na secção
de verificação e eu concordo com ela (ver §5). O que fica mal é que os dois
comentários do KAM-025 não foram corrigidos: quem escrever o KAM-031 lê-os
primeiro e vai procurar uma ligação que não existe.

**A paridade da guarda do SBOM é afirmada com mais força do que o teste
sustenta.** A verificação diz «a paridade com o `lint_arch` mede-se por
comportamento e não por campos: 23 nomes × 4 versões, as duas implementações
decidem o mesmo em 92 casos». Metade é verdade: o teste chama o `matches_name`
real. A outra metade não: ele **reimplementa** a comparação de versões
(`tuple(int(p) for p in versao.split("."))`) em vez de chamar
`versions.satisfies_floor`. É um terceiro oráculo, e concorda com o `egresso.py`
por construção. Duas divergências reais ficam fora da amostra (as quatro versões
são todas de três componentes):

| Entrada | `lint_arch` | guarda de *runtime* |
|---|---|---|
| `litellm==1.83` | `compare` iguala por *zero-padding* → **permitido** | `(1,83) < (1,83,0)` → **bloqueia o arranque** |
| `litellm==1.84.0.post1` | `exact_pin` não casa o `post1` → «não é pin exacto» → **bloqueia** | `_versao` dá `(1,84,0)` ≥ limiar → **permitido** |

E o `exacto=True/False` da tabela é copiado à mão: o único teste de paridade de
campos compara **conjuntos de nomes**. Caso concreto: mudar `langgraph-api` para
`match: prefix` no YAML (para apanhar um `langgraph-api-ext`) — o conjunto de
nomes continua idêntico, nenhum candidato do teste tem esse sufixo, e
`langgraph-api-ext` passa em *runtime* e falha no lint, sem que nada o diga.

## 4. Os outros importantes

**O modo `aviso` engole o achado bloqueante da própria validação (6).** Como o
`validar_golden` devolve sempre um problema, a validação nunca sai vazia e o
`continue` descarta **também** o «o dataset golden `X` não existe». Caso
concreto: `golden/vendedor/v2` escrito igual nos dois ficheiros — o
`_coerencia` compara-os entre si, e dois erros iguais concordam — dá um aviso
`golden_kam_040`, indistinguível do esperado, e a vertical vai a produção a
apontar para nada. Aqui o `aviso` não está a adiar uma fonte que falta: está a
tapar um erro de configuração.

**O *gate* 3b aceita um gate sem `golden`, e o AGR sai com 5.** O
`forma_de_gates` exige `validacoes` e nunca `golden`; o `chaves()` só recusa
chaves **desconhecidas**. O `GateDaVertical.golden` é obrigatório no Pydantic.
Caso concreto: uma entrada `servicos: { validacoes: { golden: { modo: aviso,
credor: KAM-040 } } }` passa o `canon_lint check` em verde no CI e põe o
contentor a reiniciar com código 5 em produção. É exactamente a classe de erro
que este lint existe para apanhar **antes** do *deploy*, e não depois.

**O teste de arquitectura mede `registo/` e conclui sobre o serviço.** O
`contexto.py` do KAM-025 tem `VERTICAIS: Final = ("vendedor", "servicos")` e na
linha 193 recusa qualquer outra. A *docstring* do
`test_uma_vertical_com_um_id_inventado_carrega_e_resolve` diz que a agnosticidade
do registo «é exactamente o que a vertical `catalogo` dos módulos de entrada
(KAM-118) vai precisar» — não é. Uma invocação com `vertical: catalogo` é
recusada à porta do `/internal/turn` antes de o `resolve` chegar a existir.
Acrescentar uma vertical continua a ser editar quatro sítios
(`contexto.py`, `chr/contrato.ts`, `fluxo_piloto.py`, dicionário §3.2); o
registo não reduziu esse número e o *diff* não o registra. E o §5.4(d) do
`docs/tecnica/02` pede «*grep* de nomes de vertical em `core/` = 0», uma
propriedade que este teste não mede e que o AGR já não tem.

**O `psycopg2-binary` não é apanhado por nenhum dos dois lados.** As entradas
`psycopg` e `psycopg-pool` são `match: exact` e nada casa por fronteira
`psycopg`, pelo que `psycopg2-binary` — distribuição real, com a extensão C
LGPL — não bate em entrada nenhuma. O `requirements/runtime.in` afirma por
extenso que «`psycopg` e `psycopg2-binary` são LGPL e estão **PROIBIDAS**».
Caso concreto: `pip install psycopg2-binary` num contentor de depuração instala
LGPL, o `exigir_sbom_mit` cala-se, e o
`test_a_guarda_cobre_todas_as_entradas_pypi_da_lista_de_bloqueio` reporta
cobertura total — porque compara a tabela com o ficheiro, e o ficheiro é que
tem o buraco. A correcção é no `tools/blocklist.yaml` e na tabela espelhada.

## 5. O que a revisão procurou e **não** encontrou

Oito áreas foram varridas por pedido. Onde não encontrei nada, está dito.

**(5) O isolamento de *tenant* no `resolve`, e as etiquetas da métrica.** Nas
etiquetas **não encontrei caminho nenhum** por onde um identificador chegue: a
lista fechada é de dois valores, a gramática `^[a-z][a-z0-9_]{1,62}$` recusa um
UUID pela forma, e o teste passa-lhe um `tenant_id` a sério. (O problema da
métrica é outro, e é o §1.) Quanto ao RLS: **não encontrei leitura de
entitlement sob RLS neste *diff*** — o `ler_entitlement` é uma porta injectada e
ninguém a liga em produção. A caixa do DoD está marcada `parcial` com essa razão
escrita, e **concordo com essa leitura**: a primeira metade está medida, a
segunda é do chamador.

**(6) O Pydantic e o ADR-L001.** Julgando a nota do §4 como ela está: **não
encontrei violação do `specs/01` §5**. Aquele exige *superseding* explícito para
ADRs **canónicos**, e o ADR-L001 é local; mais importante, a nota não revoga
decisão nenhuma — o Starlette fica, o `/internal/turn` continua a validar o
corpo à mão, e o que a nota registra é que a **premissa** (o custo de
acrescentar o Pydantic) caducou com o KAM-026, que é verdade e verificável no
`runtime.txt`. A linha 1.2 do controlo de versões diz o mesmo e acrescenta que o
§5 não se reverte, com a razão. A única reserva é de forma: a linha **Decisão**
do §4 não ganhou marca nenhuma, pelo que quem lê o §4 a correr lê «o Pydantic é
uma dependência compilada a fixar com *hash* por plataforma» e não chega à nota.

**(7) O `langgraph==1.2.17` no fecho de *runtime*.** **Justifica-se.** A
validação (3) tem de ler os nós de um `CompiledStateGraph`, e um teste de
contrato contra um objecto inventado provaria apenas que o `nos_do_grafo` lê o
próprio duplo — o argumento escrito no `runtime.in` é correcto, e o
`TestContratoDoGrafo` constrói mesmo `StateGraph(...).compile()`. Conferi o
fecho e as licenças eu mesmo: os três pacotes novos são MIT no
`ci/supply-chain/licencas.yaml`, e as transitivas que eles pedem (`httpx`,
`orjson`, `websockets`, `langchain-protocol`, `xxhash`, `pydantic`,
`langchain-core`) estavam **todas** já fixadas com *hash* no `runtime.txt`, que
tem 47 pinos. Duas ressalvas, nenhuma bloqueante: o
`docs/tecnica/evidencia/E4_Stack_Licencas.md` §2.6 — documento de referência do
próprio bloco — continua a dizer «langgraph 1.2.14, 2026-10-06», e o
`licencas.yaml` subiu para 1.2.17 e **mudou a `fonte` para deixar de o citar**,
o que resolve o lint e não a evidência; e o `langgraph-sdk` é, por admissão da
própria entrada, «o cliente do **Server**» que o ADR-002 veda, admitido por não
haver caminho de egresso — defensável, mas não ganhou nota no E4 nem entrada de
decisão em sítio nenhum.

**(8) A emenda 1.35.** As três divergências estão decididas **a favor da fonte
certa** pela ordem do `specs/01` §5, e verifiquei cada uma: o
`valor_max_pedido_minor` por fonte 3 sobre 6 e 7, com a emenda 1.13 já no
caminho (e é verdade que um `vendedor.yaml` escrito à letra do §5.1 falhava o
*gate* 3b no nível 1 — confirmei que `valor_max_pedido_kz` não está no
`CHAVES_DE_LIMITE`); o `registry/gates.yaml` por fonte 6 sobre fonte 7; e o
`payment.manual_confirmed`, que é cumprimento do §3.5 e não decisão deste
ticket. **As onze tools não roubam escopo ao KAM-028: eram pré-requisito.** O
que entrou é o **nome**, e sem o nome no dicionário o *gate* 3b trata cada tool
de `registry/vendedor.yaml` como achado de nível 1 — a prova está no próprio
*diff*, onde o `test_tools_e_parametros` do `canon_lint` tinha `book_slot` como
«a tool fora do dicionário» e teve de mudar de negativa. O que ficou de fora é o
que é do KAM-028: classe, versão, confirmação e modelo Pydantic — nenhum entrou.

**(2) O `grafos=` e o `checkpointer`.** **É decisão defensável, não escopo em
falta**, e o argumento escrito é o correcto: ligar o `resolve` à porta hoje
trocava um 503 (`GrafoNaoRegistadoError`) por outro 503 (o alvo de `graph` não
resolve) e punha uma leitura de entitlement no caminho de cada turno, para
nada. O `checkpointer` tem a mesma forma: não há grafo que o receba, e um
`compile(checkpointer=...)` sem grafo não existe. O que **não** está bem é o
rasto (§3): os comentários do KAM-025 continuam a apontar para este ticket.

**(1) As três validações em modo `aviso`.** A letra exige o que está no §2: o
critério 1 pede as seis, o critério 8 isenta **só** a (6), e os critérios 2 e 3
repetem «reprova o arranque» para a (1) e a (3) por sua conta. **A leitura certa
é que as três em `aviso` não cumprem a letra**, e o autor diz o mesmo — marcou
1, 2 e 3 como `parcial` e escreveu a inversão de dependências por extenso, com
as três alternativas pesadas. Não decido por ti se o critério se emenda ou se o
ticket fica `parcial`: o que a revisão acrescenta é que **a escolha do
mecanismo é separável da escolha do modo**. Hoje o `aviso` suprime a validação
inteira; se suprimisse só o «a fonte não existe», os critérios 2 e 3 ficavam
satisfeitos à letra **sem** mudar nada no `gates.yaml`, e os dois achados do §2
e do §4 desapareciam juntos. É o caminho que recomendo, e torna a questão da
letra discutível em vez de estrutural.

**(3) A guarda do SBOM.** Encontrei duas divergências e um buraco partilhado
(§3 e §4). O que **não** encontrei: nada de errado na metade dos nomes — a
correspondência por fronteira do `egresso.py` (`(?<![a-z0-9])…(?![a-z0-9])`) e a
do `lint_arch` (`(?:^|[^a-z0-9])…(?:[^a-z0-9]|$)`) são equivalentes nos casos
que importam, e a normalização PEP 503 não fabrica falsos positivos.

**(4) O teste de arquitectura.** Prova menos do que diz, e o que diz a mais
está no §4. O que está **bem** e vale registar, porque é o controlo que o
EPIC-02 ensinou a exigir: o `modulos()` faz
`assertGreaterEqual(len(ficheiros), 3, "não há fonte para ler")`, pelo que o
teste **não** passaria com o código apagado. A regra é igualdade e não
subcadeia, com a razão escrita (e as duas versões erradas anteriores também, o
que é honesto). O limite que fica: três ficheiros **vazios** passam, porque o
controlo conta ficheiros e não conteúdo.

## 6. Menores e nice-to-have

| # | Achado | Natureza |
|---|---|---|
| 12 | O `pyproject.toml` do AGR não declara `pydantic`, `yaml` nem `langgraph`, que o código agora importa directamente; chegam por transitividade. Um `langchain-core` que deixe de pedir `PyYAML` tira-o do `runtime.txt` sem *gate* nenhum objectar, e o AGR morre com `ModuleNotFoundError: yaml` **antes** de qualquer guarda — sem 2/3/4/5 para diagnosticar | defeito |
| 13 | O cabeçalho de `specs/02` continua «Versão 1.34 — PROPOSTA» enquanto o §6 e o `canon/dicionario.yaml` já vão em 1.35. O próprio parêntese diz que espelha o §6 | defeito |
| 14 | O comentário `superficies` de `ci/canon-lint.yaml` continua a dizer «**DUAS** formas» e «os ficheiros das verticais vêm com o EPIC-03». As duas falsas depois deste *diff* | defeito |
| 15 | O `RegistoInvalidoError` promete «todos os problemas e não o primeiro»; um YAML ilegível aborta por `FicheiroIlegivelError` antes de a lista se formar. Caso: `vendedor.yaml` com YAML inválido **e** `servicos.yaml` com uma chave de limite inexistente dão dois *deploys*, que é o que a *docstring* diz existir para evitar | defeito |
| 16 | O `_negar` valida o motivo com `assert`; com `python -O` a guarda desaparece. É a última linha entre a lista fechada e uma etiqueta de cardinalidade aberta | segurança |
| 17 | `MOTIVOS_DE_RECUSA` existe **duas** vezes no mesmo pacote com conteúdos diferentes (`metricas.py`: `ritmo`/`tecto_do_tenant`/`invocacao_invalida`; `registo/__init__.py`: `sem_entitlement`/`vertical_desconhecida`). Quem ligar o registo às métricas importa um e valida contra o outro | simplificação |
| 18 | O `carregar` lê cada ficheiro **duas** vezes (`ler_yaml` no `_ler_pasta`, outra no `_montar`): oito leituras para quatro ficheiros. Passar o documento já lido ao `_montar` tira ~6 linhas e uma leitura por ficheiro | simplificação |
| 19 | `METRICA_NEGADAS` não está no `__all__` apesar de ser o nome que os testes e qualquer futuro chamador usam | simplificação |
| 20 | O `golden/` não é copiado para a imagem (o `Dockerfile` copia só `registry`) e a raiz do golden é `pasta.parent` = `/app`. No dia em que o `golden` passar a `bloqueio` o contentor precisa de um `COPY golden` que ninguém registou | defeito |
| 21 | O `test_neste_ambiente_a_guarda_passa` afirma algo sobre o interpretador **inteiro**: qualquer pacote de desenvolvimento cujo nome case `minio`, `n8n`, `dify`, `typebot` ou `litellm` por fronteira põe a bateria a vermelho sem haver defeito no AGR | defeito |
| 22 | A emenda 1.35 registra `resolve` e **não** o `Resolucao` que ele devolve, embora isso seja uma mudança ao `resolve(ctx) -> Vertical` do §5.2 — a única decisão deste ticket entre duas fontes que não entrou no dicionário onde todas as outras entraram. A decisão está certa (o critério 6 obriga-a); falta o registo | defeito |
| 23 | O contrato `Vertical(Protocol)` com `build_graph(deps)` que os *Detalhes Técnicos* pedem e que a emenda 1.35 canoniza **não existe em código**: `AmbienteDoRegisto.construir_grafo` é um `Callable` e `deps` não aparece em sítio nenhum. O KAM-031 inventa-o | nice-to-have |
| 24 | O `AmbienteDoRegisto.do_repositorio` fixa `catalogo=None` e `construir_grafo=None` sem porta para os passar, e o `__main__.py` **descarta** as verticais carregadas (`_, _, adiadas`). Quem ligar o KAM-031 mexe nas duas coisas e revalida o registo uma segunda vez | nice-to-have |
| 25 | O `resolve` faz uma leitura de entitlement **por turno**, sem cache nem costura para a ter. Com o *lock* por conversa à volta, é uma ida à base dentro da secção crítica. O autor nota o custo ao justificar não ligar; o desenho não deixa onde o resolver | nice-to-have |

## 7. O que exijo corrigido antes do *merge*

| # | Achado | Porquê não espera |
|---|---|---|
| 1 | `agr_registry_denied_total` não existe em `metricas.py`; o `resolve` levanta com o objecto real, e o teste prova-o contra um duplo | O critério 6 está marcado «satisfeito» e não está. Correcção: a métrica, a etiqueta `motivo` e a entrada em `_AJUDA` no `metricas.py`, e o teste a contar com `MetricasDoAgr` e não com a espia |
| 2 | O `aviso` deixa de ser emitido quando o credor liga a fonte, e a linha sobrevive | Converte, sem aviso nenhum, os critérios 2 e 3 em «aviso» permanente. Correcção: separar «fonte ausente» de «achado» |
| 3 | `validar_fase` deixa passar `phase: D` com qualquer `KAMBA_FASE` não vazio ≠ `piloto` | A *docstring* cita a regra do canon e implementa o contrário; o AGR não tem outra guarda de fase |
| 4 | O `aviso` do `golden` tapa o «o dataset não existe» | A mesma correcção do 2 fecha-o |
| 5 | A evidência do critério 8 mede a linha do `tools`, não a do `golden`, e o `gates.yaml`/`README.md` afirmam o que o `shortcut:` já desmente | É o critério que o ticket nomeia como seu. Correcção: alinhar a prosa e medir o caso do `golden` |
| 6 | A isenção do `ci/canon-lint.yaml` cita um teste de arquitectura que não existe | Uma isenção de *gate* paga com uma promessa. Correcção: escrever o teste ou corrigir a razão |
| 9 | O *gate* 3b aceita um gate sem `golden`; o AGR sai com 5 | CI verde, produção a reiniciar. Correcção: exigir a chave no `forma_de_gates` |
| 10 | A paridade do SBOM não chama o `satisfies_floor`, e há duas divergências fora da amostra | Correcção: chamar o `lint_arch` como oráculo, e acrescentar `1.83` e `1.84.0.post1` |
| 11 | `psycopg2-binary` não é apanhado por nenhum dos dois lados | É LGPL em produção com os dois controlos a dizer que está tudo bem |

Os achados 7, 8, 12 a 14 e 22 são de prosa e de declaração, e cabem no mesmo
PR sem custo. Os restantes são declaráveis.

## 8. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial. Revisão adversarial independente do KAM-027, com `code-review high` e `ponytail-review` na mesma passagem. 25 achados; veredicto **REPROVADO**, com nove exigidos antes do *merge*. | Revisor adversarial |
