"""O acesso de excepcao a um host no `audit_log` (KAM-259, revisao `0093`).

Tres coisas, contra um PostgreSQL real:

* **a porta** — o `kamba_breakglass` escreve as duas accoes de *break-glass*
  pela `breakglass_registar`, na cadeia de plataforma, e nada mais: nem outra
  accao, nem `INSERT` directo, nem leitura; e ninguem mais executa a porta;
* **o portao** — o `sessao` de `infra/modules/host-base/kamba_breakglass.py`,
  ligado a base com o papel verdadeiro: a linha de abertura esta confirmada
  **antes** de a *shell* abrir, e sem ela a *shell* nunca abre (falha fechada);
* **o encadeamento** — as duas linhas da sessao ficam elos da cadeia de
  plataforma como as outras, recalculados em Python.

O portao confirma cada linha (e isso que o torna portao), pelo que estes
ensaios escrevem linhas confirmadas na cadeia de plataforma. Cada classe tira
as suas no fim e repoe a cabeca da cadeia que encontrou, pela forma do
`test_rotacao_de_chaves.py`.

O downgrade da `0093` desce pelo `down_revision` lido do ficheiro e nao exige
`em_head()` depois de recusar, pela licao do KAM-089.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ligacao
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_auditoria import ACCOES, CHAVE_DA_PLATAFORMA, _desligar, _religar, row_hash

RAIZ = Path(__file__).resolve().parents[2]
PORTAO = RAIZ / "infra" / "modules" / "host-base" / "kamba_breakglass.py"
VERSOES = RAIZ / "db" / "migrations" / "versions"

#: A chave publica de ensaio (um par descartavel, gerado para este ensaio) e a
#: impressao que o `ssh-keygen -lf` lhe deu. O oraculo e o `ssh-keygen`, e nao
#: o codigo do portao: copiar a formula para aqui nao provava nada.
CHAVE_DE_ENSAIO = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMEzBWUe09ym3vyLX3dhSWmeb6eE8UtgunLtsIrgmF9y "
    "ensaio-kam-259"
)
IMPRESSAO_DE_ENSAIO = "SHA256:OmmXHchDo5AU/LdJfYTu56Ywd0O16y/MvtNjs3qrHvA"


def _portao():
    """O modulo do portao, carregado pelo caminho: nao e um pacote instalado."""
    especificacao = importlib.util.spec_from_file_location("kamba_breakglass", PORTAO)
    modulo = importlib.util.module_from_spec(especificacao)
    # O `dataclass` procura o modulo em `sys.modules` para resolver as anotacoes.
    sys.modules[especificacao.name] = modulo
    especificacao.loader.exec_module(modulo)
    return modulo


bg = _portao()


def _revisao() -> tuple[str, str]:
    """`(revision, down_revision)` da revisao desta suite, lidos do ficheiro."""
    [ficheiro] = list(VERSOES.glob("*_breakglass_auditado.py"))
    texto = ficheiro.read_text(encoding="utf-8")
    revisao = re.search(r'^revision = "(\d{4})"$', texto, re.M)
    abaixo = re.search(r'^down_revision = "(\d{4})"$', texto, re.M)
    assert revisao and abaixo, "a revisao nao declara revision e down_revision"
    return revisao.group(1), abaixo.group(1)


def _sha(texto: str) -> bytes:
    return hashlib.sha256(texto.encode("utf-8")).digest()


def _actor() -> str:
    """Um actor so deste caso: e por ele que a limpeza encontra as linhas."""
    return f"SHA256:ensaio-{uuid.uuid4().hex}"


def _pedido(actor: str, **mudar) -> "bg.Pedido":
    campos = dict(
        actor=actor,
        ambiente="staging",
        host="kamba-staging-1",
        razao="revisao independente, area 6",
        prazo=datetime.now(timezone.utc) + timedelta(hours=1),
        sessao=uuid.uuid4().hex,
    )
    campos.update(mudar)
    return bg.Pedido(**campos)


class _ComCadeiaDePlataforma(ComBase):
    """Guarda a cabeca da cadeia de plataforma e repoe-na no fim da classe."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._actores: list[str] = []
        conexao = ligacao.ligar("admin")
        try:
            cls._cabeca = cls._ler_cabeca(conexao.cursor())
        finally:
            conexao.close()

    @classmethod
    def tearDownClass(cls) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            _desligar(c)
            c.execute("DELETE FROM platform.audit_log WHERE actor_id = ANY(%s)", (cls._actores,))
            _religar(c)
            if cls._cabeca is None:
                c.execute(
                    "DELETE FROM platform.audit_heads WHERE chave = %s::uuid", (CHAVE_DA_PLATAFORMA,)
                )
            else:
                c.execute(
                    "UPDATE platform.audit_heads SET last_hash = %s WHERE chave = %s::uuid",
                    (cls._cabeca, CHAVE_DA_PLATAFORMA),
                )
            conexao.commit()
        finally:
            conexao.close()

    @staticmethod
    def _ler_cabeca(cursor):
        cursor.execute(
            "SELECT last_hash FROM platform.audit_heads WHERE chave = %s::uuid",
            (CHAVE_DA_PLATAFORMA,),
        )
        linha = cursor.fetchone()
        return None if linha is None else bytes(linha[0])

    def actor(self) -> str:
        actor = _actor()
        self._actores.append(actor)
        return actor

    def linhas_de(self, actor: str) -> list[tuple]:
        """As linhas confirmadas de um actor, lidas por uma ligacao **nova**."""
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT tenant_id, actor_type, actor_id, action, entity, entity_id, turn_id, "
                "       payload_hash, prev_hash, row_hash, criado_at, id "
                "  FROM platform.audit_log WHERE actor_id = %s ORDER BY id",
                (actor,),
            )
            return [tuple(linha) for linha in c.fetchall()]
        finally:
            conexao.close()

    def gravar(self):
        """O `Gravar` do portao sobre o papel verdadeiro."""
        return bg.gravar_por_ligacao(lambda: ligacao.ligar("breakglass"))

    def gravar_pelo_psql(self):
        """O `Gravar` do host: o `docker exec ... psql` no contentor da base.

        O contentor e o que o `db/gate_bd.py` levanta, com a imagem do
        PostgreSQL de `prod` (`ci/supply-chain/imagens.yaml`), e por isso com o
        mesmo `psql`. O nome chega em `KAMBA_GATE_CONTENTOR`; sem ele, falha, e
        nao salta.
        """
        contentor = os.environ.get("KAMBA_GATE_CONTENTOR")
        self.assertTrue(contentor, "KAMBA_GATE_CONTENTOR por definir: corre pelo db/gate_bd.py")
        _utilizador, senha = ligacao.credenciais("breakglass")
        return bg.gravar_pelo_psql(contentor, ligacao.alvo().base, senha)


