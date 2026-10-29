# ANÁLISE 39 — Revisão adversarial do KAM-047 (módulo `servicos`)

| Campo | Valor |
|---|---|
| Ticket | KAM-047 — Módulo `servicos`: serviços, recursos, disponibilidade, marcações e holds |
| Revisor | Subagente `general-purpose`, que recebeu **o diff e os requisitos** e não o raciocínio de quem escreveu o código |
| Data | 28 de Outubro de 2026 |
| Achados | **22**, mais 8 mortos |
| Veredicto | 6 bloqueavam o merge, 11 a corrigir antes de fechar, 5 notas. **Corrigidos: 20.** Dois ficam declarados, com credor |

Uma revisão adversarial por ticket, com os instrumentos todos na mesma passagem
(decisão do fundador, Outubro de 2026). Lançada **assim que o diff existiu** e
não no fim: correu em paralelo com a *self-validation*, e a árvore mexeu
enquanto ela lia — três dos achados que bloqueavam merge já estavam corrigidos
quando ela respondeu, e o revisor disse-o em cada um. É o comportamento certo:
cada `CONFIRMADO` verificou-se outra vez contra a árvore que vai fundir.

---

## O que esta revisão mostrou sobre o ticket

Os seis achados que bloqueavam o merge dividem-se em dois grupos, e a divisão
diz mais do que a contagem.

**Três eram do estado do diff e já estavam mortos quando a revisão respondeu**
(A1 *typecheck* vermelho, A2 parâmetros trocados na suite, A3 segredo verificado
tarde demais). Os três tinham sido encontrados pela *self-validation* a correr ao
mesmo tempo — o que é exactamente o desenho: as duas estações correm em paralelo
e a revisão não espera pela primeira.

**Três eram defeitos reais que nenhuma das minhas provas tocava**, e os três têm
a mesma assinatura: **uma operação sem chamador e sem teste**. O A4 nomeia-a —
as 500 linhas do `criarServicosModule` não eram corridas por nada —, e o A5 e o
A12 são o que estava escondido lá dentro. O A5 é o pior do ticket: o
`rescheduleBooking` usava o `SQL_CRIAR_HOLD`, que escreve `'hold'` literal, e
por isso **degradava uma marcação confirmada num hold de dez minutos** — quem
remarcasse e não voltasse a carregar no botão perdia a marcação em silêncio,
expirada pelo varrimento.

A lição, que vira teste e não nota: **uma função sem chamador não é código
entregue**. O `servicosComPortasReais` existe agora para que haja um sítio onde
as sete operações são montadas com as portas verdadeiras, e o
`servicos.modulo.test.ts` corre-as todas contra um cliente de ensaio que regista
as consultas por ordem.

---

## Os achados

Numeração do revisor. «Estado» é o que ficou depois da verificação do achado
contra a árvore que vai fundir.

