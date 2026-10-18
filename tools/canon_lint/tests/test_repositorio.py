"""O gate ponta a ponta: o repositorio real passa, e cada mutacao deixa-o vermelho.

As mutacoes fazem-se numa **copia** (`ComCopia`). Cada uma altera uma coisa so,
e o teste exige o achado **dessa** coisa — nao apenas «saiu 1»: um gate que
fica vermelho pela razao errada passa um teste que so olha para o codigo de
saida.
"""

from __future__ import annotations

import datetime
import time
import unittest

from canon_lint import cli
from canon_lint.achados import FORA, ILEGIVEL, REGRA, SENTINELA, VARIANTE
from canon_lint.dicionario import SENTINELAS_MINIMAS, ConfiguracaoInvalida
from dict_export.cli import main as dict_export

from .base import ROOT, ComCopia
from .test_revisao import AUXILIAR

MIGRACAO = "db/migrations/versions/0001_schema_platform.py"
DOC03 = "docs/tecnica/03_Core_Comercio_Medusa.md"
DOC04 = "docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md"
DOC06 = "docs/tecnica/06_Dados_Eventos_Analytics.md"
MANIFESTO = "tools/canon_lint/tests/fixtures/manifesto.yaml"
#: O dia em que os testes «correm». E **o dia de hoje**, de proposito: estes
#: testes correm o lint contra o repositorio real, e o lint recusa uma extensao
#: de `canon/extensoes.yaml` datada **depois** deste dia. Com um dia fixo no
#: codigo, o primeiro ticket a datar uma extensao no dia seguinte punha 54
#: testes vermelhos sem nada de errado no repositorio — ja aconteceu duas vezes
#: (subiu de 11 para 12 de Outubro com o KAM-008). As *fixtures* inventadas
#: tem datas no passado e passam com qualquer dia de hoje.
HOJE = datetime.date.today()


class TestRepositorioReal(unittest.TestCase):
    def test_o_repositorio_passa(self) -> None:
        achados, _ = cli.verificar(ROOT, hoje=HOJE)
        self.assertEqual([str(a) for a in achados], [])

    def test_e_passa_tendo_lido_o_ddl_real_e_nao_por_nao_o_ter_visto(self) -> None:
        """38 colunas em 3 tabelas e o que a revisao 0001 tem (ANALISE-03 §5)."""
        _, estatisticas = cli.verificar(ROOT, hoje=HOJE)
        contagem = estatisticas["ddl"]
        self.assertGreaterEqual(estatisticas["ficheiros"]["migracoes"], 1)
        self.assertGreaterEqual(contagem.tabelas, 3)
        self.assertGreaterEqual(contagem.colunas, 38)
        self.assertGreaterEqual(contagem.valores, 20)
        self.assertGreaterEqual(estatisticas["ficheiros"]["documentos"], 12)

    def test_o_canario_esta_verde(self) -> None:
        falhas, numeros = cli.canario(ROOT)
        self.assertEqual(falhas, [])
        self.assertEqual((numeros["negativas"], numeros["positivas"], numeros["sem_forma"]), (10, 10, 2))
        self.assertGreaterEqual(numeros["por_superficie"]["eventos"], 1)
        self.assertGreaterEqual(numeros["por_superficie"]["registo"], 1)

    def test_o_lint_corre_dentro_do_tempo_do_criterio(self) -> None:
        """«O lint corre em <= 60 s» (*proposta*). A margem e de duas ordens de grandeza."""
        inicio = time.monotonic()
        cli.verificar(ROOT, hoje=HOJE)
        cli.canario(ROOT)
        self.assertLess(time.monotonic() - inicio, 60)

    def test_linha_de_comandos(self) -> None:
        self.assertEqual(cli.main(["--root", str(ROOT), "canario"]), 0)


