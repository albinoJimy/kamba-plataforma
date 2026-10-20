"""Conversas: a primeira tabela do caminho do webhook que tem tenant_id (KAM-014).

**A primeira linha e ASCII de proposito, e segue a forma das outras oito.**
O `alembic history` imprime-a, e a suite compara a saida no processo com a do
executavel: um travessao aqui faz as duas divergirem na descodificacao e poe
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` vermelho.

Revisao: 0009
Anterior: 0008

**Porque e que esta revisao existe.** O CHR e o unico sitio onde o `tenant_id`
nasce para o estado do grafo (`docs/tecnica/01` §7.2): a ToolLayer so aceita o
que vier do estado (ADR-002, ADR-012). As duas tabelas de entrada da `0008` nao
tem `tenant_id` por desenho — quando o *worker* registra o que chegou, ainda nao
se sabe de quem e o `phone_number_id` —, e por isso a `conversations` e a
**primeira** tabela deste caminho que o *gate* 6 descobre pela coluna
`tenant_id` e a primeira que leva RLS `FORCE` com a politica `tenant_iso`
(ADR-015). Nao ha entrada em `ci/rls_exceptions.yaml`.

A fonte de cada coisa:

* `conversations` e as suas oito colunas — dicionario §3.13, emenda 1.20
  (KAM-014). O DDL vem do bloco do ticket; a maquina de estados do `mode` vem
  de `docs/tecnica/01` §10.2.
* O dominio de `mode` — `docs/tecnica/01` §10.2 e o DDL do bloco.
* `GRANT SELECT (plano)` ao `kamba_resolver` — o criterio 1 do KAM-014 pede o
  `plano` no `ChannelContext`, e a `0002` concedeu ao resolvedor so
  `tenants(id, tipo, estado)`. O comentario da `0002` antecipa-o por escrito:
  «o CHR nasce no KAM-014 e pode pedir mais uma — o que se faz acrescentando-a
  aqui numa revisao, e nao dando-lhe a tabela inteira».
* `UNIQUE (tenant_id, id)` em `tenant_channels` — nao e o ticket que a pede: e
  o que permite a FK composta de `conversations` para o canal. Ver abaixo.

**A janela de 24 h vive aqui, e isso diverge de um documento.** O
`docs/tecnica/01` §6.2 punha `last_inbound_at` e `window_expires_at` em
`contacts`; a `contacts` da `0003` nao os tem, porque segue o ADR-010 e o
KAM-008. A divergencia esta registada na emenda 1.20, e a razao e de desenho e
nao de arrumacao: uma janela por **contacto** nao distingue dois canais do mesmo
tenant, e a janela da Meta e por par (numero do negocio, numero do cliente)
(`evidencia/E1` §4, CONFIRMADO).

**Tres FK, e duas sao compostas com o `tenant_id`.** E o padrao que a `0003`
fixou para a identidade, e aqui vale pelo mesmo motivo: uma conversa nao pode
apontar para um contacto nem para um canal de **outro** tenant, e quem o recusa
e a base, sem depender de o codigo acertar. A do contacto assenta na
`contacts_tenant_contact_uq` que a `0003` ja criou; a do canal **nao tinha onde
assentar**, porque `tenant_channels` so tem `PRIMARY KEY (id)` — e e por isso
que esta revisao lhe acrescenta `UNIQUE (tenant_id, id)`. Sem ela, a FK era
`REFERENCES platform.tenant_channels (id)` e uma conversa do tenant A podia
apontar para um canal do tenant B: a RLS de `conversations` nao o apanha (a
linha e de A e ve-se com o contexto de A) e a de `tenant_channels` tambem nao (a
FK e verificada por dentro). Era um furo de isolamento que nenhum dos dois gates
teria visto.

> **E a `UNIQUE` sobre uma tabela com `FORCE` leva o cuidado da `0003`.** Um
> `ADD CONSTRAINT UNIQUE` constroi um indice, e um indice e uma varredura
> fisica que a politica nao filtra — mas a propriedade «duas linhas iguais sao
> recusadas» passa a depender de uma escolha de implementacao do PostgreSQL em
> vez de estar garantida. O `FORCE` sai e volta na **mesma transacao**, como em
> `docs/isolamento.md` §6, e o intervalo nao se ve de fora. Custa duas
> instrucoes e torna a propriedade independente de como o indice e construido.

**O que esta revisao NAO faz, e e escopo e nao esquecimento:**

* **Nao da `UPDATE (mode)` a `kamba_app`.** O KAM-014 escreve o valor de omissao
  (`bot`, no `INSERT`) e **le** os outros para decidir se a mensagem vai ao AGR;
  as transicoes de modo sao KAM-018, e e esse ticket que pede o privilegio. Um
  `UPDATE (mode)` concedido aqui era a aplicacao a poder silenciar ou
  dessilenciar uma conversa sem o protocolo que o KAM-018 define.
* **Nao cria tabela de *handoff* nem de consentimento.** KAM-019 e KAM-022.
* **Nao impoe retencao.** Como a `0004`, a `0005` e a `0008`: o agendador nasce
  com KAM-071.
* **Nao reaponta `tenants.owner_contact_id` numa fusao.** Continua a ser de quem
  gere tenants, como a `0003` escreveu.
"""

