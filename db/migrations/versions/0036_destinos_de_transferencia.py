"""Destinos de transferencia: tenant_destinations e v_transfer_audit (KAM-069).

A primeira linha e **sem acentos**, como as trinta e quatro revisoes anteriores:
e a mensagem que o `alembic history` imprime, e o
`test_no_processo_e_pela_linha_de_comandos_o_alembic_diz_o_mesmo` compara a saida
no processo com a do executavel. Com acentos, as duas divergem na codificacao.

## O que esta revisao cria

Duas coisas, e sao os criterios 1 e 7 do KAM-069:

* a `platform.tenant_destinations`, a configuracao por tenant e destino do
  `docs/tecnica/08` secao 8.3.1 — **negada por omissao**, porque a ausencia de
  linha e a ausencia de autorizacao;
* a vista `platform.v_transfer_audit`, que junta o registo de chamadas a modelos
  (`dat.llm_call_log`, revisao `0023`) a esta tabela e devolve **as chamadas que
  sairam sem destino autorizado no instante em que sairam**. O alvo do criterio
  7 e **zero linhas**, e por isso a vista enumera violacoes e nao conformidades:
  uma vista que listasse o que esta bem nunca se lia.

O que o ADR-008 manda, por extenso: nenhum dado pessoal de producao sai de
Angola sem a notificacao ou a autorizacao da APD aplicavel. **O codigo nunca
infere adequacao a partir do pais** — a lista de paises adequados e NAO
VERIFICADA (a APD nao a publica), a UE e a Africa do Sul sao hipoteses e os EUA
provavelmente exigem autorizacao (INDICIO). Esta tabela nao tem coluna nenhuma
que diga «adequado»: tem `status` e `apd_ref`, e so a conjuncao dos dois liberta
uma chamada.

## `tenant_id` anulavel, e o nulo e o destino global

O criterio 1 escreve-o: «`tenant_id` nulo significa destino global (infra)». O
alojamento, as copias de seguranca, o CDN e a observabilidade sao da plataforma
e nao de um tenant — uma linha por tenant para o mesmo CDN era a mesma
autorizacao repetida tantas vezes quantos os tenants, e a primeira que
divergisse era um destino autorizado para uns e negado para outros sem ninguem
decidir isso.

**A unicidade leva `NULLS NOT DISTINCT`, e sem isso a restricao nao restringia
nada.** Em PostgreSQL, uma `UNIQUE` trata nulos como distintos entre si por
omissao: `(NULL, 'cloudflare', 'XX', 'entrega_de_conteudo')` duas vezes passava
as duas, e ficavam **dois** destinos globais para o mesmo trio — um `pendente` e
um `autorizado`, e a porta lia o que lhe calhasse primeiro. O `NULLS NOT
DISTINCT` e de PostgreSQL 15 e esta base e 18.6.

## A janela de validade existe porque o criterio 7 diz «no momento da chamada»

Sem ela, a vista do criterio 7 responde a uma pergunta diferente da que ele faz:
compara uma chamada de ha tres meses com o estado de **hoje**, pelo que revogar
um destino tornava retroactivamente ilegais chamadas que estavam autorizadas
quando sairam, e autorizar um destino hoje apagava as chamadas que sairam antes
de ele existir. As duas direccoes do erro sao graves, e a segunda e a pior: e um
registo de conformidade a limpar-se a si proprio.

Por isso ha `autorizado_em` e `revogado_em`, e os `CHECK` ligam-nas ao `status`.
**O que isto nao e:** um historico. Uma linha que seja autorizada, revogada e
autorizada outra vez perde a primeira janela, e a vista deixa de ver as chamadas
do primeiro periodo como autorizadas. A alternativa — uma tabela de historico —
e uma segunda tabela, e o custo dela esta medido nesta casa (as listas fechadas
do *gate* 8 derivam por subtraccao). Fica **declarado e nao resolvido**, com o
credor escrito no bloco: quem precisar do historico escreve-o quando houver um
destino que tenha sido revogado alguma vez, e hoje nao ha nenhum autorizado.

## A *checklist* do requisito 8 vive em colunas, e nao num documento

O criterio 6 pede que por destino fiquem arquivados contrato, retencao zero,
nao-treino e `apd_ref`, e que «um destino `autorizado` sem *checklist* completo
seja rejeitado». Rejeitado **pela base** e nao por um verificador: as tres
colunas (`contrato_ref`, `retencao_zero`, `sem_treino`) mais o `apd_ref` entram
num `CHECK` que o `status = 'autorizado'` exige.

**Os dois booleanos sao `NOT NULL` sem omissao**, pela licao que o `attempt` da
`0034` pagou ao contrario: aqui a omissao seria `false`, que e o lado seguro, e
mesmo assim nao se escreve — quem insere uma linha de destino tem de dizer, a
cada uma, se o fornecedor confirmou retencao zero e nao-treino. Um `DEFAULT
false` convidava a inserir sem olhar e a descobrir a falta so no dia em que
alguem tentasse autorizar.

## Duas politicas de RLS, e nao uma politica nova

O `db/rls.py` e o unico sitio onde a politica `tenant_iso` se escreve, e nao se
toca: o `enable_tenant_rls` cria-a aqui como em todas as outras tabelas com
`tenant_id`, e o X-05 do *gate* 6 encontra-a sem ninguem a declarar.

O que o criterio 1 pede a mais — «RLS `FORCE` com linhas globais legiveis» —
entra como uma **segunda politica permissiva**, `destinos_globais`, e o
PostgreSQL une as politicas permissivas por `OR`. E `FOR SELECT`, e isso e a
barreira: com ela em `ALL`, um tenant podia **escrever** uma linha global, que e
autorizar um destino de infra-estrutura para a plataforma toda a partir do
contexto de um tenant. Ler as linhas globais e necessario; escrever nao.

## Quem escreve aqui nao e a aplicacao

O `kamba_app` leva **`SELECT` e mais nada**. Autorizar um destino e um acto
humano com papelada arquivada — contrato, retencao zero, nao-treino, numero de
procedimento da APD — e nao uma escrita de um processo que serve conversas. Quem
escreve e o `kamba_batch`, que e o papel dos trabalhos de plataforma.

## A vista exclui as recusas, e essa decisao e a mais consequente do ficheiro

Uma linha de `dat.llm_call_log` com `resultado = 'destino_negado'` e uma chamada
que **nao aconteceu**: o *gate* corre antes de haver pedido, e o `CHECK
llm_call_log_negado_sem_consumo` da `0023` recusa-a se levar *tokens* ou custo.
Nada saiu de Angola.

Incluir essas linhas punha a vista a devolver uma linha por cada recusa, e em
`KAMBA_ENV=prod` a porta nega **tudo** hoje — a vista do criterio 7, cujo alvo e
zero, nasceria a crescer com o numero de recusas e o alvo era inalcancavel por
construcao. Pior: media o contrario do que o criterio pede. Ele pede «chamadas
sem destino autorizado», e uma recusa e precisamente a prova de que a barreira
funcionou.

**O que isto custa, dito:** uma chamada cujo registo nao se conseguiu escrever
nao aparece nesta vista, porque nao ha linha nenhuma dela. Essa classe esta
coberta do outro lado — o codigo de saida **7** do AGR e a metrica
`agr_llm_registo_falhou_total` da `0023` —, e nao por aqui.
"""

