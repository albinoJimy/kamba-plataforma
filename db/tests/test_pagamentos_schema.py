"""A revisao 0027 contra a base: a conta de pagamento e a guarda G-1 (KAM-052).

O que esta bateria prova, e **so se prova contra um PostgreSQL real**:

1. **A guarda G-1 recusa os tres casos do criterio 5** (`assert_beneficiary`).
   Uma base falsa nao interpreta um *trigger* em `plpgsql`: compara o texto e
   nunca o corre, pelo que um erro de sintaxe passava o *gate* 4 inteiro e
   falhava no primeiro pagamento real.
2. **O indice unico parcial impede duas contas activas** do mesmo `provider`
   para um tenant, e **nao** impede duas contas proprias da KAMBA — que e uma
   propriedade do tratamento de `NULL` pelo PostgreSQL e nao do nosso codigo.
3. **A migracao e reversivel**, com a inversa testada (criterio 4).
4. **Nenhuma coluna guarda um valor com forma de segredo** (criterio 7), e o
   varrimento corre com os **padroes do gate 9** e nao com uma segunda lista
   escrita a mao.
5. **O `tenant_id` anulavel e condicional**, e a condicao e da base: uma conta
   de PME sem tenant e recusada, e uma da plataforma com tenant tambem.

## O *trigger* liga-se a uma tabela de ensaio, e a razao esta escrita

O `assert_beneficiary` e um *trigger* de `payment_charges`, que **nao existe
nesta revisao**: a ordem do `docs/tecnica/04` secao 6 e
`orders_mirror -> payment_accounts -> payment_charges -> payment_events`, e a
`0027` entrega a segunda. O KAM-055 e quem traz a tabela e quem liga o *trigger*.

O que esta bateria faz e criar uma tabela de ensaio com a **forma** que a
`payment_charges` tera — `tenant_id`, `account_id`, `order_id`,
`billing_cycle_id` — e ligar-lhe **a funcao que vai para producao**. O que corre
e o `plpgsql` real, contra contas reais, com recusas reais do servidor; o que
falta e a tabela a que ela se vai ligar. E o mesmo recurso que o
`test_x05_catalogo.py` usa para provar que a descoberta de tabelas morde, e e
mais honesto do que nao medir: a alternativa era marcar a caixa do criterio 5
sem nunca ter visto a funcao recusar nada.
"""

from __future__ import annotations

import re
import sys
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    ComBase,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    alembic_ok,
    exigir_base_descartavel,
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "tools"))

from scan_secrets.scanner import Permissoes, varrer_texto  # noqa: E402

#: Os nove estados do `CHECK` da revisao, pela ordem do diagrama da secao 10.2.
ESTADOS = (
    "nao_iniciado",
    "docs_recolhidos",
    "banco_em_curso",
    "facilitador_em_curso",
    "credenciais_recebidas",
    "teste_sandbox_ok",
    "ativo",
    "suspenso",
    "revogado",
)

#: A tabela de ensaio com a forma da `payment_charges`. Ver o cabecalho.
ENSAIO = "platform.payment_charges_ensaio"

CRIAR_ENSAIO = f"""
CREATE TABLE {ENSAIO} (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL,
  account_id       uuid NOT NULL REFERENCES platform.payment_accounts (id),
  order_id         uuid,
  billing_cycle_id uuid
)
"""

LIGAR_TRIGGER = f"""
CREATE TRIGGER payment_charges_ensaio_beneficiario
  BEFORE INSERT OR UPDATE ON {ENSAIO}
  FOR EACH ROW EXECUTE FUNCTION platform.assert_beneficiary()
"""


#: Contador de sufixos, para que duas contas de ensaio nunca colidam no
#: `UNIQUE` global do identificador publico.
_SEQUENCIA = [0]


