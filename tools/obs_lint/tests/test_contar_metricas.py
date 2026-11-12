"""Testes do `contar_metricas` — o instrumento por tras dos numeros do KAM-080.

Este ficheiro existe pela razao que a revisao adversarial tornou visivel: a
secao de verificacao do bloco citava «109 metricas, 23 servidas, 7 alcancaveis»
em quatro sitios **sem comando nenhum**, e um numero reconstruido a mao e
INDICIO. O instrumento fechou essa lacuna; estes testes fecham a seguinte, que e
«e o instrumento esta certo?».

O que se prende aqui e o **predicado**, nao o numero. Um numero muda com o
repositorio; o predicado e o que decide se o numero quer dizer algo.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from obs_lint import contar_metricas as cm

RAIZ = Path(__file__).resolve().parents[3]


class _ComArvore(unittest.TestCase):
    """Monta uma arvore minima, para medir o predicado e nao o repositorio."""

    def arvore(self, ficheiros: dict[str, str]) -> Path:
        raiz = Path(tempfile.mkdtemp(prefix="contar-"))
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        for caminho, conteudo in ficheiros.items():
            alvo = raiz / caminho
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(conteudo, encoding="utf-8")
        return raiz


class TestPredicado(_ComArvore):
    """O predicado 1: um modulo de metricas e o que emite formato de exposicao."""

    def test_um_ficheiro_sem_type_nao_e_modulo_de_metricas(self) -> None:
        """E o predicado, e nao o nome: um `metricas.ts` sem `# TYPE` nao conta."""
        raiz = self.arvore(
            {"packages/x/src/metricas.ts": 'export const METRICA_A = "a_total";\n'}
        )
        self.assertEqual(cm._modulos(raiz), [])

    def test_um_ficheiro_com_type_e_modulo_mesmo_com_outro_nome(self) -> None:
        raiz = self.arvore(
            {
                "packages/x/src/qualquer.ts": (
                    'const AJUDA = "# TYPE";\nexport const METRICA_A = "a_total";\n'
                )
            }
        )
        self.assertEqual([p.name for p in cm._modulos(raiz)], ["qualquer.ts"])

    def test_as_pastas_ignoradas_nao_entram(self) -> None:
        corpo = 'const A = "# TYPE";\nexport const METRICA_A = "a_total";\n'
        raiz = self.arvore(
            {
                "packages/x/node_modules/m/metricas.ts": corpo,
                "packages/x/dist/metricas.ts": corpo,
                "packages/x/tests/metricas.ts": corpo,
                "packages/x/src/metricas.ts": corpo,
            }
        )
        self.assertEqual([p.parent.name for p in cm._modulos(raiz)], ["src"])

    def test_so_as_tres_raizes_se_leem(self) -> None:
        corpo = 'const A = "# TYPE";\nexport const METRICA_A = "a_total";\n'
        raiz = self.arvore({"tools/x/metricas.ts": corpo, "docs/metricas.ts": corpo})
        self.assertEqual(cm._modulos(raiz), [])


class TestNomes(_ComArvore):
    """O predicado 2: o que e, e o que nao e, um nome de metrica."""

    def _nomes(self, corpo: str, extensao: str = ".ts") -> set[str]:
        raiz = self.arvore({f"packages/x/src/metricas{extensao}": corpo})
        return cm._nomes(raiz / f"packages/x/src/metricas{extensao}")

    def test_uma_constante_METRICA_da_o_nome(self) -> None:
        corpo = '# TYPE\nexport const METRICA_ENVIADAS = "outbound_sent_total";\n'
        self.assertEqual(self._nomes(corpo), {"outbound_sent_total"})

    def test_a_forma_com_Final_do_python_tambem(self) -> None:
        corpo = '# TYPE\nMETRICA_TURNOS: Final = "agr_turns_total"\n'
        self.assertEqual(self._nomes(corpo, ".py"), {"agr_turns_total"})

    def test_uma_chave_de_tabela_de_ajuda_da_o_nome(self) -> None:
        corpo = '# TYPE\nconst AJUDA = {\n  "gwy_requests_total": ["counter", "x"],\n};\n'
        self.assertEqual(self._nomes(corpo), {"gwy_requests_total"})

    def test_uma_etiqueta_nao_e_uma_metrica(self) -> None:
        """A razao de o predicado ser estreito: `ETIQUETAS` nao sao metricas."""
        corpo = (
            "# TYPE\n"
            'export const ETIQUETA = "filtro";\n'
            'export const ORIGENS = ["bucket", "meta"];\n'
            'export const METRICA_A = "a_total";\n'
        )
        self.assertEqual(self._nomes(corpo), {"a_total"})

    def test_um_nome_sem_underscore_nao_conta(self) -> None:
        corpo = '# TYPE\nexport const METRICA_A = "up";\n'
        self.assertEqual(self._nomes(corpo), set())

    def test_um_nome_com_maiusculas_nao_conta(self) -> None:
        corpo = '# TYPE\nexport const METRICA_A = "Nao_E_Nome";\n'
        self.assertEqual(self._nomes(corpo), set())

    def test_uma_docstring_python_que_lista_metricas_nao_conta(self) -> None:
        """Os modulos desta casa listam as metricas em prosa no cabecalho.

        Sem retirar os comentarios, a tabela do cabecalho era contada duas
        vezes — e e por isso que o `_nomes` os retira em Python.
        """
        corpo = (
            "# TYPE\n"
            '# METRICA_FALSA = "nao_existe_total"\n'
            'METRICA_A: Final = "existe_total"\n'
        )
        self.assertEqual(self._nomes(corpo, ".py"), {"existe_total"})


class TestRepositorio(unittest.TestCase):
    """Sobre a arvore real: **o conjunto nomeado, e nao a contagem**.

    ## As duas versoes erradas que esta classe teve, por ordem

    **A primeira prendia `len(modulos) == 18` e `len(todos) == 107`**, com a
    justificacao de que «um numero que se mexe sem ninguem notar e pior do que
    nenhum». A intencao estava certa; a forma nao. O KAM-091 fundiu com um
    `provisioning/metricas.ts` (6 metricas) e o teste ficou vermelho com
    `19 != 18` — num *merge* que nao tinha nada a ver com este ticket, e dizendo
    so que um numero mudou, nunca **qual**.

    **A segunda trocou a igualdade por um piso** (`>= 19`, `>= 113`), para nao
    reprovar quem acrescenta uma metrica. Resolvia o falso alarme e abria o
    buraco do lado oposto: um modulo novo passava **calado**, e com ele a prosa
    que cita os totais. E exactamente o defeito que o
    `tools/isolamento/baterias/x01_rotas.py` nomeia — «as listas sao literais de
    proposito. Um filtro fazia a cobertura passar para sempre e uma rota nova
    nascia coberta, que e o *sem teste silencioso*». Um piso e um filtro com
    outro nome.

    **Esta e a forma do repositorio**, e a correccao veio de fora (do
    orquestrador, a propor o padrao das listas `TABELAS_*` do
    `db/tests/base.py`): asserir o **conjunto**. Um modulo novo aparece como
    nome a mais e **diz qual**; um que morra aparece como nome a menos. A
    diferenca entre as tres versoes nao e o rigor — e a mensagem de erro, e e a
    mensagem que paga o minuto de quem a le.

    O custo fica dito onde se paga: quem acrescentar um modulo de metricas tem
    de actualizar esta lista **e** propagar os totais para a prosa. O `RECADO`
    diz-lhe as duas coisas e onde.

    Onde a exactidao dos **numeros** pertence e no `TestPredicado` e no
    `TestNomes`, que correm sobre arvores sinteticas escritas pelo proprio
    teste. Aqui afirma-se o inventario, a estrutura e a ordem:

      * todo o modulo encontrado emite formato de exposicao (o predicado 1);
      * o inventario e **exactamente** o que esta lista diz;
      * o modulo do COM conta **zero**, porque importa os nomes;
      * o AGR e o modulo com **mais** metricas, que e o que tornou a sua lacuna
        a maior da arvore.
    """

    #: O inventario nomeado dos modulos de metricas, a 2026-11-08. A lista nao
    #: se consulta para saber o estado da arvore: o teste abaixo e que o diz, e
    #: a data serve so para datar a ultima vez que alguem a leu por inteiro.
    #:
    #: **E uma lista literal e nao uma contagem**, e a escolha e do repositorio e
    #: nao minha: o `tools/isolamento/baterias/x01_rotas.py` escreve a razao —
    #: «as listas sao literais de proposito. Um filtro fazia a cobertura passar
    #: para sempre e uma rota nova nascia coberta, que e o "sem teste
    #: silencioso"». Um **piso** tem o mesmo defeito que o filtro: um modulo de
    #: metricas novo passava calado, e com ele a prosa que cita os totais.
    #:
    #: Um conjunto diz **qual** modulo nasceu ou morreu; uma contagem diz so que
    #: o numero mudou. A diferenca e a mensagem de erro, e e a mensagem que paga
    #: o minuto de quem a le.
    MODULOS = (
        # Nasceu com o KAM-079 (backups pgBackRest e PITR). A propriedade que o
        # distingue: **a fonte dos valores nao esta no processo que o importa** —
        # a idade do WAL e o desfecho de um restauro sao medidos por um `job`
        # que ainda nao existe (agendador: KAM-071/KAM-078), pelo que o modulo
        # declara quatro nomes com `exposta_por: []` no catalogo e nenhum
        # processo os serve. E tambem o modulo que mostrou que esta lista e a
        # **quinta** superficie da propagacao: o ticket levou os numeros novos
        # as quatro de prosa que o RECADO nomeia e deixou o inventario atras,
        # pelo que o gate 4 reprovou o PR com o lint a dar zero achados.
        "libs/py-core/src/kamba_core/backup/metricas.py",
        # Nasceu com o KAM-193 (as tres do IDX). Biblioteca em `libs/py-core`,
        # como o `backup`, mas **servida**: quem a importa e a serve e o AGR,
        # que e o processo onde a pesquisa corre, na mesma `/metrics` que o
        # registo dele. Tem um eixo de dois nomes (`idx_query_ms{ramo,modo}`),
        # que a biblioteca do AGR nao sabe escrever.
        "libs/py-core/src/kamba_core/idx/metricas.py",
        "libs/py-core/src/kamba_core/ten/metricas.py",
        "packages/core-ts/src/agr/metricas.ts",
        "packages/core-ts/src/avisos/metricas.ts",
        "packages/core-ts/src/chr/metricas.ts",
        "packages/core-ts/src/coexistencia/metricas.ts",
        "packages/core-ts/src/consentimento/metricas.ts",
        "packages/core-ts/src/entrada/metricas.ts",
        "packages/core-ts/src/eventos/metricas.ts",
        "packages/core-ts/src/hnd/metricas.ts",
        "packages/core-ts/src/med/metricas.ts",
        "packages/core-ts/src/metering/metricas.ts",
        "packages/core-ts/src/modos/metricas.ts",
        "packages/core-ts/src/onboarding/metricas.ts",
        "packages/core-ts/src/outbound/metricas.ts",
        # Nasceu com o KAM-091 (saga de provisioning) **enquanto este ticket
        # estava aberto**, e foi o que mostrou que uma igualdade sobre a
        # contagem reprovava o PR de quem acrescenta uma metrica.
        "packages/core-ts/src/provisioning/metricas.ts",
        "packages/core-ts/src/qualidade/metricas.ts",
        # Nasceu com o KAM-116 (agregador de SMS) **depois de este ticket
        # fundir**, e e o segundo exemplo da mesma coisa que o
        # `provisioning` foi o primeiro: sete nomes que nenhum servico
        # importa, porque quem vai ligar a porta e o KAM-086.
        "packages/core-ts/src/sms/metricas.ts",
        "packages/core-ts/src/ten/metricas.ts",
        "services/agr/src/kamba_agr/metricas.py",
        # Conta **zero** nomes, e esta aqui por isso: e um modulo de exposicao
        # que importa os nomes do `repo-base`. Ver o teste da reconciliacao.
        "services/com/src/metricas.ts",
        # Nasceu com o KAM-055 (eventos de pagamento). **Nao e um modulo de
        # exposicao como o `services/com/src/metricas.ts` acima**: declara o
        # seu proprio histograma — o atraso entre o evento de pagamento e a
        # encomenda `paga` — porque o corte de 5 s e o criterio 9 daquele
        # bloco, e um histograma com os cortes de outro dono nao o mede.
        "services/com/src/payments/metricas.ts",
        # Nasceu com o KAM-048 (lembretes de marcacao) **depois de este ticket
        # fundir**, e e o terceiro exemplo do que o `provisioning` foi o primeiro
        # e o `sms` o segundo. Dois pormenores que o distinguem dos outros vinte
        # e dois, e os dois sao o desenho e nao acidente:
        #
        # * vive **dentro de um servico** que nao o expoe, ao contrario dos dois
        #   anteriores, que sao biblioteca em `packages/core-ts`. O
        #   `services/com/src/metricas.ts` serve a porta `/metrics` e conta zero
        #   nomes; este declara tres e nao serve nada — quem o expoe sera quem
        #   ligar o modulo (KAM-071). **Sem ordinal de proposito:** a primeira
        #   versao dizia «o primeiro», que e uma afirmacao sobre a ordem de
        #   fusao e nao sobre o codigo, e o KAM-055 traz um `payments/metricas.ts`
        #   pelo mesmo caminho num PR aberto ao lado;
        # * **nao tem contador de custo**, e e a ausencia que vale a pena nomear:
        #   o custo de um lembrete e o custo da mensagem que o Outbound enviou, e
        #   quem o acumula e o `meta_cost_usd_total` dele. Um segundo acumulador
        #   sobre os mesmos envios somava o mesmo dinheiro duas vezes num painel
        #   que nao tinha como saber.
        "services/com/src/servicos/reminders/metricas.ts",
        # Nasceu com o KAM-099 (painel do dono). Vive dentro do `onboarding-web`,
        # que o importa e **nao** o serve: o servico nao tem rota `/metrics`, e
        # abri-la e uma superficie HTTP nova com caso no gate 6.
        "services/onboarding-web/src/painel/metricas.ts",
    )

    #: O que fazer quando este teste ficar vermelho. Vai na mensagem de erro,
    #: porque e o unico sitio onde quem o ve esta a olhar.
    RECADO = (
        "Acrescentou ou removeu um modulo de metricas. Isto nao e um defeito: e "
        "a propagacao que vem com ele. (1) actualize esta lista; (2) corra "
        "`python tools/obs_lint/contar_metricas.py` e leve os numeros novos a "
        "`docs/observabilidade.md` §2.1 e §2.2 e a seccao de verificacao do "
        "KAM-080 no `specs/EPIC-08`. Os totais citados na prosa vivem desses "
        "numeros, e um numero parado na prosa e pior do que nenhum."
    )

    def test_cada_modulo_encontrado_emite_formato_de_exposicao(self) -> None:
        """O predicado 1, verificado na arvore real e nao so nas sinteticas."""
        modulos = cm._modulos(RAIZ)
        self.assertTrue(modulos, "zero modulos nao e um zero util")
        for modulo in modulos:
            with self.subTest(modulo=modulo.relative_to(RAIZ).as_posix()):
                self.assertIn(
                    cm.MARCA_DE_EXPOSICAO, modulo.read_text(encoding="utf-8")
                )

    def test_o_inventario_dos_modulos_e_exactamente_este(self) -> None:
        """O **conjunto**, que diz qual mudou — e nao a contagem, que nao diz."""
        encontrados = {
            m.relative_to(RAIZ).as_posix() for m in cm._modulos(RAIZ)
        }
        esperados = set(self.MODULOS)
        novos = sorted(encontrados - esperados)
        idos = sorted(esperados - encontrados)
        self.assertEqual(
            encontrados,
            esperados,
            f"modulos novos: {novos or 'nenhum'}; desaparecidos: "
            f"{idos or 'nenhum'}. {self.RECADO}",
        )

    def test_o_com_conta_zero_porque_importa_os_nomes_do_repo_base(self) -> None:
        """A reconciliacao, que e estrutural e nao um numero.

        O modulo que **expoe** as duas metricas do COM nao as **declara**: os
        nomes vivem no `repo-base/index.ts` e sao importados. E a razao pela qual
        a contagem por modulo da dois a menos do que a soma das metricas
        servidas, e esta escrita em `docs/observabilidade.md` §2.1.
        """
        modulo = RAIZ / "services" / "com" / "src" / "metricas.ts"
        self.assertIn(cm.MARCA_DE_EXPOSICAO, modulo.read_text(encoding="utf-8"))
        self.assertEqual(cm._nomes(modulo), set())
        repo_base = (RAIZ / "services/com/src/repo-base/index.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn('"com_repo_filtro_em_falta_total"', repo_base)
        self.assertIn('"com_repo_consultas_total"', repo_base)

    def test_o_agr_e_o_modulo_com_mais_metricas(self) -> None:
        """A lacuna que este ticket fechou, afirmada por **ordem** e nao por numero.

        O AGR servia **zero** das suas metricas antes do KAM-080, e e o modulo
        que mais tem — o que e o que torna a lacuna a maior da arvore. Isso
        continua verdade quando alguem lhe acrescentar uma metrica, e um
        `== 44` nao continuava.
        """
        por_modulo = {m: len(cm._nomes(m)) for m in cm._modulos(RAIZ)}
        agr = RAIZ / "services" / "agr" / "src" / "kamba_agr" / "metricas.py"
        self.assertIn(agr, por_modulo)
        maior = max(por_modulo, key=lambda m: por_modulo[m])
        self.assertEqual(maior, agr, {k.name: v for k, v in por_modulo.items()})
        self.assertGreaterEqual(por_modulo[agr], 44)


class TestCli(unittest.TestCase):
    def test_sai_com_zero_na_arvore_real(self) -> None:
        self.assertEqual(cm.main(["--root", str(RAIZ)]), 0)

    def test_com_detalhe_tambem(self) -> None:
        self.assertEqual(cm.main(["--root", str(RAIZ), "--detalhe"]), 0)

    def test_uma_arvore_sem_modulos_sai_com_dois(self) -> None:
        """Zero módulos não é um zero útil: é «não se conseguiu verificar»."""
        vazia = Path(tempfile.mkdtemp(prefix="contar-vazia-"))
        self.addCleanup(shutil.rmtree, vazia, ignore_errors=True)
        self.assertEqual(cm.main(["--root", str(vazia)]), 2)


if __name__ == "__main__":
    unittest.main()