class TestCanario(ComCopia):
    """ANALISE-05 B1, M24, M25: o canario esvaziava-se com o gate e os testes verdes."""

    def falhas(self) -> list[str]:
        falhas, _ = cli.canario(self.raiz)
        codigo = cli.main(["--root", str(self.raiz), "canario"])
        self.assertEqual(codigo, 1 if falhas else 0)
        return falhas

    def test_a_copia_sem_mutacao_passa(self) -> None:
        self.assertEqual(self.falhas(), [])

    def test_manifesto_sem_casos(self) -> None:
        texto = (self.raiz / MANIFESTO).read_text(encoding="utf-8")
        inicio, fim = texto.index("casos:\n"), texto.index("# Divergencias do KAM-111 que NAO")
        self.escrever(MANIFESTO, texto[:inicio] + "casos: []\n\n" + texto[fim:])
        falhas = self.falhas()
        self.assertTrue(any("exige exactamente" in f for f in falhas), falhas)
        self.assertEqual(sum("precisa de pelo menos" in f for f in falhas), 3, "uma por superficie")

    def test_caso_movido_para_sem_forma_de_nome(self) -> None:
        texto = (self.raiz / MANIFESTO).read_text(encoding="utf-8")
        inicio, fim = texto.index("  - divergencia: D-12\n"), texto.index("# Divergencias do KAM-111 que NAO")
        sem = texto[:inicio] + texto[fim:]
        self.escrever(
            MANIFESTO,
            sem + "  - divergencia: D-12\n    razao: >-\n      Movida para aqui sem alterar o codigo, a ver se o canario deixa passar a falta dela.\n",
        )
        falhas = self.falhas()
        self.assertTrue(any("exige exactamente" in f for f in falhas), falhas)
        self.assertTrue(any("so admite" in f for f in falhas), falhas)

    def test_caso_duplicado_nao_compensa_um_em_falta(self) -> None:
        self.trocar(MANIFESTO, "  - divergencia: D-12\n    superficie: eventos", "  - divergencia: D-03\n    superficie: eventos")
        self.assertTrue(any("exige exactamente" in f for f in self.falhas()))

    def test_espera_trivial(self) -> None:
        for curto in ("`", "dicionário §3", "`llm_calls`"):
            with self.subTest(espera=curto):
                original = (self.raiz / MANIFESTO).read_bytes()
                self.trocar(MANIFESTO, 'espera: "`llm_calls` → `llm_call_log`, dicionário §3.6"', f'espera: "{curto}"')
                falhas = self.falhas()
                (self.raiz / MANIFESTO).write_bytes(original)
                self.assertTrue(any("nao tem a forma" in f for f in falhas), falhas)
                self.assertTrue(all(f.startswith("D-10") for f in falhas), falhas)

    def test_espera_que_nao_e_a_mensagem(self) -> None:
        self.trocar(MANIFESTO, "`llm_calls` → `llm_call_log`, dicionário §3.6", "`llm_calls` → `llm_call_log`, dicionário §3.5")
        falhas = self.falhas()
        self.assertEqual(len(falhas), 1)
        self.assertIn("D-10", falhas[0])

    def test_negativa_que_passou_a_estar_certa(self) -> None:
        """M24: se o lint deixar de apanhar a negativa, o canario tem de falhar."""
        self.trocar("tools/canon_lint/tests/fixtures/negativas/D-10_llm_calls.py", "platform.llm_calls", "platform.llm_call_log")
        falhas = self.falhas()
        self.assertEqual(len(falhas), 1)
        self.assertIn("nenhum achado", falhas[0])

    def test_negativa_com_um_segundo_achado(self) -> None:
        """Um achado a mais e uma razao diferente da declarada."""
        self.trocar("tools/canon_lint/tests/fixtures/negativas/D-10_llm_calls.py", "  tenant_id  uuid NOT NULL,", "  tenant_id  uuid NOT NULL,\n  cor_xpto   text,")
        falhas = self.falhas()
        self.assertEqual(len(falhas), 1)
        self.assertIn("deu 2", falhas[0])

    def test_positiva_que_deixou_de_passar(self) -> None:
        """M25."""
        self.trocar("tools/canon_lint/tests/fixtures/positivas/D-10_llm_call_log.py", "  tenant_id  uuid NOT NULL,", "  tenant_id  uuid NOT NULL,\n  valor_kz   integer,")
        falhas = self.falhas()
        self.assertEqual(len(falhas), 1)
        self.assertIn("devia passar", falhas[0])