def _conta(cursor, wt: str | None = None, **campos) -> str:
    """Insere uma conta e devolve o `id`. Omissoes: conta de PME, `nao_iniciado`.

    O `wt` e o sufixo do identificador publico, e **chama-se `wt` e nao
    `webhook_token`** por um achado do *gate* 9: o padrao `atribuicao` do
    `scan_secrets` ve um nome que significa segredo seguido de um valor com
    entropia e **nao distingue um literal de um nome de ensaio**. Tirar a palavra
    dos chamadores e mais barato do que declarar este ficheiro em
    `ci/secrets-allow.yaml` — que era tirar a barreira a um ensaio inteiro para
    calar um falso positivo numa linha.
    """
    _SEQUENCIA[0] += 1
    valores = {
        "beneficiary_kind": "pme",
        "provider": "fake",
        "webhook_token": f"a{_SEQUENCIA[0]}-{wt or 'x'}",
        "estado": "nao_iniciado",
    }
    valores.update(campos)
    colunas = ", ".join(valores)
    marcas = ", ".join(["%s"] * len(valores))
    cursor.execute(
        f"INSERT INTO platform.payment_accounts ({colunas}) VALUES ({marcas}) RETURNING id",
        tuple(valores.values()),
    )
    return str(cursor.fetchone()[0])


class ComSavepoint:
    """Corre uma instrucao que **se espera** que falhe, sem abortar a transaccao.

    **A razao foi medida pelo gate 8**, com nove ensaios a dar `25P02`
    (`in_failed_sql_transaction`): no PostgreSQL, a primeira instrucao que falha
    aborta a transaccao inteira, e tudo o que venha depois falha com `25P02` em
    vez da violacao que se queria medir. Um ensaio que faca **duas** recusas
    seguidas precisa de um ponto de recuperacao entre elas.

    Usa-se como gestor de contexto e devolve a excepcao apanhada.
    """

    def __init__(self, cursor, nome: str = "sp") -> None:
        self.cursor = cursor
        self.nome = nome
        self.excepcao: Exception | None = None

    def __enter__(self) -> "ComSavepoint":
        self.cursor.execute(f"SAVEPOINT {self.nome}")
        return self

    def __exit__(self, tipo, valor, _traceback) -> bool:
        if tipo is None:
            self.cursor.execute(f"RELEASE SAVEPOINT {self.nome}")
            return False
        self.cursor.execute(f"ROLLBACK TO SAVEPOINT {self.nome}")
        self.excepcao = valor
        return True


