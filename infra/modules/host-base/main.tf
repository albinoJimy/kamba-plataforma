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
  })
}
