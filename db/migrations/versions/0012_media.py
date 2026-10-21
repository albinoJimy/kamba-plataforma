"""Midia recebida: descarga, armazenamento e URL interna (KAM-020).

Uma tabela, `media_assets`, e e a primeira tabela do projecto cujo conteudo
**nao esta nela**: o que ela guarda e a chave de um objecto que vive no
`StorageProvider` (ADR-014), mais o que e preciso para o encontrar, para saber
se ja foi tratado, e para saber quando deve desaparecer.

* **Catorze colunas e nao as onze do criterio 1** (emenda 1.24). As tres a mais
  vem do proprio ticket: o `media_id`, porque o criterio **2** pede a unicidade
  de `(tenant_id, wamid, media_id)` e o criterio 1 nao o lista — a contagem de
  um nao fecha com a do outro; o `asset_id`, porque o criterio 5 emite
  `media://{asset_id}` e nao havia chave de onde o tirar; e o `criado_at`, pela
  convencao de todas as tabelas do §3.

* **A idempotencia e a `UNIQUE (tenant_id, wamid, media_id)`**, e e ela que
  torna o criterio 2 uma propriedade da base. Os tres valores sao conhecidos
  **antes** da descarga, e e isso que permite escrever a linha primeiro, em
  `pendente`: o segundo chamador perde o `ON CONFLICT` e **nao descarrega**. E o
  contrario do `ensureAccount` da `0011`, que nao podia escrever primeiro porque
  precisava de identificadores que so a criacao no provedor devolve — e que por
  isso deixa conta orfa numa corrida. Aqui nao ha orfa possivel.

* **Porque sao tres colunas e nao uma na chave.** O `wamid` sozinho nao chega:
  uma mensagem pode trazer mais do que um objecto, e duas trariam o mesmo
  `wamid`. O `media_id` sozinho tambem nao: e do lado da Meta e nada nos garante
  que nao se repita entre mensagens. O `tenant_id` esta la pela razao de sempre
  — sem ele a unicidade seria global e um `media_id` repetido entre duas PMEs
  recusava o segundo.

* **O `estado` tem quatro valores e o dominio e qualificado.** `pendente`,
  `armazenado`, `rejeitado`, `falhou`. Qualificado (`media_assets.estado`) pela
  regra da emenda 1.14, e aqui nao e cautela: ha **cinco** colunas `estado` com
  `CHECK` nas revisoes `0001`, `0003` e `0005`, e um dominio nu tornaria as cinco
  vermelhas no gate 3b.

* **O `rejeitado` e o `falhou` sao dois estados e nao um**, e a diferenca e
  operacional: um `rejeitado` (tipo ou tamanho fora da allowlist) pede ao
  cliente outro formato e nunca melhora sozinho; um `falhou` (tres tentativas
  sem sucesso) e do nosso lado ou do da Meta e pode ser retomado. Junta-los fazia
  o painel mandar a PME pedir outro ficheiro quando o problema era nosso.

* **Nenhum URL da Meta entra aqui, e nao e por omissao.** Nao ha coluna onde
  caiba: o que se guarda e o `media_id` (que e um identificador e nao um URL) e
  o `storage_ref` (que e a chave do **nosso** objecto). O criterio 3 pede um
  teste que percorra as tabelas a procura de padroes do dominio da Meta, e esse
  teste encontra o que esta aqui — a ausencia de coluna e o que o faz passar por
  construcao e nao por disciplina.

* **O `retain_until` conta da criacao e nao da transcricao**, e e a unica leitura
  auto-consistente. O `docs/tecnica/08` §7.5 diz «apagar o blob apos sucesso
  (alvo <= 24 h; limite de erro 72 h)» e o criterio 7 diz «criacao + 24 h».
  Contar da transcricao faz o prazo **nunca chegar** quando a transcricao nunca
  tem sucesso — que e precisamente o caso em que o audio nao devia ficar.

* **Sem `CHECK` sobre o `retain_until`.** Nenhuma restricao a obriga a ser
  futura, e a ausencia e deliberada: a purga e KAM-071, e uma restricao que
  recusasse uma data passada impedia o proprio KAM-071 de marcar um objecto para
  eliminacao imediata. E a licao que a `outbound_messages_entrega_ck` da `0010`
  pagou — uma restricao que recusa um estado que a propria maquina produz.

* **O que esta revisao nao faz:** nao apaga nada (KAM-071), nao transcreve
  (KAM-036), nao le imagens (KAM-049) e nao tem caminho para alterar estado de
  pagamento (ADR-013) — nem podia: nao ha FK nenhuma para PAY, e e isso que o
  teste de arquitectura do criterio 8 afirma.
"""