class TestAPorta(_ComCadeiaDePlataforma):
    """O que o `kamba_breakglass` pode, e o que mais ninguem pode."""

    def test_escreve_as_duas_accoes_na_cadeia_de_plataforma(self) -> None:
        actor = self.actor()
        gravar = self.gravar()
        gravar("breakglass.open", actor, "staging/kamba-staging-1", _sha("a"))
        gravar("breakglass.close", actor, "staging/kamba-staging-1", _sha("a"))
        self.assertEqual(
            [linha[:7] for linha in self.linhas_de(actor)],
            [
                (None, "staff", actor, "breakglass.open", "host", "staging/kamba-staging-1", None),
                (None, "staff", actor, "breakglass.close", "host", "staging/kamba-staging-1", None),
            ],
        )

    def test_recusa_qualquer_outra_accao(self) -> None:
        c = self.ligar("breakglass").cursor()
        for accao in ("batch.run", "price.update", "secret.revoke", "audit.read"):
            with self.subTest(accao=accao):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, c, bg.SQL_REGISTAR, (accao, "x", "staging/h", _sha("x"))
                )

    def test_nao_escreve_nem_le_a_tabela_directamente(self) -> None:
        c = self.ligar("breakglass").cursor()
        for instrucao in (
            "INSERT INTO platform.audit_log (tenant_id, actor_type, actor_id, action, entity, "
            "entity_id, turn_id, payload_hash) VALUES (NULL, 'staff', 'x', 'breakglass.open', "
            "'host', 'h', NULL, sha256('x'::bytea))",
            "SELECT count(*) FROM platform.audit_log",
            "SELECT count(*) FROM platform.audit_heads",
            "SELECT platform.audit_append(NULL, 'staff', 'x', 'breakglass.open', 'host', 'h', "
            "NULL, sha256('x'::bytea))",
        ):
            with self.subTest(instrucao=instrucao[:50]):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, c, instrucao)

    def test_so_o_kamba_breakglass_executa_a_porta(self) -> None:
        for identidade in sorted(set(ligacao.PAPEIS) - {"breakglass", "migrator"}):
            with self.subTest(identidade=identidade):
                c = self.ligar(identidade).cursor()
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, c, bg.SQL_REGISTAR,
                    ("breakglass.open", "x", "staging/h", _sha("x")),
                )
        [(executa,)] = self.consultar(
            "SELECT has_function_privilege('public', "
            "'platform.breakglass_registar(text, text, text, bytea)', 'EXECUTE')"
        )
        self.assertFalse(executa)

    def test_o_dono_sem_a_variavel_nao_escreve_a_cadeia_de_plataforma(self) -> None:
        """A politica e do dono, so com a variavel, e so para as duas accoes."""
        c = self.ligar("migrator").cursor()
        insercao = (
            "INSERT INTO platform.audit_log (tenant_id, actor_type, actor_id, action, entity, "
            "entity_id, turn_id, payload_hash) VALUES (NULL, 'staff', 'x', %s, 'host', 'h', "
            "NULL, sha256('x'::bytea))"
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, c, insercao, ("breakglass.open",))
        c.execute("SELECT set_config('app.registo_breakglass', 'on', true)")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, c, insercao, ("batch.run",))
        # E so sem tenant: com a variavel ligada e a accao certa, uma linha na
        # cadeia de um tenant continua recusada (e so a `tenant_iso` a decide).
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, c,
            "INSERT INTO platform.audit_log (tenant_id, actor_type, actor_id, action, entity, "
            "entity_id, turn_id, payload_hash) VALUES (gen_random_uuid(), 'staff', 'x', "
            "'breakglass.open', 'host', 'h', NULL, sha256('x'::bytea))",
        )

    def test_a_porta_desliga_a_variavel_que_ligou(self) -> None:
        conexao = self.ligar("breakglass")
        c = conexao.cursor()
        c.execute(bg.SQL_REGISTAR, ("breakglass.open", self.actor(), "staging/h", _sha("v")))
        c.execute("SELECT current_setting('app.registo_breakglass', true)")
        self.assertEqual(c.fetchone()[0], "off")

    def test_a_porta_e_definer_com_caminho_fixo(self) -> None:
        self.assertEqual(
            self.consultar(
                "SELECT p.prosecdef, p.proconfig::text FROM pg_proc p "
                "  JOIN pg_namespace n ON n.oid = p.pronamespace "
                " WHERE n.nspname = 'platform' AND p.proname = 'breakglass_registar'"
            ),
            [(True, "{\"search_path=pg_catalog, platform\"}")],
        )

    def test_o_dominio_tem_o_fecho(self) -> None:
        [(definicao,)] = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'"
        )
        self.assertIn("'breakglass.close'", definicao)
        self.assertEqual(definicao.count("'::text"), len(ACCOES))