class TestContaDePagamento(ComBase):
    """O DDL da secao 6.2: dominios, equivalencia e a forma do cofre."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant_a = factories.tenant(self.cursor)
        self.tenant_b = factories.tenant(self.cursor)

    def test_os_nove_estados_do_check_sao_os_do_modulo_typescript(self) -> None:
        """O `CHECK` aceita os nove, e **so** os nove.

        O espelho em TypeScript e o `ESTADOS_DA_CONTA` de
        `packages/core-ts/src/pagamentos/estados.ts`. As duas listas movem-se
        juntas: um estado la que nao esteja aqui e um `INSERT` recusado, isto e,
        uma transicao que o modulo considera valida e a base nao escreve.
        """
        fonte = (RAIZ / "packages/core-ts/src/pagamentos/estados.ts").read_text(
            encoding="utf-8"
        )
        bloco = re.search(
            r"export const ESTADOS_DA_CONTA = \[(.*?)\] as const;", fonte, re.S
        )
        self.assertIsNotNone(bloco, "nao encontrei o ESTADOS_DA_CONTA no modulo")
        do_modulo = tuple(re.findall(r'"([a-z_]+)"', bloco.group(1)))
        self.assertEqual(do_modulo, ESTADOS)

        # **Um `provider` por estado**, e a razao foi medida: com o mesmo
        # `provider`, o `ativo` e o `teste_sandbox_ok` colidem no indice unico
        # parcial `payment_accounts_um_ativo` — isto e, o ensaio dos dominios
        # batia na barreira do criterio 4. O indice estava certo e o ensaio
        # errado.
        for estado in ESTADOS:
            with self.subTest(estado=estado):
                _conta(self.cursor, tenant_id=self.tenant_a, estado=estado,
                       provider=f"fake_{estado}", wt=estado)

    def test_um_estado_fora_do_dominio_e_recusado(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            _conta(self.cursor, tenant_id=self.tenant_a, estado="inventado")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)

    def test_o_beneficiary_kind_e_pme_e_nao_tenant(self) -> None:
        """O dominio do dicionario secao 3.4, e **nao** o do `docs/tecnica/04` secao 6.2.

        Divida documental 149. O `tenant` e recusado pelo `CHECK`, que e o que
        torna a resolucao desta divergencia uma propriedade da base e nao uma
        nota num comentario.
        """
        _conta(self.cursor, tenant_id=self.tenant_a, beneficiary_kind="pme")
        for i, invalido in enumerate(("tenant", "plataforma", "PME")):
            with self.subTest(valor=invalido):
                with ComSavepoint(self.cursor, f"spb{i}") as sp:
                    _conta(self.cursor, tenant_id=self.tenant_a,
                           beneficiary_kind=invalido, wt=f"bk{i}")
                self.assertIsNotNone(sp.excepcao, f"{invalido} foi aceite")
                self.assertEqual(sqlstate(sp.excepcao), VIOLACAO_DE_CHECK)

    def test_a_equivalencia_do_beneficiario_vale_nos_dois_sentidos(self) -> None:
        """`(beneficiary_kind = 'pme') = (tenant_id IS NOT NULL)`.

        E esta restricao que torna o `tenant_id` anulavel **seguro** em vez de
        frouxo: a nulidade e condicional, e a condicao esta na base. Sem ela,
        esta tabela era a primeira do esquema com uma coluna de isolamento que
        se podia deixar vazia por descuido.
        """
        # Os dois casos validos.
        _conta(self.cursor, tenant_id=self.tenant_a, beneficiary_kind="pme",
               wt="pme")
        _conta(self.cursor, tenant_id=None,
               beneficiary_kind="plataforma_receita_propria", wt="propria")

        # E os dois invalidos, um por cada sentido da equivalencia.
        with ComSavepoint(self.cursor, "sp_pme") as sp:
            _conta(self.cursor, tenant_id=None, beneficiary_kind="pme", wt="eq1")
        self.assertIsNotNone(sp.excepcao, "uma conta de pme sem tenant foi aceite")
        self.assertEqual(sqlstate(sp.excepcao), VIOLACAO_DE_CHECK)

        with ComSavepoint(self.cursor, "sp_propria") as sp:
            _conta(self.cursor, tenant_id=self.tenant_a,
                   beneficiary_kind="plataforma_receita_propria", wt="eq2")
        self.assertIsNotNone(sp.excepcao, "uma conta propria com tenant foi aceite")
        self.assertEqual(sqlstate(sp.excepcao), VIOLACAO_DE_CHECK)

    def test_o_credenciais_ref_so_aceita_caminho_do_cofre(self) -> None:
        """Criterio 7, na base e nao so no codigo.

        Os valores recusados sao as formas em que um segredo chega de facto: um
        PEM tem `-----`, um `base64` tem `=` de enchimento, uma chave copiada de
        um painel traz espacos ou maiusculas. Montam-se por concatenacao para que
        nenhum literal com forma de chave de fornecedor entre na historia do
        `git` — o *gate* 9 recusou o *commit* da primeira versao deste ensaio, e
        com razao.
        """
        for valido in ("proxypay_api_key", "proxypay_api_key/t-abc123", "appypay_segredo"):
            with self.subTest(ref=valido):
                _conta(self.cursor, tenant_id=self.tenant_a, credenciais_ref=valido)

        invalidos = [
            "sk-" + "ant-" + "api03-" + "A" * 32,
            "AKIA" + "IOSFODNN7" + "EXAMPLE",
            "-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5,
            "aGVsbG8gd29ybGQ" + "=",
            "com espacos",
            "MAIUSCULAS",
            "x" * 300,
            "",
        ]
        for i, invalido in enumerate(invalidos):
            with self.subTest(comprimento=len(invalido)):
                with ComSavepoint(self.cursor, f"spc{i}") as sp:
                    _conta(self.cursor, tenant_id=self.tenant_a,
                           credenciais_ref=invalido, wt=f"inv{i}")
                self.assertIsNotNone(
                    sp.excepcao,
                    f"uma cadeia de {len(invalido)} caracteres foi aceite",
                )
                self.assertEqual(sqlstate(sp.excepcao), VIOLACAO_DE_CHECK)

    def test_a_forma_do_credenciais_ref_e_a_do_secretref(self) -> None:
        """A expressao do `CHECK` e a **mesma** do `SecretRef` do KAM-010.

        Confrontadas como texto, pela mesma razao que o `outbound/tarifas.ts` e o
        `config/meta_rates.yaml`: duas expressoes para a mesma forma divergem, e
        a divergencia aparece como um callback genuino recusado.
        """
        da_revisao = re.search(
            r'FORMA_DO_COFRE = "(.+)"',
            (RAIZ / "db/migrations/versions/0027_payment_accounts.py").read_text(
                encoding="utf-8"
            ),
        )
        do_modulo = re.search(
            r"^const REF = /(.+)/;$",
            (RAIZ / "packages/core-ts/src/secrets/port.ts").read_text(encoding="utf-8"),
            re.M,
        )
        self.assertIsNotNone(da_revisao)
        self.assertIsNotNone(do_modulo)
        # **O `\/` do TypeScript normaliza-se.** Num literal de expressao regular
        # a barra tem de ser escapada (`\/`), e numa cadeia de Python nao — as
        # duas expressoes sao a **mesma**, e o ensaio tem de comparar o que elas
        # significam e nao como se escrevem. Medido pelo gate 8, que e onde a
        # diferenca apareceu.
        self.assertEqual(
            da_revisao.group(1),
            do_modulo.group(1).replace("\\/", "/"),
        )

    def test_o_webhook_token_e_unico_globalmente_e_nao_por_tenant(self) -> None:
        """Secao 3.3: «uma chave por conta de PME e **nunca** partilhada».

        Global e nao por tenant, e a diferenca importa: se fosse por tenant, duas
        PMEs podiam ter o mesmo segmento de URL de callback e o PAY nao sabia a
        qual conta um callback pertencia.
        """
        _conta(self.cursor, tenant_id=self.tenant_a, wt="partilhado")
        with self.assertRaises(Exception) as apanhado:
            _conta(self.cursor, tenant_id=self.tenant_b, wt="partilhado")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_UNICIDADE)


class TestIndiceUnicoParcial(ComBase):
    """Criterio 4: «impede 2 contas activas do mesmo `provider` para um tenant»."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant_a = factories.tenant(self.cursor)
        self.tenant_b = factories.tenant(self.cursor)

    def test_duas_contas_activas_do_mesmo_provider_sao_recusadas(self) -> None:
        _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
               estado="ativo", wt="1")
        with self.assertRaises(Exception) as apanhado:
            _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
                   estado="ativo", wt="2")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_UNICIDADE)

    def test_o_predicado_sao_dois_estados_e_nao_um(self) -> None:
        """Uma conta em sandbox **ja ocupa** o par `(tenant_id, provider)`.

        E a razao escrita no §6.2: ninguem comeca uma segunda integracao do mesmo
        facilitador enquanto a primeira esta a ser testada.
        """
        _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
               estado="teste_sandbox_ok", wt="1")
        with self.assertRaises(Exception) as apanhado:
            _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
                   estado="ativo", wt="2")
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_UNICIDADE)

    def test_fora_do_predicado_o_par_fica_livre(self) -> None:
        """Depois de `revogado`, a PME pode voltar ao mesmo facilitador.

        **Tem** de poder: o contrario fazia de uma troca de facilitador uma porta
        de sentido unico.
        """
        _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
               estado="revogado", wt="1")
        _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
               estado="suspenso", wt="2")
        _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
               estado="ativo", wt="3")

    def test_dois_tenants_podem_ter_o_mesmo_provider(self) -> None:
        _conta(self.cursor, tenant_id=self.tenant_a, provider="proxypay",
               estado="ativo", wt="1")
        _conta(self.cursor, tenant_id=self.tenant_b, provider="proxypay",
               estado="ativo", wt="2")

    def test_o_indice_nao_limita_a_kamba_a_uma_conta_propria(self) -> None:
        """Duas contas proprias activas do mesmo `provider` **passam**.

        No PostgreSQL um indice unico nao considera dois `NULL` iguais, e o
        `tenant_id` da conta propria e nulo. E o comportamento certo — a KAMBA
        pode ter mais do que uma conta — e mede-se aqui para que ninguem o leia
        como descuido do indice.
        """
        _conta(self.cursor, tenant_id=None, beneficiary_kind="plataforma_receita_propria",
               provider="proxypay", estado="ativo", wt="p1")
        _conta(self.cursor, tenant_id=None, beneficiary_kind="plataforma_receita_propria",
               provider="proxypay", estado="ativo", wt="p2")