| # | O defeito | Veredicto | Estado |
|---|---|---|---|
| **A1** | `typecheck` vermelho: `confirmBooking` e `rescheduleBooking` devolvem `comTenant(...)` sem anotar o genérico | CONFIRMADO | **Corrigido** antes da resposta da revisão (`comTenant<Resultado<T>>`) |
| **A2** | O `SQL_OCUPADO` escrevia `$2` antes de `$1`, e o conversor da suite substitui `$n → %s` **pela ordem de aparição**: a prova corria com os argumentos trocados | CONFIRMADO | **Corrigido**, e o conversor passou a **recusar** uma consulta com os `$n` fora de ordem. O código de produção estava certo — o `pg` resolve por índice; quem estava errado era a prova |
| **A3** | `lerSlotId` verificava o segredo **depois** das recusas por forma: um cofre vazio devolvia `null` para tudo, indistinguível de entrada má | CONFIRMADO | **Corrigido**: o segredo verifica-se primeiro. Uma falha de configuração é alta e imediata |
| **A4** | As 500 linhas das sete operações **sem teste e sem chamador**: os critérios 3, 4, 5 e 7 estavam provados só ao nível do SQL | CONFIRMADO | **Corrigido**: `servicos.modulo.test.ts` (27 casos) e `servicosComPortasReais` |
| **A5** | `rescheduleBooking` degradava uma marcação **confirmada** num hold de 10 min, que depois expirava sozinho | CONFIRMADO | **Corrigido**: `SQL_REMARCAR` leva o estado da original; quem já confirmou não volta a confirmar por ter mudado de hora. Dois testes |
| **A6** | O `p99 ≤ 60 s` do critério 3 não está implementado nem medido, e só o `kamba_app` pode varrer | CONFIRMADO | **Declarado, não corrigido.** Ver abaixo |
| **A7** | `holdSlot` nunca reconferia o *slot* contra a agenda: um `slot_id` assinado continuava a marcar depois de a PME apagar a regra ou desactivar o recurso | CONFIRMADO | **Corrigido**: `SQL_SLOT_OFERECIVEL` antes de cada escrita, com quatro casos medidos |
| **A8** | A rotação de segredo que o `slots.ts` prometia não existia | CONFIRMADO | **Corrigido o texto**, que é onde estava o defeito: o ficheiro descrevia um anel que não tem. A consequência da rotação fica escrita; o anel é do KAM-010 |
| **A9** | `getAvailability` ignorava o `ateAt`: quem pedia «esta manhã» recebia a tarde | CONFIRMADO | **Corrigido**: o `slotsLivres` passou a ter limite superior, e o *slot* tem de **caber** dentro dele |
| **A10** | O `generate_series` perdia dias: uma janela que atravesse a meia-noite sem chegar a 24 h não via o segundo dia | CONFIRMADO | **Corrigido**: a série corre sobre `date`. Teste próprio, que não existia porque a suite nunca corria a `SQL_GRELHA` com um intervalo de utilizador |
| **A11** | Não há ligação entre serviço e recurso: `getAvailability(servico)` oferece horas de **todos** os recursos | CONFIRMADO | **Declarado, não corrigido.** Ver abaixo |
| **A12** | `rescheduleBooking` não verificava entitlement | CONFIRMADO | **Corrigido**: verifica, e **não** consome — remarcar move uma marcação, não cria outra |
| **A13** | `rescheduleBooking` trancava só o recurso **novo**: duas remarcações cruzadas fechavam um ciclo | PLAUSÍVEL | **Corrigido**: trancam-se os dois, **por ordem do identificador** |
| **A14** | Quatro referências documentais penduradas, uma dentro de um `COMMENT ON SCHEMA` | CONFIRMADO | **Corrigido**: nasce `docs/evidencia/KAM-047-servicos.md`, o `tecnica/03` §5.7 passa a existir, e as dívidas 134–137 entram |
| **A15** | O `base.py` justificava a suite com um teste que não existia, e o `EXERCITADAS` era código morto | CONFIRMADO | **Corrigido**: `test_contrato.py` corre **todas** as consultas do módulo contra a base e confronta a lista nos dois sentidos |
| **A16** | O tecto do varrimento podia esconder horas: uma chamada libertava 100 e os restantes continuavam a ocupar | CONFIRMADO | **Corrigido**: o varrimento repete até esgotar, com tecto de voltas |
| **A17** | `confirmBooking` alterava a linha de outro contacto **antes** de verificar de quem era | CONFIRMADO | **Corrigido**: o `contact_id` entra no `WHERE`, e a distinção `HOLD_EXPIRED`/`NOT_FOUND` sai da leitura que já existia |
| **A18** | `cancelBooking` não emitia evento: o KAM-048 enviava um *template utility* pago a lembrar o que o cliente cancelou | CONFIRMADO (nota) | **Corrigido**: emite `booking.cancelled`, com domínio fechado de motivos |
| **A19** | O `slot_id` tem ~190 caracteres e nada o media contra o limite do `id` de uma linha de lista | PLAUSÍVEL | **Guardado**: `MAXIMO_DO_SLOT_ID = 256` e o `derivarSlotId` lança. O limite exacto continua **NÃO VERIFICADO** — o `E1` §7 confirma as 10 linhas e não fala do `id` |
| **A20** | Inexactidões nas justificações escritas no código (seis campos descritos como cinco; uma classe exportada que nunca era lançada) | CONFIRMADO | **Corrigido** |
| **A21** | Um identificador malformado subia como excepção de driver em vez de `VALIDATION_ERROR` | CONFIRMADO | **Corrigido** nas quatro operações, com teste |
| **A22** | `getAvailability` escreve (o varrimento emite no outbox dentro do que o chamador lê como leitura) | CONFIRMADO (nota) | **Declarado**: é escolha deliberada, e a consequência passou a estar escrita |

