"""O caminho de *release* do KAM-078: gates 14 a 18 do `specs/01` §4.

Um modulo por gate, e cada um com a decisao separada da execucao:

    lock.py        o `release.lock` (lista de *digests*), antes do deploy
    imagem.py      gate 14: *digest*, SBOM, `cosign verify` e criticas sem excepcao
    smoke.py       gate 15, a parte que nao depende do numero de teste real:
                   a guarda que aborta perante producao, e a classificacao
    aprovacao.py   gate 16: dois revisores para dinheiro, seguranca e isolamento
    rolling.py     gate 17: uma replica de cada vez, verificacao e reversao
                   automatica; e a reconciliacao de ids do ensaio sob carga
    tag.py         gate 18: SemVer so depois da verificacao pos-deploy verde
    pipeline.py    gate 18: `continue-on-error` num gate exige ADR ou aprovacao

**Nada disto esta ligado a um portao.** Ligar e alterar regra de bloqueio, e
isso e do fundador (`docs/runbooks/deploy-e-reversao.md` §6 tem a proposta).
Cada modulo fala com o mundo por uma porta injectavel — o executor do `cosign`,
a plataforma do *rolling*, o transporte do *smoke* —, pelo que os ensaios
correm sem registo de contentores, sem *host* e sem a Meta.
"""
