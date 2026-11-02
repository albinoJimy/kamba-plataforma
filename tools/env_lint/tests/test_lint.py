"""Testes das regras do `env_lint`.

As regras sao puras: lêem um `Dados` e devolvem achados. Por isso os testes
constroem um `Dados` mínimo em memoria em vez de tocarem no disco — e o que
toca no disco (`carregar`, `varrer`) testa-se contra a arvore real em
`test_arvore_real.py`.

**A distincao importa.** Um teste que monte uma arvore de ficheiros falsa
prova que a regra funciona *naquela* arvore; o canario (`env_lint canario`)
prova que funciona na arvore que o gate verifica. Sao perguntas diferentes e
estao em sitios diferentes.
"""

from __future__ import annotations

import unittest

from env_lint import lint, matriz


def _ambiente(nome: str, **sobrepor) -> dict:
    """Um `env.yaml` valido, com as sobreposicoes pedidas por caminho pontuado."""
    base = {
        "versao": 1,
        "ambiente": nome,
        "dados": {
            "classe": "synthetic",
            "decisao_d1": None,
            "apd_refs": [],
            "restauro_de": [],
        },
        # O `compute` tem de ser **coerente** com a regra de derivacao: a
        # `forma` sai do `vcpu` e do `memoria_gb`, ou e `compose-local` com os
        # tres nulos. Uma fixture incoerente fazia os outros testes medir ruido.
        "compute": (
            {"forma": "compose-local", "vcpu": None, "memoria_gb": None, "disco": None}
            if nome == "dev"
            else {"forma": "4vcpu-16gb", "vcpu": 4, "memoria_gb": 16, "disco": "nvme"}
        ),
        "meta": {"modo": "mock", "assina_corpo": True},
        "facilitador": {
            "modo": "mock",
            "proxypay_base": None,
            "sandbox_appypay": "nao-aplicavel",
        },
        "llm": {"modo": "chave-de-teste", "budget": "minimo"},
        "segredos": {
            "projecto": "local" if nome == "dev" else nome,
            "cofre": "nenhum" if nome == "dev" else "doppler",
        },
        "acesso": {"modo": "equipa"},
        "dns": {"ttl_segundos": 300},
        "custo": {
            "etiquetas": {"kamba_env": nome, "kamba_data_class": "synthetic"},
            "mensal_usd": None,
        },
    }
    for caminho, valor in sobrepor.items():
        partes = caminho.split("__")
        alvo = base
        for parte in partes[:-1]:
            alvo = alvo[parte]
        alvo[partes[-1]] = valor
    return base


def _linhas(ambientes: dict[str, dict], chaves: tuple[str, ...]) -> list[matriz.Linha]:
    """Uma matriz que, por construcao, concorda com a configuracao dada."""
    feitas = []
    for chave in chaves:
        valores = {}
        for nome, bruto in ambientes.items():
            actual = bruto
            for parte in chave.split("."):
                actual = actual[parte]
            valores[nome] = lint.normalizar(actual)
        feitas.append(matriz.Linha(aspecto=chave, chave=chave, valores=valores))
    return feitas


def _dados(**sobrepor_por_ambiente) -> lint.Dados:
    ambientes = {
        nome: _ambiente(nome, **sobrepor_por_ambiente.get(nome, {}))
        for nome in lint.AMBIENTES
    }
    return lint.Dados(
        ambientes=ambientes,
        linhas_da_matriz=_linhas(ambientes, lint.CHAVES_DA_MATRIZ),
        linhas_acrescentadas=_linhas(ambientes, lint.CHAVES_ACRESCENTADAS),
        inventario={
            "meta_app_secret": ("dev", "staging", "prod"),
            "proxypay_api_key": ("staging", "prod"),
            "vpn_wireguard_admin": ("staging", "prod"),
        },
        ficheiros={"infra/envs/dev/env.yaml": "# nada\n"},
        pastas_de_ambiente=lint.AMBIENTES,
    )


def _codigos(dados: lint.Dados) -> set[str]:
    return {achado.codigo for achado in lint.avaliar(dados)}


class TestBase(unittest.TestCase):
    def test_a_configuracao_coerente_nao_da_achados(self) -> None:
        # O teste que torna os outros legiveis: sem ele, um achado podia vir de
        # ruido da fixture e nao da mutacao.
        self.assertEqual(_codigos(_dados()), set())


