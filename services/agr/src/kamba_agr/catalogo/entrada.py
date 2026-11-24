"""As portas da foto que so existem depois do cofre e do gateway (KAM-231).

O catalogo da ToolLayer constroi-se **antes** do cofre e do cliente de LLM: o
registo de verticais confere-o no arranque, e e a mesma instancia que a camada
usa (`__main__.py`). Mas o STO precisa dos segredos do cofre, e a visao e a
porta de destinos precisam do gateway. Por isso as tres entram aqui por
**ligacao tardia**, como a `CredencialDoCom` e a `LigacaoVectorial`: o catalogo
recebe agora as portas desta `EntradaDaFoto`, e o arranque liga-as depois.

**Ate se ligarem, fecham**: o STO levanta `FotoPorLigarError` (o dono e
avisado), a visao nao tem fornecedores (o *gate* bloqueia com `sem_destino`)
e a porta de destinos nega tudo. Decisao do fundador de 2026-11-21 (P4,
opcao A): em `staging` e `prod` o arranque recusa sem o STO; em `dev` fica por
ligar, e diz-se no registo de arranque.
"""

from __future__ import annotations

from typing import Any, Final

from kamba_core.catalogo.pipeline import ErroDaVisao, ExtractorDeVisao, PortaDeDestinos, RespostaDaVisao
from kamba_core.storage.port import StorageProvider

from .fonte import FonteDoMed
from .montagem import CREDOR_DA_FOTO, FotoPorLigarError


#: Os segredos do STO que o AGR le (`ops/secrets-inventory.yaml`, KAM-231): o
#: `criar_storage_s3` pede-os ao cofre em cada pedido. Obrigatorios no arranque
#: em `staging` e `prod`.
SEGREDOS_DO_STO: Final = ("storage_access_key_id", "storage_secret_access_key")


class EntradaDaFoto:
    """O STO, a visao e a porta de destinos da foto, ligados no arranque."""

    def __init__(self) -> None:
        self._storage: StorageProvider | None = None
        self._visao: ExtractorDeVisao | None = None
        self._destinos: PortaDeDestinos | None = None
        self.storage: StorageProvider = _StorageTardio(self)  # type: ignore[assignment]
        self.visao: ExtractorDeVisao = _VisaoTardia(self)
        self.destinos: PortaDeDestinos = _DestinosTardios(self)

    def ligar(
        self,
        *,
        storage: StorageProvider | None,
        visao: ExtractorDeVisao | None,
        destinos: PortaDeDestinos | None,
    ) -> None:
        self._storage = storage
        self._visao = visao
        self._destinos = destinos

    def fonte_sobre(self, ligacao: Any) -> FonteDoMed:
        """A `FonteDoMed` de uma invocacao, sobre a ligacao dela e o STO daqui."""
        return FonteDoMed(ligacao=ligacao, storage=self.storage)


class _StorageTardio:
    def __init__(self, entrada: EntradaDaFoto) -> None:
        self._entrada = entrada

    def __getattr__(self, nome: str) -> Any:
        storage = self._entrada._storage
        if storage is None:
            raise FotoPorLigarError(f"o armazenamento da foto nao esta ligado (credor {CREDOR_DA_FOTO})")
        return getattr(storage, nome)


class _VisaoTardia:
    def __init__(self, entrada: EntradaDaFoto) -> None:
        self._entrada = entrada

    @property
    def fornecedores(self) -> tuple[str, ...]:
        visao = self._entrada._visao
        return () if visao is None else tuple(visao.fornecedores)

    def extrair(self, tenant_id: str, imagem: bytes, *, tecto_s: float | None = None) -> RespostaDaVisao:
        visao = self._entrada._visao
        if visao is None:
            raise ErroDaVisao(f"sem adaptador de visao (credor {CREDOR_DA_FOTO})")
        return visao.extrair(tenant_id, imagem, tecto_s=tecto_s)


class _DestinosTardios:
    def __init__(self, entrada: EntradaDaFoto) -> None:
        self._entrada = entrada

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        destinos = self._entrada._destinos
        if destinos is None:
            raise PermissionError("destino nao autorizado")
        destinos.autorizar(tenant_id, fornecedor, finalidade)


__all__ = ["EntradaDaFoto", "SEGREDOS_DO_STO"]