class TestOPortaoContraABase(_ComCadeiaDePlataforma):
    """O criterio 3: sem a linha de abertura confirmada, a shell nao abre."""

    def test_a_linha_de_abertura_esta_confirmada_antes_da_shell(self) -> None:
        actor = self.actor()
        pedido = _pedido(actor)
        visto_pela_shell: list[list[tuple]] = []

        def shell(segundos: float) -> int:
            # Uma ligacao nova so ve o que esta confirmado: e a prova de que a
            # linha nao esta so na transaccao de quem a escreveu.
            visto_pela_shell.append(self.linhas_de(actor))
            self.assertGreater(segundos, 0)
            self.assertLessEqual(segundos, 3600)
            return 7

        codigo = bg.sessao(pedido, self.gravar(), shell)

        self.assertEqual(codigo, 7)
        [na_shell] = visto_pela_shell
        self.assertEqual([linha[3] for linha in na_shell], ["breakglass.open"])
        linhas = self.linhas_de(actor)
        self.assertEqual([linha[3] for linha in linhas], ["breakglass.open", "breakglass.close"])
        for linha in linhas:
            self.assertEqual(linha[5], "staging/kamba-staging-1")
            self.assertEqual(bytes(linha[7]), bg.resumo(pedido))

    def test_sem_a_escrita_a_shell_nunca_abre(self) -> None:
        """A porta recusa o papel (EXECUTE revogado): sai com 69, sem shell e sem linha."""
        actor = self.actor()
        admin = ligacao.ligar("admin")
        self.addCleanup(admin.close)
        c = admin.cursor()
        porta = "platform.breakglass_registar(text, text, text, bytea)"
        c.execute(f"REVOKE EXECUTE ON FUNCTION {porta} FROM kamba_breakglass")
        admin.commit()
        try:
            chamadas: list[float] = []
            codigo = bg.sessao(_pedido(actor), self.gravar(), lambda s: chamadas.append(s) or 0)
        finally:
            c.execute(f"GRANT EXECUTE ON FUNCTION {porta} TO kamba_breakglass")
            admin.commit()
        self.assertEqual(codigo, bg.SAIDA_SEM_REGISTO)
        self.assertEqual(chamadas, [])
        self.assertEqual(self.linhas_de(actor), [])

    def test_pelo_psql_do_contentor_a_linha_esta_antes_da_shell(self) -> None:
        """O transporte do host, o mesmo `docker exec ... psql`, contra a base."""
        actor = self.actor()
        pedido = _pedido(actor)
        vistas: list[list[str]] = []

        def shell(_segundos):
            vistas.append([linha[3] for linha in self.linhas_de(actor)])
            return 0

        self.assertEqual(bg.sessao(pedido, self.gravar_pelo_psql(), shell), 0)
        self.assertEqual(vistas, [["breakglass.open"]])
        linhas = self.linhas_de(actor)
        self.assertEqual([linha[3] for linha in linhas], ["breakglass.open", "breakglass.close"])
        self.assertEqual({bytes(linha[7]) for linha in linhas}, {bg.resumo(pedido)})

    def test_pelo_psql_do_contentor_uma_recusa_da_base_fecha_a_porta(self) -> None:
        """Com o `EXECUTE` revogado, o `psql` tem de sair com erro, e a shell nao abre.

        E o ensaio do `ON_ERROR_STOP` e do `check`: sem um deles, o `psql` sai
        com 0 depois do erro, ou o codigo diferente de 0 nao levanta.
        """
        actor = self.actor()
        admin = ligacao.ligar("admin")
        self.addCleanup(admin.close)
        c = admin.cursor()
        porta = "platform.breakglass_registar(text, text, text, bytea)"
        c.execute(f"REVOKE EXECUTE ON FUNCTION {porta} FROM kamba_breakglass")
        admin.commit()
        try:
            chamadas: list[float] = []
            codigo = bg.sessao(
                _pedido(actor), self.gravar_pelo_psql(), lambda s: chamadas.append(s) or 0
            )
        finally:
            c.execute(f"GRANT EXECUTE ON FUNCTION {porta} TO kamba_breakglass")
            admin.commit()
        self.assertEqual(codigo, bg.SAIDA_SEM_REGISTO)
        self.assertEqual(chamadas, [])
        self.assertEqual(self.linhas_de(actor), [])

    def test_o_comando_do_psql_recusa_argumentos_fora_da_forma(self) -> None:
        for argumentos in (
            ("batch.run", "a", "staging/h", _sha("x")),
            ("breakglass.open", "", "staging/h", _sha("x")),
            ("breakglass.open", "a", "", _sha("x")),
            ("breakglass.open", "a", "staging/h", b"curto"),
            ("breakglass.open", "a" * 257, "staging/h", _sha("x")),
        ):
            with self.subTest(argumentos=argumentos[:3]):
                with self.assertRaises(bg.PedidoInvalido):
                    bg.comando_do_psql("c", "b", *argumentos)
        comando = bg.comando_do_psql("c", "b", "breakglass.open", "a", "staging/h", _sha("x"))
        self.assertIn("ON_ERROR_STOP=1", comando)
        self.assertNotIn("PGPASSWORD=", " ".join(comando))

    def test_sem_base_a_shell_nunca_abre(self) -> None:
        """A base nao responde (porta fechada): sai com 69, sem shell."""
        actor = self.actor()

        def ligar_a_lado_nenhum():
            ambiente = dict(__import__("os").environ, KAMBA_DB_PORT="1")
            return ligacao.ligar("breakglass", ambiente)

        chamadas: list[float] = []
        codigo = bg.sessao(
            _pedido(actor), bg.gravar_por_ligacao(ligar_a_lado_nenhum),
            lambda s: chamadas.append(s) or 0,
        )
        self.assertEqual(codigo, bg.SAIDA_SEM_REGISTO)
        self.assertEqual(chamadas, [])
        self.assertEqual(self.linhas_de(actor), [])

    def test_um_pedido_invalido_nao_escreve_nem_abre(self) -> None:
        agora = datetime.now(timezone.utc)
        casos = {
            "prazo-passado": dict(prazo=agora - timedelta(minutes=1)),
            "prazo-acima-do-tecto": dict(prazo=agora + timedelta(days=7, minutes=5)),
            "prazo-sem-fuso": dict(prazo=datetime.now() + timedelta(hours=1)),
            "sem-razao": dict(razao=""),
            "razao-longa": dict(razao="x" * (bg.RAZAO_MAXIMA + 1)),
            "ambiente-dev": dict(ambiente="dev"),
            "host-com-barra": dict(host="a/b"),
            "sem-sessao": dict(sessao=""),
        }
        for nome, mudar in casos.items():
            with self.subTest(caso=nome):
                actor = self.actor()
                chamadas: list[float] = []
                codigo = bg.sessao(
                    _pedido(actor, **mudar), self.gravar(), lambda s: chamadas.append(s) or 0
                )
                self.assertEqual(codigo, bg.SAIDA_PEDIDO_INVALIDO)
                self.assertEqual(chamadas, [])
                self.assertEqual(self.linhas_de(actor), [])

    def test_o_tecto_de_sete_dias_aceita_o_limite(self) -> None:
        actor = self.actor()
        agora = datetime.now(timezone.utc)
        pedido = _pedido(actor, prazo=agora + timedelta(days=7))
        self.assertEqual(bg.sessao(pedido, self.gravar(), lambda s: 0, agora=lambda: agora), 0)
        self.assertEqual(len(self.linhas_de(actor)), 2)

    def test_uma_shell_que_rebenta_ainda_regista_o_fecho(self) -> None:
        actor = self.actor()

        def shell(_segundos):
            raise RuntimeError("a shell caiu")

        with self.assertRaises(RuntimeError):
            bg.sessao(_pedido(actor), self.gravar(), shell)
        self.assertEqual(
            [linha[3] for linha in self.linhas_de(actor)], ["breakglass.open", "breakglass.close"]
        )

    def test_o_fecho_que_nao_se_escreve_muda_o_codigo(self) -> None:
        actor = self.actor()
        verdadeiro = self.gravar()

        def gravar(accao, *resto):
            if accao == "breakglass.close":
                raise ConnectionError("a base caiu")
            verdadeiro(accao, *resto)

        self.assertEqual(bg.sessao(_pedido(actor), gravar, lambda s: 0), bg.SAIDA_FECHO_SEM_REGISTO)