from __future__ import annotations

import json
import os

from alembic import op

import rls

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

#: Quem tem a palavra numa conversa. Lista fechada, imposta por `CHECK`
#: (dicionario §3.13, emenda 1.20; `docs/tecnica/01` §10.2).
#:
#: `bot` e a omissao: uma conversa nasce com o assistente a responder. `dono` e
#: o silenciamento por *echo* da app do dono, `humano` e o *handoff* para o
#: Chatwoot, e `pausada` e o opt-out ou as 24 h sem resposta humana. O KAM-014
#: escreve so a omissao e **le** os quatro; as transicoes sao KAM-018.
#:
#: Os valores vem **ja entre apostrofos**, e isso nao e desleixo: e a unica
#: forma que o *gate* 3b resolve. Ele le o AST da revisao sem a executar e segue
#: `", ".join(<constante de modulo>)` dentro de uma *f-string* — a forma da
#: `0002` e da `0008`. Funcao auxiliar, constante derivada e expressao geradora
#: sao recusadas, cada uma com a sua mensagem (ver `0008`, que pagou as tres).
MODOS = ("'bot'", "'dono'", "'humano'", "'pausada'")

#: A variavel que autoriza um `downgrade` destrutivo. A mesma forma da `0003`.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0009_COPIA"

#: As colunas de `platform.tenants` que o `kamba_resolver` passa a ler, por cima
#: das tres que a `0002` lhe deu (`id`, `tipo`, `estado`).
#:
#: Uma, e e o `plano`: o criterio 1 do KAM-014 poe-no no `ChannelContext`, e o
#: `ChannelContext` responde-se **antes** de haver contexto de tenant — nao ha
#: outro papel que possa ler esta coluna nesse momento. Nao se concede mais
#: nada: o resolvedor continua sem `nome`, sem `nif`, sem
#: `contacto_negocio_enc` e sem `verificado_at`, e ha um teste por cada coisa
#: vedada (`db/tests_isolamento/test_resolver.py`).
#:
#: **Dar o `plano` ao resolvedor nao e inocuo, e fica dito:** e o papel que ve
#: linhas de todos os tenants, pelo que passa a poder ler o plano de qualquer
#: um. Nao e dado pessoal nem segredo (`docs/tecnica/10` trata-o como
#: configuracao comercial) e o `tipo` e o `estado`, que ele ja lia, dizem mais
#: sobre um tenant do que o plano. A alternativa — o CHR abrir uma segunda
#: ligacao de `kamba_app` com contexto, so para ler o plano do tenant que
#: acabou de descobrir — era uma ida a base por mensagem para um valor que a
#: *cache* de 60 s ja guarda.
COLUNAS_DO_RESOLVEDOR_NA_TENANTS = ("plano",)