class TestClasseDeDados(unittest.TestCase):
    def test_real_sem_d1_e_sem_apd_ref_da_os_dois_achados(self) -> None:
        dados = _dados(prod={"dados__classe": "real", "custo__etiquetas__kamba_data_class": "real"})
        codigos = _codigos(dados)
        self.assertIn("real-sem-d1", codigos)
        self.assertIn("real-sem-apd-ref", codigos)

    def test_real_com_as_duas_referencias_passa(self) -> None:
        # A metade positiva, e e a que prova que a barreira nao e um bloqueio
        # permanente mal disfarcado: com D1 e com protocolo, `real` passa.
        dados = _dados(
            prod={
                "dados__classe": "real",
                "dados__decisao_d1": "D1/2026-12-01/jnb-cpt",
                "dados__apd_refs": ["APD-2026-00123"],
                "custo__etiquetas__kamba_data_class": "real",
            }
        )
        codigos = _codigos(dados)
        self.assertNotIn("real-sem-d1", codigos)
        self.assertNotIn("real-sem-apd-ref", codigos)

    def test_classe_fora_do_dominio(self) -> None:
        self.assertIn("classe-desconhecida", _codigos(_dados(dev={"dados__classe": "sinteticos"})))

    def test_d1_mal_formada(self) -> None:
        dados = _dados(prod={"dados__decisao_d1": "reuniao de Dezembro"})
        self.assertIn("d1-mal-formada", _codigos(dados))

    def test_d1_bem_formada_mas_com_classe_sintetica_avisa(self) -> None:
        dados = _dados(prod={"dados__decisao_d1": "D1/2026-12-01/luanda-raxio"})
        codigos = _codigos(dados)
        self.assertIn("d1-sem-classe-real", codigos)
        self.assertNotIn("d1-mal-formada", codigos)

    def test_apd_ref_com_espacos(self) -> None:
        dados = _dados(prod={"dados__apd_refs": ["protocolo 1 de 2026"]})
        self.assertIn("apd-ref-mal-formada", _codigos(dados))

    def test_etiqueta_de_custo_que_mente_sobre_a_classe(self) -> None:
        dados = _dados(dev={"custo__etiquetas__kamba_data_class": "real"})
        self.assertIn("etiqueta-de-classe-divergente", _codigos(dados))


class TestRestauro(unittest.TestCase):
    def test_staging_a_aceitar_restauro_de_prod(self) -> None:
        dados = _dados(staging={"dados__restauro_de": ["prod"]})
        self.assertIn("restauro-de-prod", _codigos(dados))

    def test_prod_a_aceitar_restauro_de_prod_nao_e_achado(self) -> None:
        dados = _dados(prod={"dados__restauro_de": ["prod"]})
        self.assertNotIn("restauro-de-prod", _codigos(dados))

    def test_ambiente_que_nao_existe(self) -> None:
        dados = _dados(dev={"dados__restauro_de": ["qa"]})
        self.assertIn("restauro-desconhecido", _codigos(dados))

    def test_restauro_que_nao_e_lista(self) -> None:
        dados = _dados(dev={"dados__restauro_de": "prod"})
        self.assertIn("restauro-mal-formado", _codigos(dados))

    def test_seccao_dados_em_falta(self) -> None:
        # Sem a secção não há classe de dados, e sem classe de dados o critério
        # 4 não tem nada para verificar. Falha, em vez de passar por omissão.
        dados = _dados()
        del dados.ambientes["staging"]["dados"]
        self.assertIn("dados-ausente", _codigos(dados))


