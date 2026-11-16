"""Foto de produtos AI (KAM-120): `ImageProvider`, `enhance_image` e `image_jobs`.

| Modulo | O que e |
|---|---|
| `fornecedor` | a interface `ImageProvider`, as quatro operacoes, a lista de recusa e o *tier* |
| `minimizacao` | o *gate* local: EXIF, tamanho, rostos e matriculas, antes de qualquer envio |
| `estados` | a maquina de `image_jobs.estado` e os motivos |
| `repositorio` | a persistencia de `platform.image_jobs` (revisao `foto_de_produtos`) |
| `servico` | o `enhance_image` e o trabalhador do pipeline assincrono |
| `bakeoff` | o *harness* do *bake-off* de fornecedores |

E uma biblioteca, pela razao do Catalogo AI (KAM-049): as dependencias que a
fazem — a porta de destinos do KAM-069, a limpeza de EXIF do KAM-049 e o STO do
KAM-011 — sao Python, e a ferramenta e invocada pelas verticais do dono
(`catalogo`, KAM-119; `social`, KAM-122), que sao quem a regista.
"""