#: As colunas que o `kamba_app` pode alterar numa conversa.
#:
#: Duas, e sao as duas que o CHR escreve em cada entrada: a janela abre-se com a
#: mensagem que chega. **`mode` nao esta aqui** (e KAM-018) e
#: `last_human_activity_at` tambem nao (e KAM-018/KAM-019): um privilegio
#: concedido «para quando for preciso» e um privilegio que ninguem volta a
#: tirar. `contact_id`, `channel_id`, `tenant_id` e `id` nao se alteram nunca
#: por esta via — mover uma conversa de contacto e de canal e reescrever a sua
#: identidade.
COLUNAS_DA_APLICACAO = ("last_inbound_at", "window_expires_at")

#: As colunas que o `kamba_identity` le e altera, e **so** porque a fusao de
#: contactos (KAM-008) corre na transacao dele.
#:
#: O gancho `onContactMerge` reaponta as conversas do contacto absorvido para o
#: que fica, e corre **dentro** da transacao da fusao, com a ligacao e o
#: contexto de tenant que o modulo de identidade abriu (`docs/identidade.md`
#: §4). Nao ha outro papel nessa transacao: faze-lo por fora quebrava a
#: atomicidade que o KAM-008 garante («se um gancho falhar, nada fica»).
#:
#: **Nao leva `INSERT` nem `DELETE`.** Nao cria conversas — isso e do CHR, com
#: `kamba_app` — e nao apaga nenhuma: quando o contacto que fica **ja tem** uma
#: conversa no mesmo canal, as duas nao se podem fundir numa linha (a
#: `UNIQUE (tenant_id, contact_id, channel_id)` recusa-o), e o que se faz e
#: dobrar os tempos na que fica e deixar a outra pendurada na lapide do
#: contacto absorvido — que continua a existir, com `merged_into` a apontar
#: para quem o absorveu. O §2 do dicionario ja diz «soft delete: estado, nunca
#: `DELETE`»; quem apaga e o `kamba_batch`.
COLUNAS_DA_IDENTIDADE_LEITURA = (
    "id",
    "tenant_id",
    "contact_id",
    "channel_id",
    "last_inbound_at",
    "window_expires_at",
    "last_human_activity_at",
)
COLUNAS_DA_IDENTIDADE_ESCRITA = (
    "contact_id",
    "last_inbound_at",
    "window_expires_at",
    "last_human_activity_at",
)