from __future__ import annotations

from alembic import op

import rls

revision = "0036"
#: A `0035` (KAM-055) e a cabeca da cadeia na **base** e nao neste worktree: a
#: cadeia Alembic e linear e de escritor unico, e uma `down_revision` que
#: aponte para uma revisao que ainda nao fundiu deixa a cadeia irresoluvel ate
#: ela fundir — e ocupar uma `down_revision` que outra revisao ja ocupa da
#: **duas cabecas**, que o `test_ha_uma_so_cabeca` de `db/tests/test_migracao.py`
#: recusa. Lido de `refs/remotes/publico/main`.
down_revision = "0035"
branch_labels = None
depends_on = None

#: Literais e nao f-strings sobre outras constantes: o *gate* 3b le o AST da
#: revisao sem a executar e resolve `f"..."` sobre constantes de modulo, mas nao
#: sobre constantes que sejam elas proprias f-strings. A `0023` pagou nove
#: `op.execute` lidos como `[ilegivel]` para aprender isto.
DESTINOS = "platform.tenant_destinations"
VISTA = "platform.v_transfer_audit"
REGISTO = "dat.llm_call_log"

#: Os **quatro** estados de um destino. Lista **fechada**, com `CHECK`.
#:
#: Sao ***proposta*** deste ticket, e os *Detalhes Tecnicos* do bloco mandam
#: regista-lo: o `docs/tecnica/08` secao 8.3.1 so fixa «por defeito negado» e
#: «sem linha `autorizado` a chamada falha», pelo que nomeia um dos quatro. Os
#: outros tres saem do que o procedimento tem de distinguir, e nao de gosto:
#:
#:   pendente    o procedimento esta em curso, ou nem comecou. E a omissao, e e
#:               o estado das **catorze** linhas da folha de seguimento do
#:               KAM-105 (zero submetidas, zero com numero de protocolo).
#:   autorizado  a APD respondeu e permite. So este liberta uma chamada.
#:   revogado    esteve autorizado e deixou de estar. Distinto do `negado`
#:               porque a janela de validade dele **existiu**, e a vista do
#:               criterio 7 le as chamadas desse periodo como conformes.
#:   negado      a APD respondeu e nao permite. Nunca houve janela.
#:
#: Ja entre apostrofos, pela razao da `0015`: e a unica forma que o *gate* 3b
#: resolve, porque segue `", ".join(<constante de modulo>)` dentro de uma
#: f-string.
ESTADOS_DO_DESTINO = ("'pendente'", "'autorizado'", "'revogado'", "'negado'")