---

## Os dois que ficam, e porquê

**A6 — o `p99 ≤ 60 s` do critério 3.** O mecanismo está feito e medido: a função
liberta, emite, é idempotente e respeita o tecto. O que falta é a **cadência** de
quem a chama, e isso é um agendador — que este repositório não tem (KAM-071). O
varrimento oportunista garante uma propriedade mais fraca e honesta: o intervalo
está livre para o próximo que pergunte. Num tenant sem tráfego nocturno, fica
ocupado até ao pedido seguinte. **A caixa do critério 3 fica vazia**, e a razão
é esta. O revisor escreveu-o bem: «um critério de aceitação deste ticket não se
satisfaz delegando-o noutro ticket sem o ticket mudar».

**A11 — a ligação entre serviço e recurso.** Não existe no esquema, e não existe
em fonte nenhuma: nem o DDL *proposta* do bloco, nem o `tecnica/02` §8.3, nem o
`00` §4 nomeiam uma tabela de ligação. Acrescentá-la seria desenhar esquema que
o ticket não especifica. Fica declarada — no `tecnica/03` §5.7, no
`dividas-documentais.md` e na verificação do bloco —, porque a alternativa era a
que o revisor nomeou: **uma omissão de esquema transformada numa oferta que o
backend garante criptograficamente**. A decisão de a fechar, e de como, é de
quem desenhar a vertical Serviços por inteiro.

---

## Os oito mortos, e o que os matou

Um `MORTO` com evidência vale tanto como um achado: senão volta na próxima
auditoria e paga-se outra vez.

| # | A suspeita | O que a matou |
|---|---|---|
| **M1** | A tranca por recurso viola a letra do critério 1 («não por código aplicacional»)? | **Não.** Uma tranca serializa e não recusa: com a restrição removida e a tranca no lugar, as tentativas entram **todas** — é o passo de canário. E o revisor verificou **todos** os caminhos que acrescentam uma entrada ao índice parcial: só o `SQL_CRIAR_HOLD` o faz, e os seus chamadores trancam antes |
| **M2** | A chave do advisory lock colide com a do KAM-018? | O prefixo `'servicos:'` muda a cadeia antes do *hash*; os espaços só coincidem por acaso de 64 bits |
| **M3** | Canonicalização de base64, confusão de tenant, reutilização entre serviços no `slot_id`? | A ida e volta do base64url fecha a primeira; o segredo derivado por tenant a segunda; o `service_id` no corpo a terceira. As três com teste |
| **M4** | O `INVENTARIO_SERVICOS` está incompleto? | Contado coluna a coluna contra o DDL: 9/9, 5/5, 8/8, 13/13. E a asserção é de **conjuntos** nos dois sentidos |
| **M5** | O `DROP CONSTRAINT` do canário deixa o esquema reparado às escondidas? | Era a suspeita mais forte do revisor — ele esperava que o `ADD CONSTRAINT` de reposição falhasse por *search_path*. Correu a suite: 34 testes OK, e a asserção `count(*) = 1` sobre o `pg_constraint` corre **fora** do `finally` |
| **M6** | O payload de `booking.cancelled` cumpre o contrato v1? | `required = [booking_id, motivo]`, `additionalProperties: false`, e o teste confronta por conjunto |
| **M7** | Privilégios a mais, política sem `WITH CHECK`, `GRANT` a `PUBLIC` esquecido? | As quatro políticas têm `WITH CHECK` igual ao `USING`; as duas funções levam `REVOKE ALL … FROM PUBLIC`; o `kamba_app` corre o varrimento **e** o `evt_emitir`, medido |
| **M8** | O *gate* 3b fica vermelho por causa da `0025`? | 17 achados, **todos** na `0024` de outro PR; zero na `0025` |

