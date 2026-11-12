"""O corredor dos casos do *harness* de isolamento cruzado (KAM-066).

Os casos **declaram-se** em `tools/isolamento/baterias/` e executam-se aqui: e
este o unico sitio deste repositorio onde ha, ao mesmo tempo, um PostgreSQL
real, o pacote do AGR importavel e `node` ao alcance. Os tres sao o que os
casos pedem em `precisa`, e a dependencia e que escolhe a suite — nao a bateria.

```text
precisa="nada"      corre tambem no passo a seco (`python -m isolamento`)
precisa="agr"       o pacote do AGR: starlette, pydantic, yaml
precisa="postgres"  a base descartavel do gate 6
precisa="node"      o condutor de TypeScript (`tools/isolamento/condutor/`)
```

## Um teste por dependencia, e nao um por caso

Porque o que se quer na saida e a lista de achados junta, por camada, e nao
dezenas de linhas de `unittest` a repetir a mesma montagem. Cada teste corre o
seu grupo e falha com **todos** os achados dele: um caso de X-01 que falhe nao
esconde um de X-02.

## Saltar e falhar

O corredor nao salta: um caso cujo `precisa` nao esta satisfeito devolve um
achado que diz o que faltava. Aqui isso significa que, se o `node` nao estiver
ao alcance, o teste de `node` **falha** — e e o que se quer num *gate*. A mesma
regra que `db/correr_suite.py` aplica a suite inteira.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import ligacao
from tests_isolamento.base import ComDoisTenants, definir_contexto

RAIZ = Path(__file__).resolve().parents[2]
for _relativo in ("tools", "services/agr/src", "libs/py-core/src"):
    _caminho = str(RAIZ / _relativo)
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

from isolamento import corredor, semente  # noqa: E402
from isolamento.contexto import Contexto  # noqa: E402
from isolamento.oraculo import Oraculo  # noqa: E402


def _parametros_de_node() -> dict:
    """Como e que o condutor de TypeScript liga a base do *gate*.

    Construidos aqui e nao em `db/ligacao.py`: esse ficheiro e de outro ticket
    e a sua API nao tem forma de JSON. O papel e `kamba_app` — o mesmo com que
    os servicos correm, e o unico contra o qual a RLS e a ultima barreira.

    Quando o `node` corre **noutro contentor** (sem `node` no anfitriao), o
    anfitriao da base nao e `127.0.0.1`: e o nome do contentor, que o
    `KAMBA_GATE_CONTENTOR` nomeia e que a ponte usa para escolher a rede. O
    `host` daqui e o do ponto de vista de quem liga, e a ponte substitui-o
    quando precisa.
    """
    destino = ligacao.alvo()
    utilizador, senha = ligacao.credenciais("app")
    return {
        "host": destino.host,
        "port": destino.porta,
        "user": utilizador,
        "password": senha,
        "database": destino.base,
    }


def _agr_importavel() -> bool:
    """O pacote do AGR esta no caminho e as dependencias dele existem?

    Nao se assume: o *venv* do `make bootstrap` instala as tres listas
    (`tools`, `migrations`, `agr/runtime`), mas quem corra esta suite a mao com
    outro interpretador pode nao ter o `starlette`. A resposta entra no
    contexto, e um caso que precise do AGR sem ele **falha** — nao e saltado.
    """
    try:
        import kamba_agr.api_interna  # noqa: F401, PLC0415
        import kamba_agr.tls.catalogo  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


class ComHarness(ComDoisTenants):
    """Os dois tenants da suite, mais os dois contactos do KAM-066."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        administrador = cls._cursores["admin"]
        cls.par = semente.semear_contactos(administrador, cls.a.id)
        # As duas condicoes de que o passo 2 do pipeline depende, e que a
        # primeira execucao mostrou em falta: o tenant tem de estar `ativo` e o
        # modulo da vertical tem de estar ligado. A razao por extenso esta em
        # `semente.activar_tenant` e em `semente.semear_entitlement` — sem elas
        # **nenhuma** tool responde, e o X-02 fica verde sem medir nada.
        semente.activar_tenant(administrador, cls.a.id)
        semente.semear_entitlement(administrador, cls.a.id)
        # **E o B tambem activo** (KAM-061). Com o B no `onboarding` da
        # omissao, a porta `tn` do `idx.candidatos` lia zero tenants para
        # qualquer `p_tenant = B`, e o X-06 ficava verde sem medir RLS
        # nenhuma — o «vector a distancia zero do de B» nao era hostil.
        # Achado 1 da revisao adversarial do KAM-061.
        semente.activar_tenant(administrador, cls.b.id)
        # A oferta viva do documento de indice de A, publicada e com o `sku`
        # igual ao `product_ref` semeado: sem ela, o `search_catalog` do X-02
        # (KAM-061) nunca tinha o que devolver a A, e a sonda positiva ficava
        # sem objecto. **Aqui e nao na receita**: a receita semeia uma linha por
        # tabela e por tenant, e o `TestReutilizacaoDeLigacao` exige-o — uma
        # segunda linha na `offer_terms` deixou-o vermelho, medido. Apaga-se com
        # a `offer_terms` do tenant no `apagar_tenant`.
        canario_do_indice = cls.a.canarios[("idx", "search_doc")]
        administrador.execute(
            "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, estado) "
            "VALUES (%s, %s, %s, 'sob_consulta', 'publicado')",
            (cls.a.id, canario_do_indice, f"produto {canario_do_indice}"),
        )
        # As marcas de consumo com os `consumer` **reais** (`agr_vendedor`,
        # `agr_servicos`), nos dois tenants. Sem elas a bateria dos
        # consumidores EVT contava zero por ausencia e nao por isolamento: a
        # receita da suite da base escreve `consumer = 'ensaio-iso'`. Achado 4
        # da revisao adversarial.
        for tenant, rotulo in ((cls.a, "a"), (cls.b, "b")):
            semente.semear_marcas_de_consumo(administrador, tenant.id, rotulo)

    @classmethod
    def tearDownClass(cls) -> None:
        # **Antes** do `apagar_tenant` do `super`: as linhas das tres tabelas
        # apontam para contactos que ele apaga.
        semente.apagar_contactos(cls._cursores["admin"], cls.par)
        semente.retirar_entitlement(cls._cursores["admin"], cls.a.id)
        for tenant in (cls.a, cls.b):
            semente.apagar_marcas_de_consumo(cls._cursores["admin"], tenant.id)
        super().tearDownClass()

    def _cursor_partilhado(self, papel: str, tenant_id: str | None = None):
        """Cursor do papel e contexto pedidos, **numa ligacao por par**.

        O `cursor_de` da base abre uma ligacao nova por chamada e so a fecha no
        fim do teste — e o corredor corre o X-03, o X-04 e o X-05 **no mesmo
        teste**, com uma chamada por tabela isolada em cada um. Com mais tabelas
        isoladas a soma passou as 100 ligacoes do servidor, e o X-04 e o X-05
        rebentaram com `53300` («remaining connection slots are reserved»),
        medido: um vermelho que nao era de isolamento e crescia com cada tabela
        nova.

        **Portado do KAM-061** (`feature/KAM-061-idx-candidatos`, commits
        `ac0bb43f` e `7c901207`), sem as baterias dele: o KAM-087 bateu no mesmo
        numero com as duas tabelas da `0043`. O trecho e identico, e quem fundir
        em segundo fica com um so.

        Aqui a ligacao e por `(papel, tenant)`, e cada reuso **desfaz** a
        transaccao anterior antes de voltar a pôr o contexto: cada chamada ve o
        mesmo que uma ligacao nova veria, porque o contexto e local a
        transaccao (`set_config(..., true)`) e os casos que usam esta porta so
        leem.
        """
        chave = (papel, tenant_id)
        conexao = self._partilhadas.get(chave)
        if conexao is None:
            conexao = self._partilhadas[chave] = self.ligar(papel)
        else:
            conexao.rollback()
        cursor = conexao.cursor()
        if tenant_id is not None:
            definir_contexto(cursor, tenant_id)
        return cursor

    def contexto(self) -> Contexto:
        """O `Contexto` que os casos recebem, com as portas desta suite."""
        self._partilhadas: dict[tuple[str, str | None], object] = {}
        oraculo = Oraculo(
            {
                f"{schema}.{tabela}": self.b.guardado((schema, tabela))
                for schema, tabela, _, _ in self.por_tabela()
            }
            | {"tenant_id": self.b.id}
        )
        return Contexto(
            raiz=RAIZ,
            a=self.a,
            b=self.b,
            x=self.par.x,
            y=self.par.y,
            oraculo=oraculo,
            oraculo_de_y=Oraculo(
                {
                    f"{schema}.{tabela}": canario
                    for (schema, tabela), canario in self.par.y.canarios.items()
                }
            ),
            cursor_de=self._cursor_partilhado,
            cursores=self._cursores,
            tabelas=self.por_tabela(),
            agr=_agr_importavel(),
            ligar=lambda papel: ligacao.ligar(papel),
            abrir_ligacao=lambda: ligacao.ligar("app"),
            node=self._condutor(),
        )

    def _condutor(self):  # noqa: ANN202
        """O condutor de TypeScript, ou `None` se o pacote dele nao existir.

        `None` nao e um salto: o corredor transforma-o num achado, porque um
        caso de X-01 sobre rotas de TypeScript que nao corre e uma rota sem
        caso com outro nome.
        """
        try:
            from isolamento.condutor import ponte  # noqa: PLC0415
        except ImportError:
            return None

        contactos = {
            rotulo: {
                "id": contacto.id,
                "canarios": {
                    f"{schema}.{tabela}": canario
                    for (schema, tabela), canario in contacto.canarios.items()
                },
            }
            for rotulo, contacto in (("x", self.par.x), ("y", self.par.y))
        }
        canarios = {
            f"{schema}.{tabela}": str(self.b.canarios[(schema, tabela)])
            for schema, tabela, _, _ in self.por_tabela()
        }

        def correr(grupo: str):  # noqa: ANN202
            return ponte.correr(
                grupo,
                canarios=canarios,
                tenant_a=self.a.id,
                tenant_b=self.b.id,
                pg=_parametros_de_node(),
                contactos=contactos,
                raiz=RAIZ,
            )

        return correr

    def exigir(self, precisa: set[str]) -> None:
        resultado = corredor.correr(self.contexto(), precisa=precisa)
        if resultado.achados:
            self.fail(
                f"{len(resultado.achados)} achado(s) de isolamento em "
                f"{sorted(precisa)}:\n  - " + "\n  - ".join(resultado.achados)
            )
        self.assertTrue(
            resultado.corridos,
            f"nenhum caso de {sorted(precisa)} correu. Num gate, zero casos "
            "corridos e o mesmo que zero casos escritos.",
        )