def upgrade() -> None:
    # ------------------------------------- o que a FK composta do canal precisa
    #
    # O `FORCE` sai e volta na mesma transacao (ver o docstring e
    # `docs/isolamento.md` §6). A instrucao do meio e a unica que pode falhar, e
    # se falhar nada fica — incluindo o `NO FORCE`.
    op.execute("ALTER TABLE platform.tenant_channels NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE platform.tenant_channels "
        "ADD CONSTRAINT tenant_channels_tenant_id_uq UNIQUE (tenant_id, id)"
    )
    op.execute("ALTER TABLE platform.tenant_channels FORCE ROW LEVEL SECURITY")

    # ----------------------------------------------------------- conversations
    op.execute(
        f"""
        CREATE TABLE platform.conversations (
            id                     uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id              uuid        NOT NULL,
            contact_id             uuid        NOT NULL,
            channel_id             uuid        NOT NULL,
            mode                   text        NOT NULL DEFAULT 'bot',
            -- Os tres tempos sao anulaveis: uma conversa pode nascer sem
            -- entrada (um `echo` do dono antes de o cliente escrever) e a
            -- actividade humana so existe depois de um *handoff*.
            last_inbound_at        timestamptz,
            window_expires_at      timestamptz,
            last_human_activity_at timestamptz,
            CONSTRAINT conversations_pkey PRIMARY KEY (id),
            CONSTRAINT conversations_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- Composta, como todas as FK de identidade desde a `0003`: a
            -- conversa e o contacto sao do mesmo tenant, e e a base que o diz.
            CONSTRAINT conversations_contact_fk
                FOREIGN KEY (tenant_id, contact_id)
                REFERENCES platform.contacts (tenant_id, contact_id),
            -- Idem para o canal, sobre a `UNIQUE` acrescentada acima.
            CONSTRAINT conversations_channel_fk
                FOREIGN KEY (tenant_id, channel_id)
                REFERENCES platform.tenant_channels (tenant_id, id),
            CONSTRAINT conversations_mode_ck
                CHECK (mode IN ({", ".join(MODOS)})),
            -- A janela nao pode fechar antes de abrir, e uma janela sem
            -- entrada nao existe: os dois tempos andam juntos.
            CONSTRAINT conversations_janela_ck
                CHECK ((last_inbound_at IS NULL AND window_expires_at IS NULL)
                       OR (last_inbound_at IS NOT NULL
                           AND window_expires_at IS NOT NULL
                           AND window_expires_at > last_inbound_at)),
            -- **Uma conversa por (tenant, contacto, canal).** E o que torna o
            -- `INSERT ... ON CONFLICT DO UPDATE` do CHR idempotente: a
            -- repeticao do mesmo `wamid` nao cria uma segunda conversa.
            CONSTRAINT conversations_tenant_contact_channel_uq
                UNIQUE (tenant_id, contact_id, channel_id)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.conversations.mode IS "
        "'Quem tem a palavra: bot, dono, humano ou pausada (docs/tecnica/01 "
        "§10.2). O CHR escreve so a omissao; as transicoes sao KAM-018.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.conversations.window_expires_at IS "
        "'Fim da janela de servico de 24 h (E1 §4, CONFIRMADO). Vive aqui e "
        "nao em contacts: a janela da Meta e por par numero-numero.'"
    )

    rls.enable_tenant_rls("conversations")

    # ------------------------------------------------------------- privilegios
    #
    # Tabela a tabela e coluna a coluna, sem `ALTER DEFAULT PRIVILEGES`: uma
    # tabela nova nao nasce acessivel (`db/migrations/README.md`, e o
    # `test_nao_ha_privilegios_por_omissao` que o confirma).
    #
    # O `SELECT` de tabela e preciso e nao e generoso: o CHR le a conversa para
    # saber o `mode` — e a decisao de nao a entregar ao AGR — e o
    # `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` exige `SELECT` nas
    # colunas devolvidas. A tabela tem `tenant_id` e RLS, pelo que o que
    # `kamba_app` ve e so o do tenant em contexto.
    op.execute("GRANT SELECT, INSERT ON platform.conversations TO kamba_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DA_APLICACAO)}) "
        "ON platform.conversations TO kamba_app"
    )

    op.execute(
        f"GRANT SELECT ({', '.join(COLUNAS_DA_IDENTIDADE_LEITURA)}) "
        "ON platform.conversations TO kamba_identity"
    )
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DA_IDENTIDADE_ESCRITA)}) "
        "ON platform.conversations TO kamba_identity"
    )

    # O `kamba_batch` tem os quatro verbos, que e o que tem em todas as outras
    # desde a `0001`, porque e quem purga (KAM-071).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.conversations TO kamba_batch"
    )

    # ------------------------------------------- mais uma coluna ao resolvedor
    op.execute(
        f"GRANT SELECT ({', '.join(COLUNAS_DO_RESOLVEDOR_NA_TENANTS)}) "
        "ON platform.tenants TO kamba_resolver"
    )


#: As colunas que a copia logica do `downgrade` escreve, pela ordem em que saem.
COLUNAS_DA_COPIA = (
    "id",
    "tenant_id",
    "contact_id",
    "channel_id",
    "mode",
    "last_inbound_at",
    "window_expires_at",
    "last_human_activity_at",
)

# As duas funcoes abaixo nao recebem argumentos, e nao e por gosto: o *gate* 3b
# le esta revisao sem a correr, e so segue uma chamada cujos argumentos consiga
# resolver. E a mesma razao que a `0003` escreveu para as suas.


def _contar() -> int:
    """Quantas conversas existem."""
    return op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM platform.conversations"
    ).scalar_one()


def _linhas() -> list[dict]:
    """A tabela inteira em JSON: UUID e tempos como texto, `mode` tal e qual."""
    resultado = op.get_bind().exec_driver_sql(
        "SELECT id, tenant_id, contact_id, channel_id, mode, "
        "       last_inbound_at, window_expires_at, last_human_activity_at "
        "  FROM platform.conversations ORDER BY id"
    )
    copia = []
    for linha in resultado:
        copia.append(
            {
                coluna: (None if valor is None else str(valor))
                for coluna, valor in zip(COLUNAS_DA_COPIA, linha)
            }
        )
    return copia


def downgrade() -> None:
    """Reverter apaga conversas, e por isso o `downgrade` pergunta primeiro.

    O que se perde nao e um registo de passagem: e a janela de 24 h e o modo de
    cada conversa. Perder o modo e o pior dos dois — uma conversa que estava em
    `humano` volta a `bot` no `upgrade` seguinte, e o assistente interrompe um
    atendimento que uma pessoa estava a fazer (`docs/tecnica/01` §10.2: «o bot
    nunca interrompe uma conversa em modo dono/humano»).

    Com linhas em `conversations`, exige-se `KAMBA_DOWNGRADE_0009_COPIA` com o
    caminho de um ficheiro onde a tabela e escrita antes de cair — a mesma
    forma que a `0003` usa para a identidade (`db/migrations/README.md`). Sem a
    variavel, o `downgrade` **recusa**: nao ha perda em silencio.

    **A politica sai ANTES de se contar, e isso foi um defeito medido.** Com
    `FORCE ROW LEVEL SECURITY`, o dono da tabela esta sujeito a politica — e uma
    migracao corre **sem** contexto de tenant. A primeira versao deste
    `downgrade` contava `count(*)` como `kamba_migrator` e via **zero linhas**
    sobre uma tabela cheia: nao pedia copia nenhuma e apagava as conversas em
    silencio, que e exactamente o contrario do que estas trinta linhas existem
    para impedir. E a mesma armadilha que o `docs/isolamento.md` §6 escreve para
    a validacao de uma FK nova — «a validacao passa sem ter olhado para nada» —,
    aqui a contar em vez de validar. Apanhada por
    `db/tests/test_conversas_schema.py`.

    O `disable_tenant_rls` e a primeira instrucao, e por isso a recusa tambem a
    desfaz: o Alembic corre **uma transacao por revisao**
    (`transaction_per_migration=True`), pelo que levantar aqui deixa a tabela
    com a politica intacta e a base em `0009`.
    """
    rls.disable_tenant_rls("conversations")
    quantas = _contar()
    if quantas:
        destino = os.environ.get(VARIAVEL_DA_COPIA, "").strip()
        if not destino:
            raise RuntimeError(
                f"downgrade da 0009: ha {quantas} conversa(s) e reverter apaga-as "
                f"— com elas, a janela de 24 h e o modo de cada uma. Defina "
                f"{VARIAVEL_DA_COPIA} com o caminho de um ficheiro para a "
                "copia logica, ou esvazie platform.conversations primeiro."
            )
        with open(destino, "w", encoding="utf-8") as ficheiro:
            json.dump(_linhas(), ficheiro, ensure_ascii=False, indent=1)

    # Pela ordem inversa do `upgrade`. Os `REVOKE` que a tabela leva consigo no
    # `DROP` nao se escrevem (seria ruido, e um `REVOKE` depois do `DROP`
    # falhava); o do `kamba_resolver` **tem** de se escrever, porque a
    # `platform.tenants` nao e desta revisao e fica.
    op.execute(
        f"REVOKE SELECT ({', '.join(COLUNAS_DO_RESOLVEDOR_NA_TENANTS)}) "
        "ON platform.tenants FROM kamba_resolver"
    )

    # A politica ja saiu, na primeira instrucao desta funcao (ver o docstring):
    # sem isso, a contagem de cima via zero linhas.
    #
    # Sem `CASCADE`: se houver um objecto pendurado que esta revisao nao criou,
    # o `downgrade` falha em vez de o apagar em silencio.
    op.execute("DROP TABLE platform.conversations")

    # A `UNIQUE` sai depois da tabela que a usava, e com o mesmo cuidado do
    # `FORCE` — um `DROP CONSTRAINT` nao le linhas, mas a simetria com o
    # `upgrade` e o que faz o par `upgrade`/`downgrade` ser lido de uma vez.
    op.execute("ALTER TABLE platform.tenant_channels NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE platform.tenant_channels "
        "DROP CONSTRAINT tenant_channels_tenant_id_uq"
    )
    op.execute("ALTER TABLE platform.tenant_channels FORCE ROW LEVEL SECURITY")
