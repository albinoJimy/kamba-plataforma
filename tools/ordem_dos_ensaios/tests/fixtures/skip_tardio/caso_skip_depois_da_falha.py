"""A hipotese 3 por um caminho **publico** do `unittest`: um caso que falha e
cuja limpeza levanta `SkipTest`.

A *fixture* irma `tardio/` encena a forma que o Contexto do KAM-182 descreve —
um erro que chega depois de o caso terminar — e tem de a encenar escrevendo a
mao no `failures`, porque **por essa via nao ha discordancia nenhuma**: um erro
tardio entra pelo `addError`, que derruba o caso e o deixa vermelho no
`estado`. Esta e a forma **real**, e foi a revisao adversarial que a mediu: o
`addFailure` escreve `failure`, e a seguir o `addSkip` escreve `skip` por cima,
que esta no `VERDE`. O caso fica acusado no `TestResult` e verde no `Registo`,
sem nenhuma API privada.

E por isso que o texto da hipotese 3 diz **classificacao sobrescrita** e nao
«um `done_callback` ou uma *thread*»: o mecanismo que o bloco supoe nao produz
a discordancia, e o que a produz e uma escrita posterior. Com o texto antigo,
quem lesse isto era mandado procurar uma *thread* que nao existe.

O `addSkip` nao protege um vermelho, ao contrario do `addSubTest`. Isso e
materia de outro ticket — mexe no que o portao classifica —, e aqui fica
**medido** em vez de corrigido de passagem.

Como as irmas, chama-se `caso_*.py` para o `unittest discover` das suites de
`tools/` nao a apanhar.
"""

from __future__ import annotations

import unittest


class TestFalhaEDepoisSalta(unittest.TestCase):
    def test_falha_e_a_limpeza_salta(self) -> None:
        def salta() -> None:
            raise unittest.SkipTest('o recurso nao estava disponivel')

        self.addCleanup(salta)
        self.fail('vermelho real de proposito, apagado pelo skip da limpeza')