from __future__ import annotations

import json
import os

from alembic import op

import rls

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


#: As classes de objecto de midia, **com o prefixo `media_`**.
#:
#: O prefixo e o que resolve a divergencia que o §3.11 do dicionario registou e
#: nao resolveu (divida 8): o bloco do KAM-020 escreve a chave como
#: `t/{tenant_id}/media/{classe}/{aaaa}/{mm}/{uuid}`, com um segmento a mais que
#: a porta do KAM-011 **recusa** hoje (`validarClasse`, `[a-z][a-z0-9_]{1,31}`).
#:
#: Em vez de mudar a porta — que esta feita nas duas linguagens, testada, e tem o
#: X-08 na sua bateria de contrato — e a classe que diz que e midia. A chave fica
#: `t/{tenant_id}/media_audio/{aaaa}/{mm}/{uuid}`: um segmento, tres classes, e
#: nenhuma alteracao ao KAM-011.
CLASSES_DE_MIDIA = ("'media_audio'", "'media_imagem'", "'media_documento'")

#: Os quatro estados. Ver a nota do modulo: o `pendente` nao esta no ticket e e
#: o que torna a idempotencia verdadeira.
ESTADOS_DE_MIDIA = (
    "'pendente'",
    "'armazenado'",
    "'rejeitado'",
    "'falhou'",
)

#: A variavel que o `downgrade` exige quando ha linhas a perder.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0012_COPIA"

#: As colunas que `kamba_app` pode **alterar**, e todas tem chamador.
#:
#: Ao contrario da `0011` — onde a lista ficou **vazia** porque o caminho que a
#: justificava nao existia —, aqui o caminho e o proprio criterio 1: a linha
#: nasce em `pendente` com o que a mensagem traz, e so depois da descarga e do
#: `put` e que se sabe o `content_type` real, o `size`, o `sha256` e o
#: `storage_ref`. Sao duas instrucoes e nao uma, e e isso que faz a
#: idempotencia ser da base.
#:
#: O `asset_id`, o `tenant_id`, o `wamid` e o `media_id` **nao** estao: sao a
#: identidade da linha, e uma identidade que se reescreve nao e identidade. O
#: `contact_id` e o `conversation_id` tambem nao: a mensagem veio de uma
#: conversa e nao muda de conversa.
#:
#: **E a `classe` tambem nao, e a primeira versao desta lista concedia-a.** A
#: revisao adversarial apanhou-o: sao **seis** e nao sete, porque o modulo
#: **nunca** escreve a `classe` — ela e derivada do `wa_type` no momento da
#: reserva e nao muda. Era um privilegio de escrita sem chamador, que e
#: exactamente o critério pelo qual a `0011` deixou esta lista **vazia**, e que
#: esta revisao cita tres linhas acima.
#:
#: O que ele permitia nao e academico: reclassificar um objecto
#: (`media_audio` -> `media_imagem`) muda a coluna de que **depende a politica
#: de retencao do KAM-071**, e o segmento da chave ja escrita passa a nao casar
#: a classe da linha. Um audio reclassificado como imagem deixa de ter prazo e
#: fica para sempre.
COLUNAS_DA_APLICACAO = (
    "content_type",
    "size",
    "sha256",
    "storage_ref",
    "estado",
    "retain_until",
)