#: As **treze** finalidades de transferencia. Lista **fechada**, com `CHECK`,
#: por ordem alfabetica.
#:
#: **Quem declara o dominio de uma coluna e a revisao que a cria**, e a emenda
#: 1.38 do dicionario escreve isso por extenso sobre esta coluna: as tres
#: finalidades que o KAM-030 ja usa (`conversa`, `embeddings`, `visao`) vivem em
#: `FINALIDADES`, em `services/agr/src/kamba_agr/llm/destinos.py`, e ficaram
#: **fora** do dicionario a espera desta revisao.
#:
#: As treze sao a uniao de duas listas do bloco, e nenhuma e invencao:
#:
#: * o criterio 4 nomeia **sete** pontos onde o *gate* e invocado — LLM, STT,
#:   embeddings, copias de seguranca, CDN, observabilidade e e-mail/SMS;
#: * o criterio 5 nomeia **onze** subprocessadores com a funcao de cada um
#:   (`docs/tecnica/08` secao 8.3.2).
#:
#: Uma finalidade que o dominio nao conhecesse tornava a linha do inventario
#: dela **impossivel de escrever**, e era por ai que o criterio 5 ficava sem
#: superficie. O `otp_e_avisos_de_servico` nao e nome novo: e o `FINALIDADE` do
#: `packages/core-ts/src/sms/fornecedor.ts` (KAM-116), ja em `main`.
FINALIDADES_DE_TRANSFERENCIA = (
    "'alojamento'",
    "'canal'",
    "'conversa'",
    "'copias_de_seguranca'",
    "'embeddings'",
    "'entrega_de_conteudo'",
    "'facturacao'",
    "'observabilidade'",
    "'otp_e_avisos_de_servico'",
    "'pagamentos'",
    "'segredos'",
    "'transcricao'",
    "'visao'",
)

#: As **tres** finalidades que uma chamada a um modelo pode ter.
#:
#: Sao as que o `FINALIDADES` do `services/agr/src/kamba_agr/llm/destinos.py`
#: declara — `conversa`, `embeddings`, `visao` —, e a vista **exige-as**: sem
#: isto, um destino autorizado so para `segredos` ou para `alojamento` cobria uma
#: chamada a um modelo, e a vista dizia conforme uma transferencia que o *gate*
#: tinha recusado. Uma superficie de auditoria mais permissiva do que a barreira
#: que audita e pior do que nao a ter.
#:
#: **O que isto nao faz, e diz-se:** nao discrimina **qual** das tres. O mapa
#: `papel` -> `finalidade` vive no AGR (`FINALIDADE_DO_PAPEL`) e reescreve-lo num
#: `CASE` do SQL dava duas copias da mesma regra, que e o defeito que esta casa
#: paga mais vezes. O que a vista mede e «havia destino autorizado para este
#: fornecedor, numa finalidade de modelo, no instante da chamada»; **quem
#: discrimina a finalidade e o *gate***, que corre antes de o pedido sair.
#: Credor da versao exacta: o ticket que trouxer o `papel` para o canon do lado
#: da base — hoje nenhum o reclama.
FINALIDADES_DE_MODELO = ("'conversa'", "'embeddings'", "'visao'")