class TestCasosDaBase(ComHarness):
    """X-03, X-04, X-05, C-01/base, P-01 e os consumidores EVT."""

    def test_os_casos_que_precisam_da_base(self) -> None:
        self.exigir({"postgres"})


class TestCasosDoAgr(ComHarness):
    """X-01 das rotas do AGR e X-02 das dez tools `declaradas`."""

    def test_os_casos_que_precisam_do_agr(self) -> None:
        self.exigir({"agr"})


class TestCasosDeNode(ComHarness):
    """X-01 das dezassete rotas de TypeScript, e as tres leituras do contacto.

    As aplicacoes Hono respondem **em processo**, pelo `app.request()` — e a
    forma que os testes do GWY ja usam —, pelo que nao se levanta servidor
    nenhum. O condutor corre com o `node` do `PATH` quando ele existe (e no
    *runner* existe: o `make bootstrap` instala-o e constroi os pacotes) e, sem
    ele, na imagem fixada por digest, na rede do contentor da base — o mesmo
    padrao que `db/tests_identidade/node.py` ja usa.
    """

    def test_os_casos_que_precisam_de_node(self) -> None:
        self.exigir({"node"})


class TestCasosSemDependencias(ComHarness):
    """Os dois casos de filas. Correm tambem no passo a seco, de proposito.

    Correr duas vezes nao e desperdicio: o passo a seco corre **antes** de a
    base subir, e e o que faz com que um PR que mexa num contrato de fila falhe
    em segundos em vez de em minutos. Aqui correm outra vez porque um caso que
    so corre num sitio deixa de correr no dia em que esse sitio mudar.
    """

    def test_os_casos_sem_dependencias(self) -> None:
        self.exigir({"nada"})


if __name__ == "__main__":
    unittest.main()
