"""Catalogo AI: foto -> rascunho de produto com perguntas de completude (KAM-049).

O pipeline das nove etapas do `docs/tecnica/03` §8.2 esta em `pipeline.py`; a
tabela e `platform.catalog_ingestions` (revisao `0052`). Ver a nota de cada
modulo: `estados` (a maquina), `exif` (os metadados em bytes), `imagem`
(qualidade e *phash*), `extraccao` (a resposta da visao e a proveniencia),
`normalizacao` (o lexico PT-AO do KAM-062), `screening` (a porta do KAM-088),
`completude` (perfis e perguntas), `repositorio` (a linha) e `indicadores`.
"""