class TestEncadeamento(_ComCadeiaDePlataforma):
    """O criterio 3, a segunda metade: as linhas sao elos como as outras."""

    def test_as_duas_linhas_ficam_encadeadas_na_cadeia_de_plataforma(self) -> None:
        conexao = ligacao.ligar("admin")
        self.addCleanup(conexao.close)
        antes = self._ler_cabeca(conexao.cursor())
        actor = self.actor()

        self.assertEqual(bg.sessao(_pedido(actor), self.gravar(), lambda s: 0), 0)

        abertura, fecho = self.linhas_de(actor)
        genese = bytes(32)
        self.assertEqual(bytes(abertura[8]), genese if antes is None else antes)
        self.assertEqual(bytes(fecho[8]), bytes(abertura[9]))
        for linha in (abertura, fecho):
            (tenant, actor_type, actor_id, action, entity, entity_id, turn_id,
             payload, prev, guardado, criado_at, _id) = linha
            with self.subTest(accao=action):
                self.assertEqual(
                    row_hash(bytes(prev), criado_at, tenant, actor_type, actor_id, action,
                             entity, entity_id, turn_id, bytes(payload)),
                    bytes(guardado),
                )
        c = conexao.cursor()
        conexao.rollback()
        self.assertEqual(self._ler_cabeca(c), bytes(fecho[9]))

    def test_o_comando_do_kam_074_mostra_as_duas_linhas_de_uma_chave(self) -> None:
        """O criterio 4: `python db/auditoria.py breakglass --actor <impressao>`."""
        import contextlib
        import io

        import auditoria

        actor, outro = self.actor(), self.actor()
        pedido = _pedido(actor)
        self.assertEqual(bg.sessao(pedido, self.gravar(), lambda s: 0), 0)
        self.assertEqual(bg.sessao(_pedido(outro), self.gravar(), lambda s: 0), 0)

        lote = ligacao.ligar("batch")
        self.addCleanup(lote.close)
        linhas = auditoria.sessoes_de_breakglass(lote.cursor(), actor)
        self.assertEqual(
            [(accao, entidade, resumo) for _id, _quando, accao, entidade, resumo in linhas],
            [
                ("breakglass.open", "staging/kamba-staging-1", bg.resumo(pedido).hex()),
                ("breakglass.close", "staging/kamba-staging-1", bg.resumo(pedido).hex()),
            ],
        )
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.assertEqual(auditoria.main(["breakglass", "--actor", actor]), 0)
        impressas = saida.getvalue().splitlines()
        self.assertEqual(len(impressas), 2)
        self.assertIn("breakglass.open", impressas[0])
        self.assertIn("breakglass.close", impressas[1])


