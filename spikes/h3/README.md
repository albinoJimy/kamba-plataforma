# `spikes/h3` — harness do spike de coexistência (KAM-100)

**Descartável.** Mede se a coexistência da app WhatsApp Business com a Cloud API
funciona em três números +244, e depois apaga-se. **Não é produto e nunca é
integrado nos serviços**: o GWY real é o KAM-013, o CHR é o KAM-014 e o
Embedded Signup em código é o KAM-016.

| Ficheiro | O que é |
|---|---|
| `es_coexistencia.html` | A página mínima de Embedded Signup v4 em modo de coexistência |
| `receptor.py` | O receptor de *webhook*: valida a assinatura, extrai e grava |
| `assinatura.py` | O `X-Hub-Signature-256` sobre o corpo **bruto** |
| `extrair.py` | Do corpo da Meta para as linhas do registo; descarta o resto |
| `registo.py` | A *allowlist* de **18** chaves com forma exacta por valor, e o JSON-lines |
| `codigos.py` | O 2593109, numa fonte so: o `extrair` e o `tabela` liam-no cada um da sua copia |
| `tabela.py` | A tabela N1–N3 a partir dos JSON-lines |
| `fixtures/gerar.py` | Gera `fixtures/n1_n3.jsonl`: N1 nominal, N2 com o erro 2593109, N3 com sincronização > 24 h |
| `protocolo_operador.md` | A folha que o operador humano preenche, uma por número |
| `smoke.py` | Ida e volta **real** contra o processo: levanta o receptor numa porta e faz pedidos HTTP |
| `tests/` | **106** ensaios. **Nenhum portão os corre** — ver «Os ensaios», abaixo |

---

## Correr

Dois segredos, os dois do cofre e nenhum do repositório. Sem eles o receptor
**recusa arrancar**: um receptor que valide com segredo vazio aceita o que
qualquer pessoa assinar com segredo vazio.

```bash
export KAMBA_H3_APP_SECRET='<do cofre>'
export KAMBA_H3_VERIFY_TOKEN='<do cofre>'
export PYTHONPATH='spikes/h3;libs/py-core/src'
python spikes/h3/receptor.py --porta 8787 --destino eventos.jsonl
```

```bash
python spikes/h3/tabela.py eventos.jsonl
```

O `libs/py-core/src` no `PYTHONPATH` é por causa do `id_opaco` canónico
(`docs/logs.md` §2.1). Não se reimplementou aqui de propósito: duas cópias de um
resumo divergem, e um `ImportError` à cabeça é melhor do que um receptor que caia
para identificadores em claro.

Os ensaios precisam também de `tools/`, pelos padrões de PII canónicos:

```bash
PYTHONPATH='spikes/h3;tools;libs/py-core/src' python -m unittest discover -s spikes/h3/tests -t spikes/h3
```

E o ida-e-volta real contra o processo, que é o que mostra que a **ordem** das
operações dentro do `do_POST` está certa — os ensaios de unidade exercitam as
funções, este exercita o receptor:

```bash
PYTHONPATH='spikes/h3;libs/py-core/src' python spikes/h3/smoke.py
```

---

## As três propriedades que isto tem de ter certas

### 1. A assinatura é sobre o corpo bruto

`E1` §5, de fonte primária: `X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo
bruto com o App Secret>`.

A implementação errada é `hmac(json.dumps(json.loads(corpo)))`, e é um
***fail-open* silencioso**: a assinatura passa a autenticar uma **família** de
cadeias de bytes em vez da cadeia que chegou. Quem capture um par
`(corpo, assinatura)` legítimo pode reordenar chaves, mudar espaços ou trocar
`á` pelo caractere, e a assinatura continua a validar.

`verificar` recebe `bytes` e não tem caminho que aceite uma árvore já
descodificada. `tests/test_assinatura.py::TestCorpoBruto` prova-o com cinco
pares de bytes diferentes e árvore igual — e escreve lá a implementação **errada**
para mostrar que ela aceitaria todos, que é o que torna o ensaio não-vacuo.

E a **ordem** é produto: `json.loads` corre depois da verificação, e há um ensaio
em que um corpo assinado mas ilegível tem de passar a assinatura e falhar só no
descodificador.

### 2. O registo não leva conteúdo, e isso mede-se pela forma do valor