#: As colunas da copia logica, pela ordem do `SELECT`.
COLUNAS_DA_COPIA = (
    "asset_id",
    "tenant_id",
    "contact_id",
    "conversation_id",
    "wamid",
    "media_id",
    "classe",
    "content_type",
    "size",
    "sha256",
    "storage_ref",
    "estado",
    "retain_until",
    "criado_at",
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform.media_assets (
            asset_id        uuid        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       uuid        NOT NULL,
            contact_id      uuid        NOT NULL,
            conversation_id uuid        NOT NULL,
            -- O identificador da mensagem no WhatsApp, e o do objecto no lado
            -- da Meta. Os dois sao precisos: ver a nota do modulo.
            wamid           text        NOT NULL,
            media_id        text        NOT NULL,
            classe          text        NOT NULL,
            -- Anulaveis ate a descarga acontecer: a linha nasce em `pendente`,
            -- e o `content_type` **real** so se sabe da resposta. Confiar no
            -- que o webhook anuncia era aceitar que ele mente.
            content_type    text,
            size            bigint,
            sha256          text,
            storage_ref     text,
            estado          text        NOT NULL,
            retain_until    timestamptz,
            criado_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT media_assets_pkey PRIMARY KEY (asset_id),
            -- **A idempotencia do criterio 2, e e da base.** Tres colunas e nao
            -- uma: ver a nota do modulo.
            CONSTRAINT media_assets_origem_uq UNIQUE (tenant_id, wamid, media_id),
            CONSTRAINT media_assets_tenant_fk
                FOREIGN KEY (tenant_id) REFERENCES platform.tenants (id),
            -- **Compostas com o `tenant_id`**, pela razao que a `0009` fixou e
            -- a `0011` repetiu: sem o `tenant_id` na FK, um objecto de A podia
            -- apontar para uma conversa de B, e nem o gate 6 nem o 3b o veriam.
            CONSTRAINT media_assets_contact_fk
                FOREIGN KEY (tenant_id, contact_id)
                REFERENCES platform.contacts (tenant_id, contact_id),
            CONSTRAINT media_assets_conversation_fk
                FOREIGN KEY (tenant_id, conversation_id)
                REFERENCES platform.conversations (tenant_id, id),
            CONSTRAINT media_assets_classe_ck
                CHECK (classe IN ({', '.join(CLASSES_DE_MIDIA)})),
            CONSTRAINT media_assets_estado_ck
                CHECK (estado IN ({', '.join(ESTADOS_DE_MIDIA)})),
            -- Um `wamid` ou um `media_id` vazio e um identificador que nao
            -- identifica. A mesma forma do `token_ref` da `0001`.
            CONSTRAINT media_assets_wamid_ck CHECK (btrim(wamid) <> ''),
            CONSTRAINT media_assets_media_id_ck CHECK (btrim(media_id) <> ''),
            -- Um tamanho negativo nao existe; zero existe (um ficheiro vazio
            -- descarrega-se, e e a allowlist de tamanho que o recusa, nao a
            -- base).
            CONSTRAINT media_assets_size_ck CHECK (size IS NULL OR size >= 0),
            -- Um SHA-256 em hexadecimal minusculo, 64 digitos. A forma vale
            -- porque e o que o `ObjectRef.sha256` da porta devolve, e porque um
            -- resumo com outra forma e um resumo de outra coisa.
            CONSTRAINT media_assets_sha256_ck
                CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{{64}}$'),
            -- **O que esta armazenado tem de ter onde estar.** E a unica
            -- restricao que liga duas colunas, e existe porque um
            -- `armazenado` sem `storage_ref` e uma linha que diz que o objecto
            -- esta la e nao diz onde: o consumidor pede `signUrl` e nao ha o
            -- que assinar. Os outros tres estados nao exigem nada, porque
            -- `pendente` e antes, e `rejeitado` e `falhou` nunca chegaram a
            -- escrever.
            CONSTRAINT media_assets_armazenado_ck
                CHECK (
                    estado <> 'armazenado'
                    OR (
                        storage_ref IS NOT NULL
                        AND btrim(storage_ref) <> ''
                        AND sha256 IS NOT NULL
                        AND size IS NOT NULL
                    )
                )
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN platform.media_assets.media_id IS "
        "'Identificador do objecto do lado da Meta. **Nao e um URL**: o URL "
        "temporario que ele resolve nunca e persistido, aqui nem em sitio "
        "nenhum (docs/tecnica/08 §3.8, e o criterio 3 do KAM-020).'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.media_assets.storage_ref IS "
        "'A ObjectKey do StorageProvider (KAM-011), na forma "
        "t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}. O que os consumidores "
        "guardam e passam entre si e media://{asset_id} e nao esta chave: a "
        "chave e do armazenamento e muda se o molde mudar, o asset_id e nosso "
        "e nao muda.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.media_assets.retain_until IS "
        "'Conta da **criacao** e nao da transcricao, e e a unica leitura "
        "auto-consistente: contar da transcricao faz o prazo nunca chegar "
        "quando ela nunca tem sucesso, que e o caso em que o audio nao devia "
        "ficar. A purga em si e KAM-071.'"
    )
    op.execute(
        "COMMENT ON COLUMN platform.media_assets.classe IS "
        "'Com o prefixo media_ de proposito: e o que permite usar a chave do "
        "KAM-011 sem o segmento a mais que o bloco do KAM-020 escreve e que a "
        "porta recusa (divida documental 8).'"
    )

    # O indice comeca pelo `tenant_id` **porque a RLS o le em toda a consulta**,
    # e so depois pelo que o painel ordena. A licao e da `0011`, onde o gate 8
    # recusou a tabela sem ele. A segunda coluna e escolha desta revisao.
    op.execute(
        "CREATE INDEX media_assets_tenant_idx "
        "ON platform.media_assets (tenant_id, criado_at DESC)"
    )

    rls.enable_tenant_rls("media_assets")

    # ------------------------------------------------------------- privilegios
    #
    # Tabela a tabela e coluna a coluna, sem `ALTER DEFAULT PRIVILEGES`: uma
    # tabela nova nao nasce acessivel (`db/migrations/README.md`).
    #
    # O `SELECT` de tabela e preciso e nao e generoso: o `INSERT ... ON CONFLICT
    # (tenant_id, wamid, media_id) DO NOTHING RETURNING` exige `SELECT` nas
    # colunas de inferencia — a licao que a `0008` escreveu.
    op.execute("GRANT SELECT, INSERT ON platform.media_assets TO kamba_app")
    op.execute(
        f"GRANT UPDATE ({', '.join(COLUNAS_DA_APLICACAO)}) "
        "ON platform.media_assets TO kamba_app"
    )

    # O `kamba_batch` tem os quatro verbos, que e o que tem em todas as outras
    # desde a `0001`, porque e quem purga (KAM-071).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON platform.media_assets TO kamba_batch"
    )