#: O desfecho de uma chamada que **nao** saiu: o *gate* recusou antes de haver
#: pedido. Ver a nota do modulo — a vista exclui-o, e e a decisao mais
#: consequente deste ficheiro. O valor e o do dominio de `llm_call_log.resultado`
#: da `0023`.
RESULTADO_RECUSADO = "destino_negado"

#: A forma do pais: ISO 3166-1 alfa-2, em maiusculas. **A mesma** do
#: `packages/core-ts/src/storage/config.ts` (KAM-011), do `avisos/fornecedor.ts`
#: (KAM-115) e do `sms/fornecedor.ts` (KAM-116), que e a razao de a escrever
#: assim: os tres declaram um destino de transferencia no ambiente, e esta
#: tabela e a que o KAM-069 confronta com eles.
FORMA_DO_PAIS = "^[A-Z]{2}$"

#: A forma do fornecedor: minusculas, como nos tres modulos acima.
FORMA_DO_FORNECEDOR = "^[a-z][a-z0-9_-]{1,62}$"

#: A forma da referencia do procedimento na APD, dos mesmos tres modulos.
#:
#: **Nao e um numero de protocolo com formato conhecido**, e isso e deliberado:
#: o formato das referencias da APD e NAO VERIFICADO (nenhuma submissao foi
#: feita — folha de seguimento do KAM-105, zero de catorze), pelo que a forma
#: aceita o que um orgao publico costuma emitir e recusa o que nao e referencia
#: nenhuma: vazio, espacos, texto com acentos.
FORMA_DO_APD_REF = "^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$"

PAPEL_DA_APP = "kamba_app"
PAPEL_DE_AUDITORIA = "kamba_audit"
PAPEL_DE_LOTE = "kamba_batch"

#: A segunda politica permissiva: as linhas globais, **so para leitura**. Ver a
#: nota do modulo.
POLITICA_GLOBAL = "destinos_globais"


def upgrade() -> None:
    _tenant_destinations()
    _vista_de_auditoria()
    _rls()
    _privilegios()


