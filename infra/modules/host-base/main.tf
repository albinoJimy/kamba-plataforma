# infra/modules/host-base — produz o documento cloud-init. Nada mais.
#
# Nao ha `resource` nem `provider` aqui, e nao e por falta de maturidade: e a
# regra do criterio 6 (ver `../README.md`). Este modulo devolve TEXTO; quem o
# entrega a um host e o modulo de fornecedor, que e o unico que sabe como.

locals {
  cloud_init = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ambiente                        = var.ambiente
    utilizador                      = var.utilizador
    chaves_ssh_de_administracao     = var.chaves_ssh_de_administracao
    ponto_de_montagem_nvme          = var.ponto_de_montagem_nvme
    etiqueta_do_disco_nvme          = var.etiqueta_do_disco_nvme
    porta_wireguard                 = var.porta_wireguard
    referencia_do_segredo_wireguard = var.referencia_do_segredo_wireguard
    # KAM-259: o acesso de excepcao auditado.
    chaves_ssh_de_breakglass         = var.chaves_ssh_de_breakglass
    referencia_do_segredo_breakglass = var.referencia_do_segredo_breakglass
    programa_breakglass_b64          = filebase64("${path.module}/kamba_breakglass.py")
    contentor_da_base                = coalesce(var.contentor_da_base, "kamba-${var.ambiente}-postgres-1")
    base_da_plataforma               = var.base_da_plataforma
  })
}