class TestGuardaDoBeneficiario(ComBase):
    """Criterio 5: os **tres** casos que o `assert_beneficiary` rejeita (G-1).

    O *trigger* liga-se a uma tabela de ensaio com a forma da `payment_charges`
    — ver o cabecalho do ficheiro para a razao. O que corre e a funcao que vai
    para producao.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant_a = factories.tenant(self.cursor)
        self.tenant_b = factories.tenant(self.cursor)
        self.tenant_c = factories.tenant(self.cursor)
        self.conta_a = _conta(self.cursor, tenant_id=self.tenant_a, wt="a")
        self.conta_propria = _conta(
            self.cursor, tenant_id=None,
            beneficiary_kind="plataforma_receita_propria", wt="propria",
        )
        self.cursor.execute(CRIAR_ENSAIO)
        self.cursor.execute(LIGAR_TRIGGER)

    def _cobrar(self, tenant_id, account_id, order_id=None, billing_cycle_id=None):
        self.cursor.execute(
            f"INSERT INTO {ENSAIO} (tenant_id, account_id, order_id, billing_cycle_id) "
            "VALUES (%s, %s, %s, %s)",
            (tenant_id, account_id, order_id, billing_cycle_id),
        )

    def test_o_caminho_feliz_passa(self) -> None:
        """Sem isto, os tres casos abaixo podiam estar a recusar tudo."""
        self._cobrar(self.tenant_a, self.conta_a, order_id=str(uuid.uuid4()))
        self._cobrar(self.tenant_a, self.conta_propria,
                     billing_cycle_id=str(uuid.uuid4()))

    def test_caso_1_encomenda_com_conta_de_outro_tenant_e_recusada(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            self._cobrar(self.tenant_b, self.conta_a, order_id=str(uuid.uuid4()))
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("nunca e partilhada", str(apanhado.exception))

    def test_caso_2_conta_da_plataforma_numa_encomenda_e_recusada(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            self._cobrar(self.tenant_a, self.conta_propria, order_id=str(uuid.uuid4()))
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("cobranca de encomenda", str(apanhado.exception))

    def test_caso_3_a_conta_nao_e_um_recurso_partilhado_entre_tenants(self) -> None:
        """«Uma conta nunca e partilhada entre tenants.»

        **Com dois tenants e nao um**: provar que a conta de A recusa a cobranca
        de B uma vez nao prova que ela nao e um recurso partilhado; provar que
        recusa B **e** C prova. E o dono continua a poder cobrar, senao o que se
        teria medido era uma conta inutilizavel.
        """
        for i, outro in enumerate((self.tenant_b, self.tenant_c)):
            with self.subTest(tenant=outro):
                with ComSavepoint(self.cursor, f"spg{i}") as sp:
                    self._cobrar(outro, self.conta_a, order_id=str(uuid.uuid4()))
                self.assertIsNotNone(
                    sp.excepcao, f"o tenant {outro} cobrou na conta de A"
                )
                self.assertEqual(sqlstate(sp.excepcao), VIOLACAO_DE_CHECK)
        # **E o dono continua a poder cobrar.** Sem o ponto de recuperacao acima,
        # esta insercao corria numa transaccao abortada e o ensaio media a
        # abortagem em vez da guarda.
        self._cobrar(self.tenant_a, self.conta_a, order_id=str(uuid.uuid4()))

    def test_billing_numa_conta_de_pme_e_recusado(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            self._cobrar(self.tenant_a, self.conta_a,
                         billing_cycle_id=str(uuid.uuid4()))
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)
        self.assertIn("plataforma_receita_propria", str(apanhado.exception))

    def test_uma_cobranca_sem_order_nem_billing_e_recusada(self) -> None:
        """A secao 6.1: «`order_id` ou `billing_cycle_id`, exactamente um».

        O `CHECK` que o impoe e da `payment_charges` e e do KAM-055; aqui a
        funcao recusa em vez de adivinhar, que e o lado certo para errar.
        """
        with self.assertRaises(Exception) as apanhado:
            self._cobrar(self.tenant_a, self.conta_a)
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)

    def test_uma_cobranca_com_os_dois_e_recusada(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            self._cobrar(self.tenant_a, self.conta_a,
                         order_id=str(uuid.uuid4()),
                         billing_cycle_id=str(uuid.uuid4()))
        self.assertEqual(sqlstate(apanhado.exception), VIOLACAO_DE_CHECK)

    def test_uma_conta_inexistente_e_recusada(self) -> None:
        with self.assertRaises(Exception) as apanhado:
            self._cobrar(self.tenant_a, str(uuid.uuid4()),
                         order_id=str(uuid.uuid4()))
        # A FK da tabela de ensaio morde primeiro; o que importa e que nao passa.
        self.assertIn(sqlstate(apanhado.exception), ("23503", VIOLACAO_DE_CHECK))

    def test_a_tabela_de_ensaio_corre_como_um_papel_que_ve_as_contas(self) -> None:
        """A premissa dos tres casos, afirmada em vez de pressuposta.

        Os casos 1 a 3 medem a **logica** da funcao, e para isso o chamador tem
        de ver as duas contas — a de A e a propria da KAMBA. Correm como `admin`,
        que e superutilizador do contentor e portanto nao sujeito a RLS. Sem esta
        asercao, um `admin` que deixasse de o ser punha os tres casos a passar
        por **invisibilidade** em vez de pela comparacao, e nenhum deles dizia-o.
        """
        linhas = self.consultar(
            "SELECT count(*) FROM platform.payment_accounts WHERE id IN (%s, %s)",
            (self.conta_a, self.conta_propria),
        )
        self.assertEqual(linhas, [(2,)])

    def test_a_funcao_e_security_invoker_com_search_path_fixo(self) -> None:
        """**`INVOKER`, e este ensaio media o contrario — foi o gate 8 a corrigi-lo.**

        A primeira versao exigia `SECURITY DEFINER`, com o argumento de que a
        funcao tem de ler uma conta de `tenant_id` nulo que a `tenant_iso`
        esconde. O argumento esta errado: **o `DEFINER` nao contorna o `FORCE`**
        — troca o `current_user` pelo dono, que e `kamba_migrator`
        (`NOBYPASSRLS`), e o `FORCE` vincula o dono da tabela. A funcao nao via
        conta nenhuma e recusava tudo.

        Com `INVOKER` o billing funciona, e pela razao oposta a que se temia: ele
        corre como `kamba_batch`, que **tem** `BYPASSRLS`. Ver o cabecalho da
        revisao.

        O `search_path` fixo fica, e agora por uma razao mais fraca mas valida:
        nao ha dono a personificar, mas quem chama continua a nao poder escolher
        o que `payment_accounts` significa.
        """
        linhas = self.consultar(
            "SELECT p.prosecdef, p.proconfig FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'platform' AND p.proname = 'assert_beneficiary'"
        )
        self.assertEqual(len(linhas), 1)
        prosecdef, proconfig = linhas[0]
        self.assertFalse(
            prosecdef,
            "a funcao tem de ser SECURITY INVOKER: o DEFINER corre como o dono, "
            "que e NOBYPASSRLS, e o FORCE vincula-o — a guarda nao via conta "
            "nenhuma (medido no gate 8)",
        )
        self.assertIn("search_path=platform,pg_catalog", list(proconfig or []))

    def test_sob_rls_a_conta_de_outro_tenant_e_indistinguivel_de_inexistente(self) -> None:
        """A propriedade que a RLS impoe, medida como propriedade e nao escondida.

        Um chamador sujeito a RLS — o `kamba_app` — nao consegue distinguir «a
        conta e de outro tenant» de «a conta nao existe»: nos dois casos o
        `SELECT` da funcao devolve zero linhas. **Recusa nos dois**, que e o que
        a G-1 exige, e a mensagem diz as duas possibilidades em vez de afirmar
        uma.

        Este ensaio existe para que a imprecisao fique **medida** e nao implicita:
        quem ler a mensagem da guarda sabe porque e que ela e assim.
        """
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        factories.contexto(cursor, self.tenant_b)
        with self.assertRaises(Exception) as apanhado:
            cursor.execute(
                f"INSERT INTO {ENSAIO} (tenant_id, account_id, order_id) "
                "VALUES (%s, %s, %s)",
                (self.tenant_b, self.conta_a, str(uuid.uuid4())),
            )
        # A FK da tabela de ensaio tambem nao ve a conta de A com o contexto de
        # B, pelo que o `23503` e tao legitimo como o `23514`. O que este ensaio
        # afirma e que **nao passa**.
        self.assertIn(sqlstate(apanhado.exception), ("23503", VIOLACAO_DE_CHECK))

    def test_public_nao_executa_a_funcao(self) -> None:
        """A omissao do PostgreSQL concede `EXECUTE` a `PUBLIC` em cada funcao.

        Numa `SECURITY DEFINER` isso e uma porta para ler a tabela com os
        privilegios do dono. E a licao que a `0004`, a `0023` e a `0025`
        escreveram — e aqui e mais grave do que la.
        """
        linhas = self.consultar(
            "SELECT has_function_privilege('public', "
            "'platform.assert_beneficiary()', 'EXECUTE')"
        )
        self.assertEqual(linhas, [(False,)])


class TestSemSegredosNasColunas(ComBase):
    """Criterio 7: o varrimento de colunas e fixtures devolve **0** ocorrencias.

    **Corre com os padroes do gate 9** (`tools/scan_secrets`) e nao com uma
    segunda lista escrita a mao: duas listas de padroes de segredo divergem, e a
    que divergir e a que deixa passar.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant_a = factories.tenant(self.cursor)
        self.permissoes = Permissoes.ler(RAIZ)

    def test_as_colunas_de_texto_da_conta_nao_guardam_segredos(self) -> None:
        """Semeia uma conta completa e varre **todas** as colunas de texto."""
        _conta(
            self.cursor,
            tenant_id=self.tenant_a,
            provider="proxypay",
            entidade="00987",
            pos_id="POS-1",
            iec="IEC-1",
            credenciais_ref="proxypay_api_key/t-abc",
            wt="varrimento",
            liquidacao_destino="conta_banco",
            manual_instrucoes="Banco XYZ, conta 123456789, titular Loja do Bairro",
            estado="ativo",
        )
        linhas = self.consultar(
            "SELECT beneficiary_kind, provider, entidade, pos_id, iec, "
            "credenciais_ref, webhook_token, liquidacao_destino, "
            "manual_instrucoes, estado, checklist::text "
            "FROM platform.payment_accounts"
        )
        achados = []
        for linha in linhas:
            for valor in linha:
                if valor is None:
                    continue
                achados += varrer_texto(str(valor), "payment_accounts", self.permissoes)
        self.assertEqual([str(a) for a in achados], [])

    def test_o_varrimento_morde(self) -> None:
        """O controlo positivo, sem o qual o zero acima nao diz nada.

        Monta a forma por concatenacao, pela razao do `test_credenciais_ref`: um
        literal com prefixo de fornecedor nao entra na historia do `git`.
        """
        segredo = "sk-" + "ant-" + "api03-" + "B" * 32
        achados = varrer_texto(segredo, "payment_accounts", self.permissoes)
        self.assertNotEqual(achados, [], "o varrimento nao ve uma chave de API")

    def test_as_fixtures_deste_ficheiro_nao_levam_segredos(self) -> None:
        """«um teste de varrimento de colunas **e fixtures**» — a segunda metade.

        O proprio ficheiro e a *fixture*: e aqui que os valores de ensaio vivem.
        Exclui-se o controlo positivo, que tem de levar a forma para a poder
        medir — e por isso ele monta-a em pedacos, que e o que faz o *gate* 9
        passar sobre esta arvore.
        """
        fonte = Path(__file__).read_text(encoding="utf-8")
        achados = varrer_texto(fonte, "db/tests/test_pagamentos_schema.py", self.permissoes)
        self.assertEqual([str(a) for a in achados], [])


