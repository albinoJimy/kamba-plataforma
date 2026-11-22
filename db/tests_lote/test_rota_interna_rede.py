"""A rota interna do guia nao escuta fora da rede `app` (KAM-239).

O custo que o fundador aceitou a 2026-11-22 e uma superficie HTTP num processo que
passa a RLS (o `onboarding-lote`, `kamba_batch`), e uma das quatro condicoes que o
tornam pequeno e que a rota **nao escute fora da rede `app`**. No compose de
`prod` o lote esta em duas redes (`app` e `data`), e um `listen` em `0.0.0.0`
escutava nas duas. A forma escolhida (decisao da coordenacao do lote 19) e ligar a
rota ao nome `onboarding-lote-interno`, que e um *alias* **so** da rede `app`.

So o Docker prova isto, e por isso o ensaio esta no gate 8, que ja o tem. Monta a
forma do compose em pequeno: duas redes `internal`, um contentor nas duas com o
*alias* so numa, e dentro dele a rota interna servida pela **mesma**
`servirRotaInterna` do `lote.ts` (`services/onboarding-web/tests/apoio/
servir_rota_interna.ts`). E mede de fora, com uma sonda em cada rede:

    pela rede app, pelo nome      401 — a rota esta la e pede a credencial
    pela rede data, pelo IP       a ligacao e recusada — nao ha nada a escutar

**E o controlo, que e o que faz disto um ensaio:** o mesmo servidor ligado a
`0.0.0.0` responde 401 pela rede `data`. Sem ele, um «recusada» podia vir de a
sonda nao chegar a rede nenhuma, e o ensaio passava pela razao errada.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
import time
import unittest

from tests_lote import node

ALIAS = "onboarding-lote-interno"
PORTA = 3015
CAMINHO = "/interno/guia/reservar"
#: O tecto do arranque do servidor de ensaio, em segundos. ***Proposta***: o Node
#: importa o `@kamba/core-ts` e o `hono`, e numa maquina carregada isso demora.
ARRANQUE_S = 180

SONDA = (
    "fetch(process.argv[1], {method: 'POST', signal: AbortSignal.timeout(8000)})"
    ".then(r => console.log('estado=' + r.status),"
    " e => console.log('erro=' + ((e.cause && e.cause.code) || e.name)))"
)


def _docker(*argumentos: str, verificar: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["docker", *argumentos], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
    )
    if verificar and r.returncode != 0:
        raise AssertionError(f"docker {' '.join(argumentos[:2])} falhou: {r.stderr[-400:]}")
    return r


def _volumes() -> list[str]:
    """A raiz em leitura, e os `node_modules` de outra raiz quando os ha (a forma do `node.py`)."""
    volumes = ["--volume", f"{node.RAIZ}:/repo:ro"]
    modulos = node._raiz_dos_modulos()
    if modulos != node.RAIZ:
        for relativo in node.MODULOS:
            volumes += ["--volume", f"{modulos / relativo}:/repo/{relativo}:ro"]
    return volumes


class TestRotaInternaSoNaRedeApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise AssertionError("sem docker no PATH: o ensaio de rede nao corre, e num gate saltar e falhar")
        sufixo = secrets.token_hex(4)
        cls.rede_app = f"kamba-ri-app-{sufixo}"
        cls.rede_data = f"kamba-ri-data-{sufixo}"
        cls.contentores: list[str] = []
        for rede in (cls.rede_app, cls.rede_data):
            _docker("network", "create", "--internal", rede)

    @classmethod
    def tearDownClass(cls) -> None:
        for nome in cls.contentores:
            _docker("rm", "-f", nome, verificar=False)
        for rede in (cls.rede_app, cls.rede_data):
            _docker("network", "rm", rede, verificar=False)

    def _servidor(self, anfitriao: str) -> str:
        """Levanta a rota nas duas redes, com o *alias* so na `app`, e devolve o IP na `data`."""
        nome = f"kamba-ri-{secrets.token_hex(4)}"
        self.contentores.append(nome)
        _docker(
            "create", "--name", nome,
            "--network", self.rede_app, "--network-alias", ALIAS,
            *_volumes(),
            "--workdir", "/repo/services/onboarding-web",
            "--env", f"LOTE_INTERNO_HOST={anfitriao}",
            "--env", f"LOTE_INTERNO_PORT={PORTA}",
            node.IMAGEM_NODE,
            "node", "tests/apoio/servir_rota_interna.ts",
        )
        _docker("network", "connect", self.rede_data, nome)
        _docker("start", nome)
        limite = time.monotonic() + ARRANQUE_S
        while "pronto" not in _docker("logs", nome, verificar=False).stdout:
            estado = _docker("inspect", "-f", "{{.State.Running}}", nome).stdout.strip()
            if estado != "true" or time.monotonic() > limite:
                registo = _docker("logs", nome, verificar=False)
                self.fail(f"o servidor de ensaio nao arrancou ({anfitriao}): {(registo.stdout + registo.stderr)[-600:]}")
            time.sleep(1)
        ip = _docker(
            "inspect", "-f", "{{(index .NetworkSettings.Networks \"" + self.rede_data + "\").IPAddress}}", nome
        ).stdout.strip()
        self.assertRegex(ip, r"^\d+\.\d+\.\d+\.\d+$", "o servidor tem um IP na rede data")
        return ip

    def _sondar(self, rede: str, url: str) -> str:
        r = _docker("run", "--rm", "--network", rede, node.IMAGEM_NODE, "node", "-e", SONDA, url)
        return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f"sem-saida: {r.stderr[-200:]}"

    def test_ligada_ao_alias_responde_pela_app_e_nao_pela_data(self) -> None:
        ip = self._servidor(ALIAS)
        self.assertEqual(self._sondar(self.rede_app, f"http://{ALIAS}:{PORTA}{CAMINHO}"), "estado=401")
        self.assertEqual(self._sondar(self.rede_data, f"http://{ip}:{PORTA}{CAMINHO}"), "erro=ECONNREFUSED")

    def test_o_controlo_ligado_a_todas_as_interfaces_responde_pela_data(self) -> None:
        ip = self._servidor("0.0.0.0")
        self.assertEqual(self._sondar(self.rede_data, f"http://{ip}:{PORTA}{CAMINHO}"), "estado=401")


if __name__ == "__main__":
    unittest.main()