---

## O que isto diz sobre a fábrica

**Calibração: 22 achados levantados, 20 confirmados e corrigidos, 2 declarados.**
Nenhum foi descartado como ruído. É um número alto para uma revisão só, e a razão
está no A4: a superfície que o ticket pede — as sete operações ctx-first — não
tinha chamador nem teste, e metade dos achados estavam escondidos atrás dessa
lacuna. (Lido à mão a partir desta análise, como o `SKILL.md` §3 manda dizer:
**INDÍCIO**, não um número que o repositório produza.)

**Escapes por portão.** Nenhum dos cinco *linters* documentais, nem o *gate* 8,
nem o *gate* 6 apanhavam o A5, o A7, o A9, o A10 ou o A11 — e nenhum podia: são
sobre comportamento que nenhum teste criava, que é o mesmo padrão dos oito
achados do KAM-013. **Três** deles viraram portão sem *job* novo, que é a forma
que esta casa usa:

- o conversor de `db/tests_servicos/consultas.py` passou a **recusar** uma
  consulta com os `$n` fora de ordem ou repetidos — e apanhou um defeito meu na
  primeira execução depois de escrito;
- o `test_a_lista_de_exercitadas_e_a_do_modulo` passou a exigir que **cada**
  consulta do módulo seja corrida contra a base, que é o que teria apanhado o
  A10 antes de ele existir.
- o `test_toda_a_suite_de_base_de_dados_e_invocada_por_um_gate` exige que o
  `SUITES` do `gate_bd.py` e as invocações do `ci-8` e do `ci-6` sejam o **mesmo
  conjunto**, nos dois sentidos. Ver abaixo: é o escape que o CI verde escondia.

### O terceiro escape apareceu depois do PR aberto, e com o CI verde

Nenhum dos vinte e dois achados acima o apanhou, e nenhum podia — não é um
defeito de comportamento, é uma **declaração em falta**.

Acrescentei a `tests_servicos` ao `SUITES` do `gate_bd.py` e ao
`correr_suite.py`, corri-a à mão uma dúzia de vezes, e **esqueci-me do alvo
`ci-8` do `Makefile`**, que invoca as suites uma a uma, por nome.

A consequência era exacta e silenciosa: as **1.000 tentativas concorrentes que
provam o critério 1 deste ticket** valiam só na máquina de quem as escreveu. O
*gate* 8 do CI estava **verde**, a suite existia, o `gate_bd.py` sabia correr, e
nada no PR o denunciava. Descobriu-se por acidente — a ler o registo do *gate* 8
de uma corrida verde para confirmar outra coisa, a `tests_servicos` não estava
entre as dezesseis invocadas.

É a mesma classe do `PACOTES_NODE` e do `ci/thresholds.yaml`, com a diferença
que a torna pior: ali um ficheiro que nenhum estrato classifique **falha** o
*gate* 4 de propósito; aqui uma suite que nenhum alvo invoque **passa**.

O portão entra num *gate* que já existe — a bateria do que só o repositório pode
afirmar — e lê o `SUITES` pelo AST em vez de importar o módulo, pelo mesmo
caminho que o *gate* 3b usa para ler as revisões sem as executar. **E a prova de
que morde está feita**: retirada a linha do `Makefile`, o teste falha nomeando a
suite; reposta, passa.