class TestSegredos(unittest.TestCase):
    def test_dois_ambientes_no_mesmo_projecto(self) -> None:
        dados = _dados(staging={"segredos__projecto": "prod"})
        codigos = _codigos(dados)
        self.assertIn("projecto-repetido", codigos)
        # E a consequencia que o criterio 5 nomeia: as chaves deixam de ser
        # distintas por ambiente.
        self.assertIn("chave-partilhada-entre-ambientes", codigos)

    def test_projecto_local_so_em_dev(self) -> None:
        dados = _dados(prod={"segredos__projecto": "local"})
        self.assertIn("projecto-local-fora-de-dev", _codigos(dados))

    def test_ambiente_sem_projecto_declarado(self) -> None:
        # O mapeamento do critério 5 é o `segredos.projecto`. Um ambiente sem
        # ele não tem mapeamento, e um mapeamento em falta não se distingue de
        # um mapeamento correcto se ninguém o exigir.
        dados = _dados()
        del dados.ambientes["prod"]["segredos"]["projecto"]
        self.assertIn("projecto-em-falta", _codigos(dados))

    def test_segredo_de_prod_referenciado_em_staging(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/staging/main.tf"] = 'x = "prod/META_APP_SECRET"\n'
        self.assertIn("segredo-de-outro-ambiente", _codigos(dados))

    def test_segredo_do_proprio_ambiente_passa(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/staging/main.tf"] = 'x = "staging/META_APP_SECRET"\n'
        self.assertEqual(_codigos(dados), set())

    def test_referencia_dentro_de_um_modulo(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/modules/host-base/main.tf"] = 'x = "prod/META_APP_SECRET"\n'
        self.assertIn("segredo-fora-de-um-ambiente", _codigos(dados))

    def test_segredo_que_nao_existe_naquele_ambiente(self) -> None:
        # `proxypay_api_key` e de staging/prod: `dev` nao o tem, e e a linha
        # «Facilitador: mock» do doc 09 §6 a ser verificada.
        dados = _dados()
        dados.ficheiros["infra/envs/dev/x.tf"] = 'x = "local/PROXYPAY_API_KEY"\n'
        self.assertIn("segredo-nao-existe-no-ambiente", _codigos(dados))

    def test_segredo_fora_do_inventario(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/prod/x.tf"] = 'x = "prod/CHAVE_QUE_NINGUEM_DECLAROU"\n'
        self.assertIn("segredo-fora-do-inventario", _codigos(dados))

    def test_um_caminho_de_ficheiro_nao_e_uma_referencia_de_segredo(self) -> None:
        # O falso positivo que mataria este lint, e que este teste apanhou de
        # facto: `prod/LEIA-ME` casava `prod/LEIA`, porque a corrida de
        # maiusculas para no hifen e o hifen e fronteira de palavra. Dava um
        # `segredo-fora-do-inventario` sobre um caminho de ficheiro — e um lint
        # que acusa caminhos e um lint que alguem desliga.
        #
        # O ficheiro e `.tf` de proposito: num `.md` o varrimento nem entra (ver
        # o teste seguinte), e o que se quer testar aqui e o **padrao**.
        dados = _dados()
        dados.ficheiros["infra/modules/host-base/caminhos.tf"] = (
            "# o ambiente prod corre em prod/ e nao em staging; ver prod/LEIA-ME\n"
            "# e tambem prod/etc/HOSTS e prod/A.B\n"
        )
        self.assertEqual(_codigos(dados), set())

    def test_markdown_nao_entra_no_varrimento(self) -> None:
        # A fronteira e entre configuracao e documentacao: o `infra/README.md`
        # **documenta a forma** de uma referencia e tem de poder escrever um
        # exemplo. Foi o proprio lint a acusa-lo.
        #
        # O que se perde fica dito: uma referencia cruzada escrita em Markdown
        # passa — e passa porque o OpenTofu nao le `.md`, pelo que ali nao muda
        # comportamento nenhum. Um *valor* de segredo em Markdown e do gate 9.
        dados = _dados()
        dados.ficheiros["infra/README.md"] = 'exemplo: `prod/META_APP_SECRET`\n'
        self.assertEqual(_codigos(dados), set())

    def test_a_mesma_referencia_num_tf_e_achado(self) -> None:
        # O par do teste anterior: sem ele, a exclusao de Markdown podia
        # crescer sem ninguem notar que ja nao sobra nada varrido.
        dados = _dados()
        dados.ficheiros["infra/envs/staging/x.tf"] = 'x = "prod/META_APP_SECRET"\n'
        self.assertIn("segredo-de-outro-ambiente", _codigos(dados))

    def test_segredo_nomeado_que_sai_do_inventario(self) -> None:
        dados = _dados()
        del dados.inventario["proxypay_api_key"]
        self.assertIn("segredo-nomeado-ausente-do-inventario", _codigos(dados))


class TestPortabilidade(unittest.TestCase):
    def test_resource_num_modulo_de_raiz(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/prod/main.tf"] = 'resource "vm" "host" {}\n'
        self.assertIn("recurso-fora-da-costura", _codigos(dados))

    def test_provider_num_modulo_comum(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/modules/host-base/main.tf"] = 'provider "aws" {}\n'
        self.assertIn("recurso-fora-da-costura", _codigos(dados))

    def test_resource_dentro_da_costura_passa(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/modules/provider-raxio/main.tf"] = 'resource "vm" "host" {}\n'
        self.assertEqual(_codigos(dados), set())

    def test_a_palavra_resource_em_prosa_nao_dispara(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/prod/main.tf"] = "# um resource aqui seria defeito\n"
        self.assertEqual(_codigos(dados), set())


class TestMatriz(unittest.TestCase):
    def test_configuracao_que_muda_sem_a_matriz(self) -> None:
        # Muda-se o trio inteiro, e nao so a `forma`: assim o achado que se
        # procura e o da matriz, e nao o `forma-divergente-do-compute` que a
        # regra de coerencia daria por ter mudado so uma das tres.
        dados = _dados()
        dados.ambientes["staging"]["compute"].update(
            {"forma": "2vcpu-8gb", "vcpu": 2, "memoria_gb": 8}
        )
        self.assertIn("matriz-divergente", _codigos(dados))

    def test_linha_em_falta(self) -> None:
        dados = _dados()
        dados.linhas_da_matriz = dados.linhas_da_matriz[1:]
        self.assertIn("matriz-linha-em-falta", _codigos(dados))

    def test_linha_a_mais(self) -> None:
        dados = _dados()
        dados.linhas_da_matriz.append(
            matriz.Linha("Inventada", "nao.verificada", {a: "x" for a in lint.AMBIENTES})
        )
        self.assertIn("matriz-linha-a-mais", _codigos(dados))

    def test_matriz_com_uma_chave_que_a_configuracao_nao_tem(self) -> None:
        dados = _dados()
        del dados.ambientes["dev"]["acesso"]
        codigos = _codigos(dados)
        self.assertIn("configuracao-sem-a-chave", codigos)


class TestEsquemaEEstrutura(unittest.TestCase):
    def test_ambiente_em_falta(self) -> None:
        dados = _dados()
        del dados.ambientes["staging"]
        self.assertIn("ambiente-em-falta", _codigos(dados))

    def test_chave_desconhecida(self) -> None:
        dados = _dados()
        dados.ambientes["dev"]["regiao"] = "luanda"
        # Uma chave a mais e achado e nao silencio: era a forma de a D1 entrar
        # por um campo que ninguem verifica.
        self.assertIn("chave-desconhecida", _codigos(dados))

    def test_ambiente_mal_declarado(self) -> None:
        dados = _dados()
        dados.ambientes["dev"]["ambiente"] = "staging"
        self.assertIn("ambiente-mal-declarado", _codigos(dados))


class TestCoerenciaInterna(unittest.TestCase):
    """As folhas que a matriz não compara.

    Esta classe nasceu de um achado da revisão adversarial: o `env.yaml` tem 24
    folhas e a matriz compara 12. Nove ficavam sem regra, e duas delas —
    `compute.vcpu` e `compute.memoria_gb` — são as que o HCL **consome**.
    Cada teste aqui é uma dessas folhas a ficar amarrada a uma que a matriz vê.
    """

    def test_forma_que_nao_deriva_do_vcpu(self) -> None:
        dados = _dados(staging={"compute__forma": "4vcpu-16gb", "compute__vcpu": 64})
        self.assertIn("forma-divergente-do-compute", _codigos(dados))

    def test_forma_que_deriva_do_vcpu_passa(self) -> None:
        dados = _dados(staging={"compute__forma": "64vcpu-256gb", "compute__vcpu": 64,
                                "compute__memoria_gb": 256, "compute__disco": "nvme"})
        self.assertNotIn("forma-divergente-do-compute", _codigos(dados))

    def test_compose_local_com_host(self) -> None:
        dados = _dados(dev={"compute__vcpu": 4})
        self.assertIn("compute-local-com-host", _codigos(dados))

    def test_disco_que_nao_e_nvme(self) -> None:
        dados = _dados(staging={"compute__forma": "4vcpu-16gb", "compute__vcpu": 4,
                                "compute__memoria_gb": 16, "compute__disco": "hdd"})
        self.assertIn("disco-sem-nvme", _codigos(dados))

    def test_versao_desconhecida(self) -> None:
        dados = _dados()
        dados.ambientes["dev"]["versao"] = 2
        self.assertIn("versao-desconhecida", _codigos(dados))

    def test_ambiente_sem_verificacao_de_assinatura(self) -> None:
        dados = _dados(dev={"meta__assina_corpo": False})
        self.assertIn("meta-sem-assinatura", _codigos(dados))

    def test_endpoint_de_producao_num_ambiente_sintetico(self) -> None:
        # O pior dos nove, e o que a revisão usou: um `staging` a cobrar a
        # alguém de verdade porque ninguém comparava este campo.
        dados = _dados(staging={"facilitador__modo": "sandbox",
                                "facilitador__proxypay_base": "api.proxypay.co.ao",
                                "facilitador__sandbox_appypay": "indicio"})
        self.assertIn("facilitador-fora-da-sandbox", _codigos(dados))

    def test_sandbox_correcta_passa(self) -> None:
        dados = _dados(staging={"facilitador__modo": "sandbox",
                                "facilitador__proxypay_base": lint.SANDBOX_DO_FACILITADOR,
                                "facilitador__sandbox_appypay": "indicio"})
        codigos = _codigos(dados)
        self.assertNotIn("facilitador-fora-da-sandbox", codigos)
        self.assertNotIn("appypay-com-estado-errado", codigos)

    def test_endpoint_a_mais_num_mock(self) -> None:
        dados = _dados(dev={"facilitador__proxypay_base": lint.SANDBOX_DO_FACILITADOR})
        self.assertIn("facilitador-com-endpoint-a-mais", _codigos(dados))

    def test_appypay_promovida_a_confirmada(self) -> None:
        # Promover um estado é o defeito mais comum desta casa, e aqui tem gate.
        dados = _dados(staging={"facilitador__modo": "sandbox",
                                "facilitador__proxypay_base": lint.SANDBOX_DO_FACILITADOR,
                                "facilitador__sandbox_appypay": "confirmado"})
        self.assertIn("appypay-com-estado-errado", _codigos(dados))

    def test_facilitador_com_modo_inventado(self) -> None:
        dados = _dados(dev={"facilitador__modo": "quase-mock"})
        self.assertIn("facilitador-modo-desconhecido", _codigos(dados))

    def test_budget_que_nao_deriva_do_modo(self) -> None:
        dados = _dados(dev={"llm__budget": "ilimitado"})
        self.assertIn("budget-divergente-do-modo", _codigos(dados))

    def test_llm_com_modo_inventado(self) -> None:
        dados = _dados(dev={"llm__modo": "chave-emprestada"})
        self.assertIn("llm-modo-desconhecido", _codigos(dados))

    def test_cofre_que_nao_deriva_do_projecto(self) -> None:
        dados = _dados(dev={"segredos__cofre": "doppler"})
        self.assertIn("cofre-divergente-do-projecto", _codigos(dados))

    def test_projecto_remoto_sem_cofre(self) -> None:
        dados = _dados(staging={"segredos__cofre": "nenhum"})
        self.assertIn("cofre-divergente-do-projecto", _codigos(dados))


class TestFormasNativasDoOpenTofu(unittest.TestCase):
    """O `.tf.json`, que é a segunda forma que o OpenTofu carrega.

    A revisão adversarial passou um `resource` de fornecedor num módulo de raiz
    por esta via, com `tofu validate` a confirmar que o ficheiro é configuração
    a valer. A regra do critério 6 via metade dos formatos.
    """

    def test_resource_num_tf_json_de_um_modulo_de_raiz(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/prod/fornecedor.tf.json"] = (
            '{"resource": {"aws_instance": {"kamba_prod": {"ami": "x"}}}}\n'
        )
        self.assertIn("recurso-fora-da-costura", _codigos(dados))

    def test_provider_num_tf_json(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/modules/host-base/p.tf.json"] = '{"provider": {"aws": {}}}\n'
        self.assertIn("recurso-fora-da-costura", _codigos(dados))

    def test_tf_json_dentro_da_costura_passa(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/modules/provider-raxio/r.tf.json"] = (
            '{"resource": {"vm": {"host": {}}}}\n'
        )
        self.assertEqual(_codigos(dados), set())

    def test_tf_json_sem_blocos_proibidos_passa(self) -> None:
        dados = _dados()
        dados.ficheiros["infra/envs/prod/variaveis.tf.json"] = (
            '{"variable": {"ambiente": {"type": "string"}}}\n'
        )
        self.assertEqual(_codigos(dados), set())

    def test_tf_json_ilegivel_e_achado(self) -> None:
        # Um `.tf.json` que não se interpreta também não é inofensivo: o
        # OpenTofu recusa-o, e um ficheiro que o gate não consegue ler não pode
        # passar por ficheiro limpo.
        dados = _dados()
        dados.ficheiros["infra/envs/prod/roto.tf.json"] = "{nao e json\n"
        self.assertIn("configuracao-nativa-ilegivel", _codigos(dados))

    def test_segredo_cruzado_num_tfvars(self) -> None:
        # O `terraform.tfvars` é auto-carregado pelo OpenTofu: está do lado da
        # configuração, e deixá-lo fora tornava a caixa do critério 5 evitável
        # por mudar a extensão de um ficheiro.
        dados = _dados()
        dados.ficheiros["infra/envs/staging/terraform.tfvars"] = (
            'referencia_meta = "prod/META_APP_SECRET"\n'
        )
        self.assertIn("segredo-de-outro-ambiente", _codigos(dados))


class TestPastasDeAmbiente(unittest.TestCase):
    def test_uma_quarta_pasta_e_achado(self) -> None:
        # Sem esta regra, um `infra/envs/staging-dr/env.yaml` com
        # `dados.classe: real` e `restauro_de: [prod]` era invisível a quatro
        # das cinco verificações — medido pela revisão adversarial.
        dados = _dados()
        dados.pastas_de_ambiente = (*lint.AMBIENTES, "staging-dr")
        self.assertIn("ambiente-desconhecido", _codigos(dados))

    def test_as_tres_pastas_conhecidas_passam(self) -> None:
        dados = _dados()
        dados.pastas_de_ambiente = lint.AMBIENTES
        self.assertNotIn("ambiente-desconhecido", _codigos(dados))


class TestDns(unittest.TestCase):
    def test_ttl_acima_do_tecto_proposto(self) -> None:
        dados = _dados(dev={"dns__ttl_segundos": 3600})
        self.assertIn("ttl-acima-do-proposto", _codigos(dados))

    def test_ttl_abaixo_do_tecto_passa(self) -> None:
        dados = _dados(dev={"dns__ttl_segundos": 60})
        self.assertNotIn("ttl-acima-do-proposto", _codigos(dados))

    def test_ttl_booleano_nao_passa_por_inteiro(self) -> None:
        # Em Python `True` e um `int`. Sem a guarda explicita, `ttl: true`
        # passava por 1 segundo.
        dados = _dados(dev={"dns__ttl_segundos": True})
        self.assertIn("ttl-ausente", _codigos(dados))


class TestNormalizar(unittest.TestCase):
    def test_formas(self) -> None:
        self.assertEqual(lint.normalizar(None), "null")
        self.assertEqual(lint.normalizar(True), "true")
        self.assertEqual(lint.normalizar(False), "false")
        self.assertEqual(lint.normalizar([]), "[]")
        self.assertEqual(lint.normalizar(["a", "b"]), "a, b")
        self.assertEqual(lint.normalizar(300), "300")
        self.assertEqual(lint.normalizar("synthetic"), "synthetic")

    def test_booleano_antes_de_inteiro(self) -> None:
        # `True` normalizaria para "1" se a ordem dos ramos fosse a outra, e a
        # matriz passaria a aceitar `true` onde escreve `1`.
        self.assertNotEqual(lint.normalizar(True), lint.normalizar(1))


class TestAchado(unittest.TestCase):
    def test_texto(self) -> None:
        achado = lint.Achado("codigo", "onde", "mensagem")
        self.assertEqual(str(achado), "codigo: onde: mensagem")


if __name__ == "__main__":
    unittest.main()