def _tenant_destinations() -> None:
    """A configuracao por tenant e destino, negada por omissao."""
    op.execute(
        f"""
        CREATE TABLE {DESTINOS} (
            id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            -- **Anulavel, e o nulo e o destino global (infra).** Ver a nota do
            -- modulo. Sem FK para `platform.tenants`: um destino pode ser
            -- registado antes de o tenant existir (o gate de go-live do
            -- criterio 8 corre na transicao `onboarding` -> `ativo`, e o
            -- registo do destino e anterior a ela).
            tenant_id     uuid,
            provider      text        NOT NULL,
            -- ISO 3166-1 alfa-2. **Nao ha coluna que diga «adequado»**: a lista
            -- de paises adequados e NAO VERIFICADA e o codigo nunca a infere.
            country       text        NOT NULL,
            purpose       text        NOT NULL,
            -- A referencia do procedimento na APD. Anulavel, e hoje e nula em
            -- todas as linhas: o KAM-105 fechou com **zero de catorze**
            -- destinos com `apd_ref`.
            apd_ref       text,
            status        text        NOT NULL,
            -- A *checklist* do requisito 8 de `E3`, em colunas. Ver a nota do
            -- modulo: um destino `autorizado` sem ela e recusado pela base.
            contrato_ref  text,
            -- **`NOT NULL` sem omissao, de proposito.** Um `DEFAULT false`
            -- convidava a inserir sem olhar; assim quem insere diz, linha a
            -- linha, se o fornecedor confirmou cada uma das duas coisas.
            retencao_zero boolean     NOT NULL,
            sem_treino    boolean     NOT NULL,
            -- A janela de validade, que existe porque o criterio 7 diz «no
            -- momento da chamada». Ver a nota do modulo.
            autorizado_em timestamptz,
            revogado_em   timestamptz,
            criado_at     timestamptz NOT NULL DEFAULT now(),
            -- Escrito pelo modulo em cada `UPDATE`, nao por *trigger* — a
            -- mesma escolha da `0028`, da `0030`, da `0033` e da `0034`.
            atualizado_at timestamptz NOT NULL DEFAULT now(),
            -- A unicidade do criterio 1, com `NULLS NOT DISTINCT`. **Sem isso
            -- a restricao nao restringia nada**: dois destinos globais para o
            -- mesmo trio passavam os dois, um `pendente` e um `autorizado`.
            -- Ver a nota do modulo.
            CONSTRAINT tenant_destinations_destino_uk
                UNIQUE NULLS NOT DISTINCT (tenant_id, provider, country, purpose),
            CONSTRAINT tenant_destinations_status_ck
                CHECK (status IN ({", ".join(ESTADOS_DO_DESTINO)})),
            CONSTRAINT tenant_destinations_purpose_ck
                CHECK (purpose IN ({", ".join(FINALIDADES_DE_TRANSFERENCIA)})),
            CONSTRAINT tenant_destinations_country_ck
                CHECK (country ~ '{FORMA_DO_PAIS}'),
            CONSTRAINT tenant_destinations_provider_ck
                CHECK (provider ~ '{FORMA_DO_FORNECEDOR}'),
            -- **Sem `IS NULL OR`, e a coluna continua anulavel.** Um `CHECK`
            -- passa quando a expressao e verdadeira **ou nula**, e um `~` sobre
            -- nulo e nulo: a guarda explicita era redundante, e o *gate* 3b
            -- nao a le como dominio (medido na `0030`).
            CONSTRAINT tenant_destinations_apd_ref_ck
                CHECK (apd_ref ~ '{FORMA_DO_APD_REF}'),
            -- Vazio nao e uma referencia de contrato. Pela razao do `sku` da
            -- `0033` e do `external_id` da `0034`.
            CONSTRAINT tenant_destinations_contrato_ref_ck
                CHECK (btrim(contrato_ref) <> ''),
            -- O criterio 1, ao pe da letra: «`status='autorizado'` exige
            -- `apd_ref` nao nulo (`CHECK`)».
            CONSTRAINT tenant_destinations_autorizado_com_apd_ref_ck
                CHECK (status <> 'autorizado' OR apd_ref IS NOT NULL),
            -- O criterio 6: «um destino `autorizado` sem *checklist* completo e
            -- rejeitado». Separado do anterior de proposito — sao dois
            -- criterios distintos, e uma restricao so dizia qual das duas
            -- metades faltou.
            CONSTRAINT tenant_destinations_autorizado_com_checklist_ck
                CHECK (status <> 'autorizado'
                       OR (contrato_ref IS NOT NULL
                           AND retencao_zero
                           AND sem_treino)),
            -- A janela de um destino autorizado esta **aberta**: tem inicio e
            -- nao tem fim. Sem isto, uma linha `autorizado` com `revogado_em`
            -- no passado dizia as duas coisas ao mesmo tempo, e a vista lia-a
            -- de uma maneira e a porta de outra.
            CONSTRAINT tenant_destinations_autorizado_com_janela_ck
                CHECK (status <> 'autorizado'
                       OR (autorizado_em IS NOT NULL AND revogado_em IS NULL)),
            -- Um destino revogado **esteve** autorizado: tem as duas pontas.
            -- E o que distingue `revogado` de `negado`.
            CONSTRAINT tenant_destinations_revogado_com_janela_ck
                CHECK (status <> 'revogado'
                       OR (autorizado_em IS NOT NULL
                           AND revogado_em IS NOT NULL)),
            -- Uma janela nao se fecha antes de abrir. O `>` e nao `>=`: uma
            -- janela de duracao zero nao autorizou chamada nenhuma, e
            -- escreve-la como `negado` diz a verdade.
            CONSTRAINT tenant_destinations_janela_ordenada_ck
                CHECK (revogado_em IS NULL
                       OR autorizado_em IS NULL
                       OR revogado_em > autorizado_em),
            -- Nem `pendente` nem `negado` tem janela: nenhum dos dois esteve
            -- autorizado alguma vez. Sem este, um `pendente` com
            -- `autorizado_em` preenchido fazia a vista do criterio 7 tratar as
            -- chamadas dele como conformes — a tabela tem duas leitoras e elas
            -- discordavam.
            CONSTRAINT tenant_destinations_sem_janela_ck
                CHECK (status IN ('autorizado', 'revogado')
                       OR (autorizado_em IS NULL AND revogado_em IS NULL))
        )
        """
    )
    op.execute(
        f"COMMENT ON TABLE {DESTINOS} IS "
        "'Configuracao por tenant e destino do gate de transferencia (KAM-069, "
        "ADR-008, docs/tecnica/08 secao 8.3.1). Negada por omissao: a ausencia "
        "de linha e a ausencia de autorizacao, e so status autorizado com "
        "apd_ref liberta uma chamada. O tenant_id nulo e um destino global de "
        "infra-estrutura, legivel por todos os tenants e escrito so pelo "
        "kamba_batch. Nenhuma coluna diz adequado: a lista de paises adequados "
        "e NAO VERIFICADA e o codigo nunca a infere. As colunas autorizado_em e "
        "revogado_em sao a janela que a vista v_transfer_audit le, porque o "
        "criterio 7 pergunta pelo estado no momento da chamada.'"
    )
    # A chave primaria **nao** comeca pelo `tenant_id`, e a unica que comeca e a
    # da unicidade — que leva quatro colunas e serve o prefixo
    # `(tenant_id, provider)` que a porta consulta. O indice proprio aqui e o
    # **outro** acesso: as linhas globais, que a porta le em todas as consultas
    # e que a unicidade nao serve (o `tenant_id` nulo esta a cabeca dela, e um
    # `IS NULL` sobre a primeira coluna de um indice de quatro varre-o todo).
    op.execute(
        f"CREATE INDEX tenant_destinations_globais_idx ON {DESTINOS} "
        "(provider, purpose) WHERE tenant_id IS NULL"
    )