class TestAsPecasDoPortao(unittest.TestCase):
    """As funcoes puras do portao, sem base."""

    def test_a_impressao_e_a_do_ssh_keygen(self) -> None:
        self.assertEqual(
            bg.impressao_digital(f"publickey {CHAVE_DE_ENSAIO}\n"), IMPRESSAO_DE_ENSAIO
        )

    def test_sem_chave_publica_nao_ha_actor(self) -> None:
        for info in ("", "password\n", "keyboard-interactive\n", "publickey ssh-ed25519 %%%\n"):
            with self.subTest(info=info):
                with self.assertRaises(bg.PedidoInvalido):
                    bg.impressao_digital(info)

    def test_o_comando_leva_prazo_e_razao(self) -> None:
        prazo, razao = bg.ler_comando("2026-12-01T18:00:00+01:00 revisao independente, area 6")
        self.assertEqual(prazo, datetime(2026, 12, 1, 17, 0, tzinfo=timezone.utc))
        self.assertEqual(razao, "revisao independente, area 6")
        for comando in ("", "2026-12-01T18:00:00+01:00", "amanha uma razao"):
            with self.subTest(comando=comando):
                with self.assertRaises(bg.PedidoInvalido):
                    bg.ler_comando(comando)

    def test_o_resumo_muda_com_cada_campo(self) -> None:
        base = _pedido("SHA256:x", prazo=datetime(2026, 12, 1, tzinfo=timezone.utc))
        vistos = {bg.resumo(base)}
        for mudar in (
            dict(sessao=uuid.uuid4().hex),
            dict(actor="SHA256:y"), dict(ambiente="prod"), dict(host="outro"),
            dict(razao="outra"), dict(prazo=datetime(2026, 12, 2, tzinfo=timezone.utc)),
        ):
            with self.subTest(mudar=mudar):
                resumo = bg.resumo(_pedido(**{**base.__dict__, **mudar}))
                self.assertNotIn(resumo, vistos)
                vistos.add(resumo)
        self.assertEqual(len(bg.resumo(base)), 32)

    def test_o_resumo_nao_depende_do_fuso_do_prazo(self) -> None:
        utc = datetime(2026, 12, 1, 17, 0, tzinfo=timezone.utc)
        luanda = utc.astimezone(timezone(timedelta(hours=1)))
        sessao = uuid.uuid4().hex
        self.assertEqual(
            bg.resumo(_pedido("SHA256:x", prazo=utc, sessao=sessao)),
            bg.resumo(_pedido("SHA256:x", prazo=luanda, sessao=sessao)),
        )

    def test_a_primeira_linha_isola_o_python(self) -> None:
        """O `-I`: sem ele, o Python le os `site-packages` da casa da conta."""
        self.assertEqual(
            PORTAO.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/python3 -I"
        )