def _contar() -> int:
    """Quantos objectos de midia existem."""
    return op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM platform.media_assets"
    ).scalar_one()


def _linhas() -> list[dict[str, object]]:
    """A copia logica, pela ordem de `COLUNAS_DA_COPIA`."""
    resultado = op.get_bind().exec_driver_sql(
        f"SELECT {', '.join(COLUNAS_DA_COPIA)} "
        "  FROM platform.media_assets ORDER BY tenant_id, criado_at"
    )
    return [
        {coluna: str(valor) for coluna, valor in zip(COLUNAS_DA_COPIA, linha)}
        for linha in resultado
    ]


def downgrade() -> None:
    """Reverter apaga os registos, e os objectos **ficam**.

    O que se perde aqui e diferente do que se perde nas outras revisoes, e e
    pior do que parece: as linhas vao, e os **objectos no armazenamento nao**.
    Um blob sem linha que o aponte e lixo que ninguem sabe que existe — nenhum
    consumidor o encontra, a purga do KAM-071 nao o ve (ela le esta tabela), e
    continua a custar armazenamento e a guardar dados pessoais de um cliente
    final para sempre. **A copia e por isso a unica forma de alguem os poder
    reencontrar**, e e o `storage_ref` de cada linha que o permite.

    Com linhas, exige-se `KAMBA_DOWNGRADE_0012_COPIA` com o caminho de um
    ficheiro onde elas sao escritas antes de cairem — a mesma forma da `0003`,
    da `0009`, da `0010` e da `0011`. Sem a variavel, **recusa**.

    **A politica sai ANTES de se contar**, pela licao medida na `0009` e
    confirmada na `0010` e na `0011`: com `FORCE ROW LEVEL SECURITY` o dono da
    tabela esta sujeito a politica, e uma migracao corre **sem** contexto de
    tenant — `count(*)` como `kamba_migrator` veria **zero** sobre uma tabela
    cheia, nao pediria copia nenhuma, e apagaria em silencio.

    O `disable_tenant_rls` e a primeira instrucao, pelo que a recusa tambem o
    desfaz: o Alembic corre uma transacao por revisao
    (`transaction_per_migration=True`), e levantar aqui deixa a tabela com a
    politica intacta e a base em `0012`.
    """
    rls.disable_tenant_rls("media_assets")

    objectos = _contar()
    if objectos:
        destino = os.environ.get(VARIAVEL_DA_COPIA, "").strip()
        if not destino:
            raise RuntimeError(
                f"downgrade da 0012: ha {objectos} objecto(s) de midia, e "
                "reverter apaga os registos **e deixa os blobs no "
                "armazenamento** — lixo que nenhum consumidor encontra e que a "
                "purga do KAM-071 nao ve, porque ela le esta tabela. Defina "
                f"{VARIAVEL_DA_COPIA} com o caminho de um ficheiro onde a "
                "copia (com o storage_ref de cada linha) e escrita antes de "
                "cair, ou nao reverta."
            )
        with open(destino, "w", encoding="utf-8") as ficheiro:
            json.dump({"media_assets": _linhas()}, ficheiro, ensure_ascii=False, indent=2)

    op.execute("DROP INDEX platform.media_assets_tenant_idx")
    op.execute("DROP TABLE platform.media_assets")