class TestMutacoes(ComCopia):
    def achados(self, hoje: datetime.date = HOJE):
        return cli.verificar(self.raiz, hoje=hoje)[0]

    def unico(self, classe: str, fragmento: str, ficheiro: str | None = None) -> None:
        achados = self.achados()
        self.assertEqual(
            [a.classe for a in achados], [classe], "\n".join(str(a) for a in achados) or "sem achados"
        )
        self.assertIn(fragmento, achados[0].mensagem)
        if ficheiro:
            self.assertEqual(achados[0].ficheiro, ficheiro)

    def com_divida(self, ficheiro: str, variante: str, ocorrencias: int,
                   expira_em: str = "2026-11-16") -> None:
        """Declara uma divida na copia, para a testar sem depender do repositorio.

        O `ci/canon-allow.yaml` real tem hoje `dividas: []` — e isso e o
        **criterio de aceitacao do KAM-139**, que as pagou todas. As quatro
        baterias que provam o mecanismo das dividas (contagem exacta para
        cima e para baixo, excepcao que ficou orfa, prazo vencido) dependiam
        de o repositorio ter divida por pagar: eram testes cujo sujeito
        desaparecia no dia em que o repositorio ficasse limpo, e a conta e
        sempre a mesma — ou se desligava o teste, ou se deixava a divida.

        Passam a trazer a sua. O mecanismo e o mesmo; o sujeito e nosso.
        """
        texto = (self.raiz / "ci/canon-allow.yaml").read_text(encoding="utf-8")
        entrada = (
            "dividas:\n"
            f"  - ficheiro: {ficheiro}\n"
            f"    variante: {variante}\n"
            f"    ocorrencias: {ocorrencias}\n"
            "    origem: KAM-139\n"
            "    criado_em: 2026-10-17\n"
            f"    expira_em: {expira_em}\n"
            '    razao: "Divida construida pela bateria de testes para exercitar o mecanismo '
            'das dividas com prazo, que o repositorio real ja nao tem por estarem todas pagas."\n'
        )
        self.escrever("ci/canon-allow.yaml", texto.replace("dividas: []\n", entrada))

    def test_a_copia_sem_mutacao_passa(self) -> None:
        """A base de todas as outras: se a copia ja falhasse, tudo o resto era vacuo."""
        self.assertEqual([str(a) for a in self.achados()], [])
        self.assertEqual(cli.main(["--root", str(self.raiz), "check"]), 0)

    def test_a_lista_de_dividas_do_repositorio_esta_vazia(self) -> None:
        """O criterio de aceitacao do KAM-139, verificado onde se ve.

        Nao e so «o gate passa»: passar com dividas declaradas tambem passa.
        O que se exige e que nenhum documento tecnico use hoje um nome que o
        dicionario substitui, e a forma de o dizer e a lista estar vazia.
        """
        import kamba_yaml

        documento = kamba_yaml.load_file(ROOT / "ci/canon-allow.yaml")
        self.assertEqual(documento.get("dividas") or [], [])

    def test_o_dominio_do_registo_nao_se_aplica_a_coluna_e_o_da_coluna_aplica_se(self) -> None:
        """A proteccao que a `dominios_so_no_registo` dava, agora sem ela.

        A lista de excepcoes ficou vazia (KAM-141, linhas 6 e 9) e a
        distincao passou a vir do dicionario. Ficou provado que o exportador
        marca o campo, e **nao** que o gate se comporta como antes — apanhado
        pela revisao adversarial (achado m10.2). E o comportamento que
        importa: `id uuid PRIMARY KEY` numa migracao nao pode ter de ser uma
        vertical, e um valor fora de um dominio **nao qualificado** — que e a
        classe que o `so_no_registo` pode desarmar — tem de falhar.
        """
        tabela = "\n".join(
            (
                "    op.execute(",
                '        """',
                "        CREATE TABLE platform.ensaio_do_registo (",
                "          id uuid PRIMARY KEY,",
                "          tenant_id uuid NOT NULL,",
                "          modulo text NOT NULL,",
                "          preco_tipo text NOT NULL CHECK (preco_tipo IN ({valores}))",
                "        )",
                '        """',
                "    )",
                "",
            )
        )
        base = (self.raiz / MIGRACAO).read_text(encoding="utf-8")
        marca = "def upgrade() -> None:\n"
        self.assertIn(marca, base)

        self.escrever(MIGRACAO, base.replace(
            marca, marca + tabela.format(valores="'fixo', 'a_partir_de'"), 1))
        dominios = [a for a in self.achados() if "dominio" in a.mensagem or a.classe == REGRA]
        self.assertEqual(
            [a for a in dominios if "id" in a.mensagem or "modulo" in a.mensagem], [],
            "o `id` e o `modulo` voltaram a ser tratados como dominios de coluna",
        )

        self.escrever(MIGRACAO, base.replace(
            marca, marca + tabela.format(valores="'fixo', 'banana'"), 1))
        achados = [a for a in self.achados() if "banana" in a.mensagem]
        self.assertEqual(
            len(achados), 1, "um valor fora do dominio de `preco_tipo` tem de falhar"
        )
        self.assertEqual(achados[0].classe, REGRA)

    # --- migracoes ---------------------------------------------------------------
    def test_valor_kz_na_migracao(self) -> None:
        self.trocar(MIGRACAO, "          zona                     text,", "          zona                     text,\n          valor_kz                 integer,")
        self.unico(VARIANTE, "`valor_kz` → `valor_minor + currency ∈ {AOA}`, dicionário §3.4", MIGRACAO)
        self.assertEqual(cli.main(["--root", str(self.raiz), "check"]), 1)

    def test_coluna_canonica_renomeada_para_nome_inventado(self) -> None:
        self.trocar(MIGRACAO, "          verificado_at            timestamptz,", "          verificado_em            timestamptz,")
        self.unico(FORA, "`tenants.verificado_em`", MIGRACAO)

    def test_estado_restrito_retirado_do_check(self) -> None:
        self.trocar(MIGRACAO, "('onboarding','ativo','restrito','suspenso','encerrado')", "('onboarding','ativo','suspenso','encerrado')")
        self.unico(REGRA, "falta: restrito", MIGRACAO)

    def test_estado_a_mais_no_canal(self) -> None:
        self.trocar(MIGRACAO, "'desligado','suspenso','encerrado'))", "'desligado','suspenso','encerrado','pausado'))")
        self.unico(REGRA, "a mais: pausado", MIGRACAO)

    def test_check_do_tipo_retirado(self) -> None:
        """M1 (s25): a coluna continua la, o dominio deixa de estar imposto."""
        self.trocar(
            MIGRACAO,
            "                                   CONSTRAINT tenants_tipo_ck\n"
            "                                   CHECK (tipo IN ('pme','courier','reseller','agent','platform')),",
            ",",
        )
        self.unico(REGRA, "`tenants.tipo` sem CHECK fechado", MIGRACAO)

    def test_kamba_ops_num_grant(self) -> None:
        self.trocar(MIGRACAO, "TO kamba_app, kamba_batch", "TO kamba_app, kamba_ops")
        self.unico(VARIANTE, "`kamba_ops` →", MIGRACAO)

    def test_variante_num_comentario_de_coluna(self) -> None:
        """M3: uma cadeia tambem e texto que alguem vai ler como contrato."""
        self.trocar(MIGRACAO, "'Cifrado em aplicacao. Nunca em claro", "'Substitui msisdn_hash. Nunca em claro")
        self.unico(VARIANTE, "`msisdn_hash` →", MIGRACAO)

    def test_tabela_renomeada_para_variante(self) -> None:
        self.trocar(MIGRACAO, "CREATE TABLE platform.entitlements (", "CREATE TABLE platform.consents (")
        self.assertIn(VARIANTE, [a.classe for a in self.achados()])

    def test_uma_extensao_datada_hoje_nao_e_futura(self) -> None:
        """A razao de `HOJE` ser o dia de hoje, e nao um dia escrito no codigo.

        Com um dia fixo, o primeiro ticket a datar uma extensao no dia seguinte
        punha todo este modulo vermelho — e a causa (uma data no codigo de
        teste) nao se le em nenhuma mensagem de erro do lint.
        """
        hoje = datetime.date.today().isoformat()
        base = "  - nome: tenants.nif\n    tipo: coluna\n    ticket: KAM-003\n    data: "
        self.trocar("canon/extensoes.yaml", base + "2026-10-11\n", base + hoje + "\n")
        self.assertEqual([str(a) for a in self.achados()], [])

    def test_extensao_retirada(self) -> None:
        self.trocar("canon/extensoes.yaml", "  - nome: tenants.nif\n    tipo: coluna\n    ticket: KAM-003\n    data: 2026-10-11\n", "")
        self.unico(FORA, "`tenants.nif`", MIGRACAO)

    def test_extensao_que_nada_usa(self) -> None:
        self.trocar("canon/extensoes.yaml", "extensoes:\n", "extensoes:\n  - nome: tenants.cor_favorita\n    tipo: coluna\n    ticket: KAM-003\n    data: 2026-10-11\n")
        self.unico(REGRA, "`tenants.cor_favorita`", "canon/extensoes.yaml")

    def test_migracao_com_a_api_do_alembic(self) -> None:
        self.escrever("db/migrations/versions/0009_x.py", "from alembic import op\nimport sqlalchemy as sa\n\ndef upgrade():\n    op.add_column('tenants', None)\n")
        self.unico(ILEGIVEL, "op.add_column", "db/migrations/versions/0009_x.py")

    def test_revisao_que_chama_o_auxiliar_de_rls(self) -> None:
        """A integracao com o KAM-004: o `db/rls.py` **real** e lido por dentro, nao dispensado."""
        base = cli.verificar(self.raiz, hoje=HOJE)[1]["ddl"].instrucoes
        nomes = len(list((self.raiz / "db/migrations/versions").glob("*.py")))
        revisao ="from alembic import op\n\nimport rls\n\n\ndef upgrade():\n    rls.enable_tenant_rls({})\n\n\ndef downgrade():\n    rls.disable_tenant_rls({})\n"
        self.escrever("db/migrations/versions/0009_rls.py", revisao.format('"tenants", coluna="id"', '"tenants"'))
        achados, estatisticas = cli.verificar(self.raiz, hoje=HOJE)
        self.assertEqual([str(a) for a in achados], [])
        self.assertEqual(estatisticas["ficheiros"]["migracoes"], nomes + 1)
        # ENABLE + FORCE + CREATE POLICY, e DROP POLICY + NO FORCE + DISABLE
        self.assertEqual(estatisticas["ddl"].instrucoes, base + 6, "as seis instrucoes do auxiliar foram lidas")

        self.escrever("db/migrations/versions/0009_rls.py", revisao.format('"consent_log"', '"consent_log"'))
        achados, _ = cli.verificar(self.raiz, hoje=HOJE)
        self.assertEqual({a.classe for a in achados}, {VARIANTE})
        self.assertIn("via rls.enable_tenant_rls", achados[0].mensagem)
        self.assertEqual(achados[0].linha, 7)

    def test_auxiliar_que_deixa_de_se_seguir(self) -> None:
        """Se o auxiliar real mudar para uma forma que o lint nao segue, as revisoes
        reais que o chamam — a 0002, a 0003 (KAM-008), a 0004 (KAM-005), a 0005
        (KAM-006) e a 0006 (KAM-012) — passam a falhar, em vez de ficarem por ler."""
        self.assertEqual(self.achados(), [])
        self.escrever("db/rls.py", AUXILIAR.replace('alvo = f"{schema}.{tabela}"', "alvo = montar(schema, tabela)"))
        achados = self.achados()
        self.assertGreaterEqual(len(achados), 6)
        self.assertEqual({a.classe for a in achados}, {ILEGIVEL})
        self.assertEqual(
            {a.ficheiro for a in achados},
            {
                "db/migrations/versions/0002_rls_por_tenant.py",
                "db/migrations/versions/0003_identidade_de_contacto.py",
                "db/migrations/versions/0004_outbox_e_eventos.py",
                "db/migrations/versions/0005_consumo_dlq.py",
                "db/migrations/versions/0006_audit_log.py",
            },
        )
        # Todo o achado diz **por onde** chegou. Quatro revisoes chamam o auxiliar
        # directamente; a 0006 chama-o por um embrulho local, e o lint segue-o e
        # atribui-lhe a origem. Exigir `via rls.` em todos prendia a forma do sitio
        # da chamada, que nao e o que este teste afirma.
        self.assertTrue(all("(via " in a.mensagem for a in achados))
        directos = {a.ficheiro for a in achados if "via rls." in a.mensagem}
        self.assertEqual(len(directos), 4)
        self.assertEqual(
            {a.mensagem.split("(via ")[1].split(")")[0]
             for a in achados if a.ficheiro.endswith("0006_audit_log.py")},
            {"_rls"},
        )

    def test_le_a_revisao_0002_real_pelo_auxiliar_real(self) -> None:
        """O que o gate faz hoje sobre `main`: 28 instrucoes da 0002, 18 vindas de `db/rls.py`."""
        from canon_lint import revisao as leitor
        from canon_lint.dicionario import Saber

        saber = Saber.ler(self.raiz, HOJE)
        fonte = (self.raiz / "db/migrations/versions/0002_rls_por_tenant.py").read_text(encoding="utf-8")
        extraccao = leitor.extrair(fonte, saber.politica.auxiliares, saber.carregar)
        self.assertEqual(extraccao.ilegiveis, [])
        self.assertEqual(len(extraccao.blocos), 28)
        self.assertEqual(sum(1 for b in extraccao.blocos if b.origem.startswith("via rls.")), 18)
        self.assertIn(
            "CREATE POLICY tenant_iso ON platform.tenants USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
            [b.texto for b in extraccao.blocos],
        )

    # --- sentinelas ------------------------------------------------------------------
    def test_ficheiros_com_forma_de_superficie_fora_dela(self) -> None:
        """M6: todos estes davam «conforme» com uma variante la dentro."""
        casos = {
            "services/com/migrations/versions/0001_x.py": "migracoes",
            "migrations/0002_idx_schema.sql": "migracoes",  # o caminho que o EPIC-06 manda usar
            "migrations/versions/0001_x.py": "migracoes",
            "services/com/alembic/versions/0001_x.py": "migracoes",
            "services/com/src/migrations/Migration20261011.ts": "migracoes",  # Medusa
            "db/0002_x.sql": "migracoes",
            "db/seed/schema.sql": "migracoes",
            "db/migrations/versions/0002_x.PY": "migracoes",
            "db/migrations/novo_env.py": "migracoes",
            "packages/contracts/schemas/eventos/order.created.v1.schema.json": "eventos",
            "contratos/events/payment/v1.json": "eventos",
            "contratos/eventos/payment/v1.SCHEMA.JSON": "eventos",
            "contratos/eventos/payment/v1.schema.yaml": "eventos",
            "registry/x.YAML": "registo",
            "registry/x.yml": "registo",
            "registry/x.json": "registo",
            "services/agr/registry/servicos.yaml": "registo",
            "registo/servicos.yaml": "registo",
            "docs/tecnica/novo.MD": "documentos",
        }
        for caminho, superficie in casos.items():
            with self.subTest(caminho=caminho):
                self.escrever(caminho, "valor_kz consent_log\n")
                achados = self.achados()
                self.assertEqual([a.classe for a in achados], [SENTINELA], [str(a) for a in achados])
                self.assertEqual(achados[0].ficheiro, caminho)
                self.assertIn(f"`{superficie}`", achados[0].mensagem)
                (self.raiz / caminho).unlink()

    def test_as_sentinelas_minimas_estao_no_codigo(self) -> None:
        """M9: `sentinelas: []` na politica desligava a proteccao sem tocar em codigo."""
        self.assertGreaterEqual(len(SENTINELAS_MINIMAS), 10)
        texto = (self.raiz / "ci/canon-lint.yaml").read_text(encoding="utf-8")
        inicio, fim = texto.index("sentinelas:\n"), texto.index("fora_de_ambito:\n")
        self.escrever("ci/canon-lint.yaml", texto[:inicio] + "sentinelas: []\n\n" + texto[fim:])
        with self.assertRaisesRegex(ConfiguracaoInvalida, "sentinelas obrigatorias"):
            self.achados()
        self.escrever("ci/canon-lint.yaml", texto.replace('  - padrao: "*.sql"\n    superficie: migracoes\n', ""))
        with self.assertRaisesRegex(ConfiguracaoInvalida, r"\*\.sql"):
            self.achados()

    # --- eventos e registo, com ficheiros na superficie -------------------------
    def test_schema_de_evento_real_e_lido(self) -> None:
        self.escrever(
            "contratos/eventos/payment/confirmed/v1.schema.json",
            '{"properties": {"tipo": {"const": "payment.confirmed"}, "versao": {"const": 1}, '
            '"payload": {"properties": {"valor_kz": {"type": "integer"}}}}}',
        )
        self.unico(VARIANTE, "`valor_kz` →", "contratos/eventos/payment/confirmed/v1.schema.json")
        _, estatisticas = cli.verificar(self.raiz, hoje=HOJE)
        self.assertEqual(estatisticas["ficheiros"]["eventos"], 1)

    def test_schema_partilhado_tem_de_estar_declarado(self) -> None:
        self.escrever("contratos/eventos/envelope.schema.json", '{"properties": {"id": {}, "tipo": {}, "versao": {}}}')
        self.unico(REGRA, "eventos_partilhados", "contratos/eventos/envelope.schema.json")
        self.trocar("ci/canon-lint.yaml", "eventos_partilhados: []\n", 'eventos_partilhados:\n  - "contratos/eventos/envelope.schema.json"\n')
        self.assertEqual([str(a) for a in self.achados()], [])

    def test_ficheiro_do_registo_real_e_lido(self) -> None:
        self.escrever(
            "registry/vendedor.yaml",
            "id: vendedor\nentitlements:\n  modulo: vendedor\n  limites: [msgs_ai_mes, valor_max_pedido_kz]\n",
        )
        self.unico(VARIANTE, "`valor_max_pedido_kz` →", "registry/vendedor.yaml")

    # --- documentos --------------------------------------------------------------
    def test_variante_reposta_num_documento_limpo(self) -> None:
        self.trocar("docs/tecnica/09_Topologia_Operacao_Escala.md", "tabela `llm_call_log` sem conteúdo;", "tabela `llm_calls` sem conteúdo;")
        self.unico(VARIANTE, "`llm_calls` → `llm_call_log`, dicionário §3.6", "docs/tecnica/09_Topologia_Operacao_Escala.md")

    def test_uma_divida_declarada_com_a_contagem_certa_passa(self) -> None:
        """A base das tres que seguem: sem isto, todas passariam por acidente."""
        self.trocar(DOC03, "kamba_batch (BYPASSRLS, auditado)", "kamba_ops (BYPASSRLS, auditado)")
        self.com_divida(DOC03, "kamba_ops", 1)
        self.assertEqual([str(a) for a in self.achados()], [])

    def test_mais_uma_ocorrencia_de_uma_divida_declarada(self) -> None:
        """A excepcao e por contagem: a segunda `kamba_ops` nao entra atras da primeira."""
        self.trocar(DOC03, "kamba_batch (BYPASSRLS, auditado)",
                    "kamba_ops (BYPASSRLS, auditado), e kamba_ops outra vez")
        self.com_divida(DOC03, "kamba_ops", 1)
        self.unico(VARIANTE, "2 ocorrencia(s)", DOC03)

    def test_menos_ocorrencias_do_que_as_declaradas(self) -> None:
        """M11: corrigir uma das duas e deixar a excepcao a dizer duas tambem falha."""
        self.trocar(DOC03, "kamba_batch (BYPASSRLS, auditado)", "kamba_ops (BYPASSRLS, auditado)")
        self.com_divida(DOC03, "kamba_ops", 2)
        achados = self.achados()
        self.assertEqual([a.classe for a in achados], [VARIANTE], "\n".join(str(a) for a in achados))
        self.assertIn("1 ocorrencia(s)", achados[0].mensagem)
        self.assertIn("declara 2", achados[0].mensagem)

    def test_divida_corrigida_obriga_a_retirar_a_excepcao(self) -> None:
        """Zero ocorrencias com a excepcao de pe falha: a lista nao apodrece."""
        self.com_divida(DOC03, "kamba_ops", 1)
        self.unico(REGRA, "retire a excepcao", DOC03)

    def test_divida_vencida_falha(self) -> None:
        self.trocar(DOC03, "kamba_batch (BYPASSRLS, auditado)", "kamba_ops (BYPASSRLS, auditado)")
        self.com_divida(DOC03, "kamba_ops", 1, expira_em="2026-11-16")
        self.assertEqual(self.achados(datetime.date(2026, 11, 16)), [])
        vencidas = self.achados(datetime.date(2026, 11, 17))
        self.assertEqual({a.classe for a in vencidas}, {REGRA})
        self.assertIn("venceu", vencidas[0].mensagem)

    def test_citacao_historica_trocada_por_uso_vivo(self) -> None:
        """M9: a contagem prendia o numero, nao a natureza."""
        self.trocar(DOC04, "| `valor_kz int`, sem moeda | Perde cêntimos;", "| `valor_kz int` e a coluna do ledger | Perde cêntimos;")
        achados = self.achados()
        self.assertEqual([a.classe for a in achados], [VARIANTE])
        self.assertIn("nenhuma das ancoras", achados[0].mensagem)

    def test_valor_entre_plicas_num_documento(self) -> None:
        self.trocar(DOC06, "'a_partir_de' excluído", "'a_partir_de' e 'exato' excluídos")
        achados = self.achados()
        self.assertEqual([a.classe for a in achados], [VARIANTE])
        self.assertIn("`exato` →", achados[0].mensagem)

    # --- dicionario --------------------------------------------------------------
    def test_nome_que_passa_a_variante_no_dicionario_deixa_o_ddl_vermelho(self) -> None:
        """O dicionario manda: mudar o Markdown muda o que o gate recusa."""
        self.trocar(
            "specs/02_Dicionario_de_Dados_Canonico.md",
            "| Registo de chamadas LLM | `llm_call_log` | `llm_calls` |",
            "| Registo de chamadas LLM | `llm_call_log` | `llm_calls`, `fuso_horario` |",
        )
        self.assertEqual(dict_export(["--root", str(self.raiz), "--check"]), 1, "o YAML ficou atras do Markdown")
        self.assertEqual(dict_export(["--root", str(self.raiz)]), 0)
        with self.assertRaisesRegex(ConfiguracaoInvalida, "fuso_horario"):
            self.achados()  # a extensao `tenants.fuso_horario` passou a declarar uma variante