class TestDowngradeDoBreakglass(unittest.TestCase):
    """O `downgrade` recusa com uma linha `breakglass.close`, e sem ela desce e volta."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _admin(self):
        conexao = ligacao.ligar("admin")
        self.addCleanup(conexao.close)
        return conexao

    def _estado(self) -> tuple[bool, int, int]:
        """(o dominio tem o fecho, quantas portas, quantas politicas do dono)."""
        c = self._admin().cursor()
        c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'")
        dominio = "'breakglass.close'" in c.fetchone()[0]
        c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'breakglass_registar'")
        portas = c.fetchone()[0]
        c.execute("SELECT count(*) FROM pg_policies WHERE policyname = 'breakglass_registo'")
        return dominio, portas, c.fetchone()[0]

    def test_com_um_fecho_recusa_e_sem_ele_desce_e_volta(self) -> None:
        revisao, abaixo = _revisao()
        conexao = self._admin()
        c = conexao.cursor()
        c.execute(
            "SELECT last_hash FROM platform.audit_heads WHERE chave = %s::uuid", (CHAVE_DA_PLATAFORMA,)
        )
        linha = c.fetchone()
        cabeca = None if linha is None else bytes(linha[0])
        conexao.rollback()
        actor = _actor()
        bg.gravar_por_ligacao(lambda: ligacao.ligar("breakglass"))(
            "breakglass.close", actor, "staging/h", _sha("descida")
        )
        try:
            resultado = alembic("downgrade", abaixo)
            self.assertNotEqual(resultado.returncode, 0, "o downgrade devia recusar")
            self.assertIn(f"downgrade da {revisao} recusado", resultado.stderr)
            self.assertEqual(self._estado(), (True, 1, 1), "a revisao ficou, com a linha")
        finally:
            if not em_head():
                alembic_ok("upgrade", "head")
            _desligar(c)
            c.execute("DELETE FROM platform.audit_log WHERE actor_id = %s", (actor,))
            _religar(c)
            if cabeca is None:
                c.execute("DELETE FROM platform.audit_heads WHERE chave = %s::uuid", (CHAVE_DA_PLATAFORMA,))
            else:
                c.execute(
                    "UPDATE platform.audit_heads SET last_hash = %s WHERE chave = %s::uuid",
                    (cabeca, CHAVE_DA_PLATAFORMA),
                )
            conexao.commit()
        alembic_ok("downgrade", abaixo)
        try:
            self.assertEqual(self._estado(), (False, 0, 0))
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._estado(), (True, 1, 1))


if __name__ == "__main__":
    unittest.main()
