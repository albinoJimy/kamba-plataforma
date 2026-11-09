"""A imagem do contentor condutor do ensaio (KAM-085).

Vive num ficheiro proprio porque o inventario do gate 11
(`ci/supply-chain/imagens.yaml`, `fontes_adicionais`) le **uma** constante por
ficheiro, e o `ensaio.py` ja la esta com a do PostgreSQL. O digest e o mesmo
que o inventario fixa para `python:3.12-slim-trixie`.
"""

IMAGEM = (
    "python:3.12-slim-trixie"
    "@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
)