class TestConfiguracao(ComCopia):
    """Um ficheiro de politica mal formado e erro (saida 2), nunca «conforme»."""

    def erro(self, padrao: str) -> None:
        with self.assertRaisesRegex(ConfiguracaoInvalida, padrao):
            cli.verificar(self.raiz, hoje=HOJE)

    def com(self, relativo: str, velho: str, novo: str, padrao: str) -> None:
        caminho = self.raiz / relativo
        original = caminho.read_bytes()
        self.trocar(relativo, velho, novo)
        self.erro(padrao)
        caminho.write_bytes(original)

    def test_a_linha_de_comandos_sai_com_2(self) -> None:
        (self.raiz / "canon/dicionario.yaml").unlink()
        self.erro("dict_export")
        self.assertEqual(cli.main(["--root", str(self.raiz), "check"]), 2)
        self.assertEqual(cli.main(["--root", str(self.raiz), "canario"]), 2)

    def test_politica(self) -> None:
        politica = "ci/canon-lint.yaml"
        for velho, novo, padrao in (
            ("version: 1\n", "version: 1\nmodo: brando\n", "modo"),
            ('  migracoes:\n    - "db/migrations/versions/*.py"\n', "  migracoes: []\n", "migracoes"),
            ("      - provider\n      - referencia\n", "      - provider\n      - account_id\n", r"UNIQUE\(provider,account_id\)"),
            ('conceito: "Estado do tenant"', 'conceito: "Estado do inquilino"', "Estado do inquilino"),
            ('identificador: "confirm:{hold_id}"', 'identificador: "confirm:{slot_id}"', "slot_id"),
            # A `dominios_so_no_registo` esta hoje vazia (KAM-141, linhas 6 e 9):
            # o dicionario passou a dizer «No registo» na propria linha e a
            # excepcao deixou de ser precisa. A mutacao, que trocava uma entrada,
            # ficou sem sujeito; passa a **acrescentar** uma invalida, que prova o
            # mesmo e nao depende de o ficheiro ter excepcoes.
            ("dominios_so_no_registo: []\n",
             'dominios_so_no_registo:\n  - coluna: estado\n    razao: "uma razao '
             'suficientemente longa para passar a verificacao de comprimento"\n',
             "nao e um dominio nao qualificado"),
            ("  - modulo: rls\n    ficheiro: db/rls.py\n", "  - modulo: rls\n", "modulo. e de .ficheiro"),
            ('papeis:\n  seccao: "3.2"', 'papeis:\n  seccao: "3.9"', "Pap"),
        ):
            with self.subTest(padrao=padrao):
                self.com(politica, velho, novo, padrao)

    def test_razao_curta_nao_serve(self) -> None:
        """M43: uma area fora de ambito sem razao e uma dispensa que ninguem consegue rever."""
        texto = (self.raiz / "ci/canon-lint.yaml").read_text(encoding="utf-8")
        inicio = texto.index('  - caminho: "db/migrations/env.py"\n    razao: >-\n')
        fim = texto.index('  - caminho: "db/migrations/script.py.mako"')
        self.escrever(
            "ci/canon-lint.yaml",
            texto[:inicio] + '  - caminho: "db/migrations/env.py"\n    razao: "porque sim"\n\n' + texto[fim:],
        )
        self.erro("razao")

    def test_extensao_nao_pode_declarar_uma_variante(self) -> None:
        self.com("canon/extensoes.yaml", "extensoes:\n", "extensoes:\n  - nome: tenants.valor_kz\n    tipo: coluna\n    ticket: KAM-003\n    data: 2026-10-11\n", "valor_kz")

    def test_extensao_redundante_com_o_dicionario(self) -> None:
        self.com("canon/extensoes.yaml", "extensoes:\n", "extensoes:\n  - nome: tenants.estado\n    tipo: coluna\n    ticket: KAM-003\n    data: 2026-10-11\n", "redundante")
        self.com("canon/extensoes.yaml", "extensoes:\n", "extensoes:\n  - nome: payment.confirmed\n    tipo: evento\n    ticket: KAM-003\n    data: 2026-10-11\n", "redundante")

    def test_extensao_mal_formada(self) -> None:
        base = "  - nome: tenants.nif\n    tipo: coluna\n    ticket: KAM-003\n    data: 2026-10-11\n"
        for novo, padrao in (
            (base.replace("tipo: coluna", "tipo: campo_livre"), "tipo"),
            (base.replace("ticket: KAM-003", "ticket: KAM-3"), "KAM-NNN"),
            (base.replace("data: 2026-10-11", "data: 2026-13-45"), "nao existe"),
            (base.replace("data: 2026-10-11", "data: 2099-01-01"), "futura"),  # M9
            (base.replace("    data: 2026-10-11\n", ""), "falta data"),
            (base + "    aprovado: sim\n", "aprovado"),
            (base + base, "repetida"),
        ):
            with self.subTest(padrao=padrao):
                self.com("canon/extensoes.yaml", base, novo, padrao)

    #: Uma divida bem formada, para as mutacoes terem o que estragar.
    #:
    #: O `ci/canon-allow.yaml` real tem `dividas: []` desde o KAM-139, que as
    #: pagou todas. Estas seis mutacoes partiam de uma divida **do
    #: repositorio** e ficaram sem sujeito no dia em que ele ficou limpo — que
    #: e o dia em que se quer que tudo isto continue a ser verificado.
    DIVIDA_BOA = (
        "dividas:\n"
        "  - ficheiro: docs/tecnica/03_Core_Comercio_Medusa.md\n"
        "    variante: kamba_ops\n"
        "    ocorrencias: 1\n"
        "    origem: KAM-111\n"
        "    criado_em: 2026-10-11\n"
        "    expira_em: 2026-11-10\n"
        '    razao: "Uma divida construida pela bateria para exercitar a validacao da '
        'forma de uma entrada, que o repositorio real ja nao tem por estarem todas pagas."\n'
    )

    def com_divida_boa(self, velho: str, novo: str, padrao: str) -> None:
        """Instala a divida boa, estraga-a como se diz, e exige a mensagem."""
        caminho = self.raiz / "ci/canon-allow.yaml"
        original = caminho.read_text(encoding="utf-8")
        self.escrever("ci/canon-allow.yaml", original.replace("dividas: []\n", self.DIVIDA_BOA))
        try:
            self.com("ci/canon-allow.yaml", velho, novo, padrao)
        finally:
            self.escrever("ci/canon-allow.yaml", original)

    def test_a_divida_boa_e_mesmo_boa(self) -> None:
        """Sem isto, as seis que seguem podiam estar a falhar pela razao errada."""
        caminho = self.raiz / "ci/canon-allow.yaml"
        original = caminho.read_text(encoding="utf-8")
        self.escrever("ci/canon-allow.yaml", original.replace("dividas: []\n", self.DIVIDA_BOA))
        self.trocar(DOC03, "kamba_batch (BYPASSRLS, auditado)", "kamba_ops (BYPASSRLS, auditado)")
        self.assertEqual([str(a) for a in cli.verificar(self.raiz, hoje=HOJE)[0]], [])

    def test_excepcao_de_documento_mal_formada(self) -> None:
        divida = "    variante: kamba_ops\n    ocorrencias: 1\n    origem: KAM-111\n    criado_em: 2026-10-11\n    expira_em: 2026-11-10\n"
        for velho, novo, padrao in (
            ("    variante: kamba_ops\n    ocorrencias: 1\n", "    variante: kamba_xyz\n    ocorrencias: 1\n", "nao e uma variante"),
            ("    variante: kamba_ops\n    ocorrencias: 1\n", "    variante: kamba_ops\n    ocorrencias: 0\n", "ocorrencias"),
            (divida, divida.replace("expira_em: 2026-11-10", "expira_em: 2027-10-11"), "maximo"),
            (divida, divida.replace("criado_em: 2026-10-11", "criado_em: 2031-01-01").replace("expira_em: 2026-11-10", "expira_em: 2031-01-31"), "futuro"),  # M9
            (divida, divida.replace("    origem: KAM-111\n", ""), "origem"),
            (divida, divida + "    aprovado_por: ninguem\n", "aprovado_por"),  # M40
        ):
            with self.subTest(padrao=padrao):
                self.com_divida_boa(velho, novo, padrao)
        self.com("ci/canon-allow.yaml", "version: 1\n", "version: 1\ntoleradas: []\n", "toleradas")  # M40

    def test_historica_sem_ancora_ou_com_ancora_que_nao_prova_nada(self) -> None:
        """M9: uma «historica» nao tem prazo, pelo que tem de provar que e citacao."""
        ancora = '    ancoras:\n      - "sem moeda | Perde cêntimos"\n'
        self.com("ci/canon-allow.yaml", ancora, "", "ancoras")
        self.com("ci/canon-allow.yaml", ancora, '    ancoras:\n      - "valor_kz int"\n', "nao\n?.*pode conter a propria variante|propria variante")
        self.com("ci/canon-allow.yaml", ancora, '    ancoras:\n      - "|"\n', "12 caracteres")


if __name__ == "__main__":
    unittest.main()
