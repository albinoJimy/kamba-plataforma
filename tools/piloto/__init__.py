"""Instrumentos da medicao do Piloto: H1, H6, H8 e H9 (KAM-109).

Prepara a medicao e nao a faz. Seis coisas, e nenhuma decide uma hipotese:

    exportacao  le e valida a exportacao do Piloto, e congela-a com *hash*
    regras      as definicoes e os limiares pre-registados, como codigo
    sorteio     a amostra de produtos da auditoria de H8, com semente
    horas       o registo de horas do operador, validado
    relatorio   o relatorio semanal de modelo fixo, sem conteudo nem telefones
    cli         `python -m piloto`, que junta as cinco

**Os limiares e as definicoes sao *propostas*** do protocolo
`docs/tecnica/evidencia/validacao/Piloto_Protocolo.md`, que esta por assinar.
Mudar um numero aqui sem emenda ao protocolo avermelha o ensaio que os cruza.
O estado que sai de `medir` e uma proposta de leitura para o Registo de
Hipoteses; quem o escreve la e o fundador.
"""

from __future__ import annotations

__all__ = ["exportacao", "horas", "regras", "relatorio", "sorteio"]