def _vista_de_auditoria() -> None:
    """A vista do criterio 7: as chamadas que sairam sem destino autorizado.

    `security_invoker = true`, e nao e opcional: o *gate* 6 falha com uma vista
    sem ele e **para vistas nao ha lista de excepcoes**. Sem o `invoker`, a
    vista corria com os privilegios do dono — o `kamba_migrator` — e era um
    caminho de leitura por cima dos `GRANT` das duas tabelas e por cima da RLS
    das duas.

    **Uma consequencia de `security_invoker` que quem le isto tem de saber:** o
    `kamba_audit` nao tem `BYPASSRLS`, pelo que ve as violacoes **do tenant do
    seu contexto** e nenhuma das linhas globais de `llm_call_log`. A pergunta do
    criterio 7 — «zero linhas em toda a plataforma» — responde-se como
    `kamba_batch`, que tem `BYPASSRLS`. As duas leituras sao legitimas e medem
    coisas diferentes; confundi-las dava um zero que so dizia «nao vi nada».

    **Um `LEFT JOIN` e nao um `NOT EXISTS`**, e a diferenca nao e de gosto: o
    criterio escreve «junta `llm_call_log` a `tenant_destinations`», e um
    anti-*join* por `LEFT JOIN ... IS NULL` **e** a juncao que ele pede, com a
    condicao de autorizacao escrita no `ON` onde se pode ler. A forma com
    subconsulta escondia a condicao dentro de um `EXISTS` e dava a mesma
    resposta sem mostrar contra o que foi comparada.
    """
    op.execute(
        f"""
        CREATE VIEW {VISTA}
          WITH (security_invoker = true) AS
          SELECT c.id, c.ts, c.tenant_id, c.fornecedor, c.modelo, c.papel,
                 c.resultado
            FROM {REGISTO} c
            LEFT JOIN {DESTINOS} d
              ON (d.tenant_id = c.tenant_id OR d.tenant_id IS NULL)
             AND d.provider = c.fornecedor
             AND d.purpose IN ({", ".join(FINALIDADES_DE_MODELO)})
             AND d.apd_ref IS NOT NULL
             AND d.autorizado_em IS NOT NULL
             AND d.autorizado_em <= c.ts
             AND (d.revogado_em IS NULL OR d.revogado_em > c.ts)
           WHERE c.resultado <> '{RESULTADO_RECUSADO}'
             AND d.id IS NULL
        """
    )
    op.execute(
        f"COMMENT ON VIEW {VISTA} IS "
        "'As chamadas a modelos que sairam sem destino autorizado com apd_ref "
        "no instante em que sairam (KAM-069 criterio 7, ADR-008). O alvo e zero "
        "linhas. Exige que o destino seja autorizado numa finalidade de modelo "
        "(conversa, embeddings, visao): sem isso, um destino autorizado so para "
        "segredos cobria uma chamada ao modelo e a vista dizia conforme o que o "
        "gate recusou. Nao discrimina qual das tres, porque o mapa papel -> "
        "finalidade vive no AGR e reescreve-lo aqui dava duas copias da mesma "
        "regra; quem discrimina e o gate, antes de o pedido sair. "
        "Exclui o resultado destino_negado, que e uma chamada que nao "
        "aconteceu: o gate corre antes de haver pedido e o CHECK "
        "llm_call_log_negado_sem_consumo da revisao 0023 recusa-a se levar "
        "tokens ou custo. Com security_invoker, o kamba_audit ve o tenant do seu "
        "contexto e a pergunta sobre a plataforma toda responde-se como "
        "kamba_batch.'"
    )