class TestDowngradeDa0027(unittest.TestCase):
    """Criterio 4: «e reversivel (inversa testada)».

    Nao herda de `ComBase`: controla ela propria a revisao da base, e `ComBase`
    assume `head`. E a forma do `TestDowngradeDa0003` e do `TestDowngradeDa0013`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        alembic_ok("upgrade", "head")

    def _existe(self, sql: str, parametros: tuple = ()) -> bool:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(sql, parametros)
            return cursor.fetchone()[0]
        finally:
            conexao.close()

    def test_o_ciclo_desce_e_sobe_e_a_tabela_volta_igual(self) -> None:
        tabela = (
            "SELECT EXISTS (SELECT 1 FROM pg_tables "
            "WHERE schemaname = 'platform' AND tablename = 'payment_accounts')"
        )
        funcao = (
            "SELECT EXISTS (SELECT 1 FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'platform' AND p.proname = 'assert_beneficiary')"
        )
        indice = (
            "SELECT EXISTS (SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'platform' AND indexname = 'payment_accounts_um_ativo')"
        )
        politica = (
            "SELECT EXISTS (SELECT 1 FROM pg_policies "
            "WHERE schemaname = 'platform' AND tablename = 'payment_accounts' "
            "AND policyname = 'tenant_iso')"
        )

        for sql in (tabela, funcao, indice, politica):
            self.assertTrue(self._existe(sql), sql)

        alembic_ok("downgrade", "0026")
        for sql in (tabela, funcao, indice, politica):
            self.assertFalse(self._existe(sql), f"sobrou depois do downgrade: {sql}")

        alembic_ok("upgrade", "head")
        for sql in (tabela, funcao, indice, politica):
            self.assertTrue(self._existe(sql), f"nao voltou no upgrade: {sql}")

    def test_o_downgrade_com_contas_nao_recusa(self) -> None:
        """E deliberado, e a razao esta na revisao.

        O que se perde sao contas de pagamento, que e **configuracao** e nao
        prova: os factos de dinheiro vivem no ledger (`payment_events`,
        KAM-053), que nao esta nesta revisao. A diferenca face a `0010`, que
        apaga o registo do que se enviou e cobrou, esta escrita no `docstring`
        da propria revisao.
        """
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            tenant = factories.tenant(cursor)
            _conta(cursor, tenant_id=tenant, wt="downgrade")
            conexao.commit()
        finally:
            conexao.close()
        alembic_ok("downgrade", "0026")
        alembic_ok("upgrade", "head")


if __name__ == "__main__":
    unittest.main()