Uma guarda por nome de campo fica verde com uma mensagem inteira num campo
chamado `nota`. Por isso `registo.PERMITIDOS` não diz só que chaves passam: diz
a **forma exacta** de cada valor, e um valor fora da forma faz `ConteudoRecusado`
em vez de ser aparado.

Os telefones **descartam-se, não se resumem**: um móvel de nove dígitos tem 10^8
hipóteses úteis e um resumo sem chave inverte-se por enumeração (ADR-010,
`docs/logs.md` §2.1). No lugar fica o rótulo `N1`–`N3`, cuja correspondência vive
**fora do repositório**.

O `wamid` passa por `id_opaco` porque é de alta entropia — e em claro leva o
número do interlocutor em base64, que é o caminho que o `id_opaco` existe para
fechar.

`tests/test_privacidade.py` mede a forma dos valores, não as chaves, e corre
primeiro um **canário**: os mesmos detectores sobre a **entrada**, onde têm de
encontrar as três formas. Sem o canário, um detector que devolvesse zero passava
tudo.

### 3. Um zero não é um «não»

«Não recebi o `FINISH`» e «não liguei o receptor a tempo» produzem os mesmos zero
eventos e têm conclusões opostas. A tabela escreve `NAO MEDIDO` e **nunca `N`**,
**e não há excepção.** A primeira versão abria uma para a coluna do *echo* da
API — «houve *echoes* e nenhum é nosso» — e isso não é prova de ausência: só o
seria se tivéssemos enviado ≥ 1 mensagem pela API, e nada nos JSON-lines diz que
enviámos. Com o `nossos.txt` esquecido, a célula afirmava «uma mensagem da API
não gera *echo*» sobre zero envios. O `N` dessa coluna fecha-se cruzando com o
passo 4.2 da folha do operador, que é quem registra o envio.

---

## Os ensaios, e o portão que não existe

**Medido: `spikes/` não entra em portão nenhum.** Não está nos padrões de
`ci/thresholds.yaml` (`services/*/src/**`, `packages/*/src/**`, `libs/*/src/**`,
`tools/**`), não está no `SUITES_DE_TOOLS` do `Makefile`, que descobre suites por
`tools/*/tests/test_*.py`, e não é nomeado em `.github/workflows/ci.yaml`.

Logo os 106 ensaios são **evidência de um instante** — o que o PR do KAM-100
registar — e não uma guarda contínua. A alternativa era pô-los em
`tools/<nome>/tests/`, onde o gate 4 os corria, e não se fez por duas razões:

1. o bloco do ticket diz que o harness é **descartável** em `spikes/h3/`, e um
   artefacto descartável cuja remoção avermelha o gate 4 de todos os PRs deixa de
   ser descartável;
2. ligá-los a um portão muda o que o gate 4 passa a exigir, e **alterar o
   critério de um portão é decisão do fundador**. Entrega-se a medição; a ligação,
   se a quiser, é dele.

O mesmo vale para `scripts/`, onde vive o `validar_evidencia.py` com os seus 27
ensaios. **A diferença entre os dois pesa na decisão, e está escrita:** este
*harness* é descartável, e o validador é **permanente** e citado nos «Testes
Requeridos» de quatro tickets — pelo que o argumento do descartável não se lhe
aplica. Os dois ficam devolvidos no §6 do
`docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md`, item 7.

---

## O que este harness não faz

| Não faz | Porquê |
|---|---|
| Trocar o `code` por um *token* | Precisa do App Secret, e é servidor-a-servidor. O operador copia o `code`; o *onboarding* real é o KAM-016 |
| HTTPS | O túnel é do operador, e `E1` §5 exige certificado válido — um auto-assinado não serve |
| Subscrever campos | Faz-se uma vez no App Dashboard. A folha do operador lista os cinco |
| Contar as 20 conversas de controlo | Conta-se na app do dono. O harness conta o que recebeu, não o que devia receber |
| Decidir H3 | Nenhuma decisão é automática. É do fundador, com dono e data |

---

## Apagar

Os JSON-lines, o `rotulos.json` e o `nossos.txt` vivem no portátil do operador,
**nunca** no repositório, e apagam-se em ≤ 30 dias. Esta pasta apaga-se quando H3
estiver decidido — e nada depende dela: nenhum serviço a importa e nenhum portão
a corre.