def _rls() -> None:
    """A `tenant_iso` do `db/rls.py`, e a segunda politica das linhas globais.

    Chamado **directamente** e nao por iteracao sobre uma lista: o *gate* 3b le
    o AST da revisao sem a executar e resolve a chamada com os argumentos que
    consegue ler, e um `for` sobre uma lista de nomes deixava-o sem os ver.
    """
    rls.enable_tenant_rls("tenant_destinations")
    # A segunda politica permissiva. O PostgreSQL une as permissivas por `OR`,
    # pelo que esta **acrescenta** as linhas globais ao que a `tenant_iso` ja
    # deixa ver, sem tocar nela — e o `db/rls.py` continua a ser o unico sitio
    # onde a `tenant_iso` se escreve.
    #
    # `FOR SELECT`, e e ai que a barreira vive: em `ALL`, um tenant podia
    # **escrever** uma linha global, que e autorizar um destino de
    # infra-estrutura para a plataforma toda a partir do contexto de um tenant.
    op.execute(
        f"CREATE POLICY {POLITICA_GLOBAL} ON {DESTINOS} "
        "FOR SELECT USING (tenant_id IS NULL)"
    )


def _privilegios() -> None:
    """Tabela a tabela, como a `0028`, a `0030`, a `0033` e a `0034`.

    **O `kamba_app` le e nao escreve.** Autorizar um destino e um acto humano
    com papelada arquivada — contrato, retencao zero, nao-treino, numero de
    procedimento da APD — e nao uma escrita de um processo que serve conversas.
    Quem escreve e o `kamba_batch`.

    **E o `kamba_agr` nao ganha nada**, pela razao que a `0023` escreve: o
    KAM-026 deixou-o sem `USAGE` no `platform` de proposito. A porta de destinos
    corre na quinta ligacao do AGR (`kamba-agr:llm`), cujo papel e o
    `kamba_app`.
    """
    op.execute(f"GRANT SELECT ON {DESTINOS} TO {PAPEL_DA_APP}")
    op.execute(f"GRANT SELECT ON {DESTINOS} TO {PAPEL_DE_AUDITORIA}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {DESTINOS} TO {PAPEL_DE_LOTE}"
    )
    # A vista le as duas tabelas, e com `security_invoker` quem a le precisa de
    # privilegio nelas: o `kamba_audit` e o `kamba_batch` tem `SELECT` em
    # `dat.llm_call_log` desde a `0023` e ganham-no aqui no `tenant_destinations`.
    # **O `kamba_app` nao le a vista**: servir uma conversa nao e auditar
    # conformidade, e o criterio 7 e uma pergunta de plataforma.
    op.execute(f"GRANT SELECT ON {VISTA} TO {PAPEL_DE_AUDITORIA}")
    op.execute(f"GRANT SELECT ON {VISTA} TO {PAPEL_DE_LOTE}")


def downgrade() -> None:
    # Sem `CASCADE`, como todas as revisoes desde a `0001`: se houver um objecto
    # pendurado que esta revisao nao criou, o `downgrade` **falha** em vez de o
    # apagar em silencio.
    #
    # A ordem e a inversa do `upgrade`: as politicas, depois a vista (que
    # depende da tabela), depois a tabela. A RLS cai **explicitamente** e nao
    # por efeito do `DROP TABLE`, pela razao do ensaio de mutacao do
    # `canon_lint`.
    op.execute(f"DROP POLICY {POLITICA_GLOBAL} ON {DESTINOS}")
    rls.disable_tenant_rls("tenant_destinations")
    op.execute(f"DROP VIEW {VISTA}")
    # Os doze `CHECK`, a unicidade, a chave primaria e o indice parcial caem com
    # a tabela. Nenhuma funcao e nenhum *trigger* nascem nesta revisao, pelo que
    # nao ha nada a apagar depois.
    op.execute(f"DROP TABLE {DESTINOS}")
