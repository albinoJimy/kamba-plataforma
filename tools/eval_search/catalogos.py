"""Os cinco catalogos sinteticos do `golden_search` (KAM-064), versao 1.

**Tudo aqui e inventado**: produtos, marcas, precos. Nenhuma linha vem de um
catalogo real de uma PME, de uma conversa nem de um contacto (ADR-018; a origem
esta registada no bloco do KAM-064 e no cabecalho de cada ficheiro do
*dataset*). As marcas sao nomes de lugar, de planta ou de animal, escolhidos
para nao serem nomes de pessoa — o *scanner* do `dataset` procura nomes
proprios e recusava-os.

Cada produto e `(sku, nome, preco_kz, tipo, atributos)`. O `sku` e o
`product_ref` (a `v_oferta_viva` da `0037` diz que o `product_ref` **e** o
`sku`). O `tipo` e os `atributos` sao da anotacao e nunca entram na base: a
pesquisa so ve o `nome` e o preco. O preco vai a base em unidade menor
(`preco_kz * 100`, dicionario §2).

Os nomes sao os que uma loja de Luanda escreveria numa lista de precos, com a
grafia padrao: os regionalismos («geleira», «gasosa», «ginguba») ficam do lado
das consultas, que e onde o lexico PT-AO do KAM-062 tem de os resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Produto:
    sku: str
    nome: str
    preco_kz: int
    tipo: str
    atributos: frozenset[str]

    @property
    def preco_minor(self) -> int:
        return self.preco_kz * 100


def _p(sku: str, nome: str, preco_kz: int, tipo: str, *atributos: str) -> Produto:
    return Produto(sku, nome, preco_kz, tipo, frozenset(atributos))


#: A versao dos catalogos. Muda quando um produto muda, e com ela o nome dos
#: ficheiros do *dataset* (um ficheiro por *snapshot*, criterio 1).
VERSAO: Final = "v1"

MERCEARIA: Final = (
    _p("arroz-agulha-5kg", "Arroz agulha Kianda 5 kg", 4500, "arroz", "agulha", "5kg", "kianda"),
    _p("arroz-agulha-1kg", "Arroz agulha Kianda 1 kg", 1100, "arroz", "agulha", "1kg", "kianda"),
    _p("arroz-carolino-1kg", "Arroz carolino Mulemba 1 kg", 1250, "arroz", "carolino", "1kg", "mulemba"),
    _p("arroz-basmati-1kg", "Arroz basmati Imbondeiro 1 kg", 2300, "arroz", "basmati", "1kg", "imbondeiro"),
    _p("feijao-manteiga-1kg", "Feijão manteiga 1 kg", 1600, "feijao", "manteiga", "1kg"),
    _p("feijao-catarino-1kg", "Feijão catarino 1 kg", 1500, "feijao", "catarino", "1kg"),
    _p("feijao-preto-1kg", "Feijão preto 1 kg", 1700, "feijao", "preto", "1kg"),
    _p("oleo-soja-1l", "Óleo de soja Palanca 1 L", 1900, "oleo", "soja", "1l", "palanca"),
    _p("oleo-girassol-1l", "Óleo de girassol Palanca 1 L", 2400, "oleo", "girassol", "1l", "palanca"),
    _p("oleo-soja-5l", "Óleo de soja Palanca 5 L", 8900, "oleo", "soja", "5l", "palanca"),
    _p("oleo-palma-1l", "Óleo de palma 1 L", 1800, "oleo_palma", "palma", "1l"),
    _p("acucar-branco-1kg", "Açúcar branco 1 kg", 950, "acucar", "branco", "1kg"),
    _p("acucar-amarelo-1kg", "Açúcar amarelo 1 kg", 1050, "acucar", "amarelo", "1kg"),
    _p("fuba-milho-1kg", "Fuba de milho 1 kg", 700, "fuba", "milho", "1kg"),
    _p("fuba-milho-5kg", "Fuba de milho 5 kg", 3200, "fuba", "milho", "5kg"),
    _p("fuba-bombo-1kg", "Fuba de bombó 1 kg", 900, "fuba", "bombo", "1kg"),
    _p("esparguete-500g", "Esparguete Mussulo 500 g", 650, "massa", "esparguete", "500g", "mussulo"),
    _p("macarrao-500g", "Macarrão Mussulo 500 g", 600, "massa", "macarrao", "500g", "mussulo"),
    _p("cotovelos-500g", "Massa cotovelos Mussulo 500 g", 620, "massa", "cotovelos", "500g", "mussulo"),
    _p("leite-po-400g", "Leite em pó Cabinda 400 g", 3500, "leite", "po", "400g", "cabinda"),
    _p("leite-uht-1l", "Leite UHT meio gordo 1 L", 1200, "leite", "uht", "1l", "meio_gordo"),
    _p("leite-condensado", "Leite condensado 397 g", 1400, "leite_condensado", "condensado"),
    _p("sumo-manga-1l", "Sumo de manga Tundavala 1 L", 1300, "sumo", "manga", "1l", "tundavala"),
    _p("sumo-laranja-1l", "Sumo de laranja Tundavala 1 L", 1300, "sumo", "laranja", "1l", "tundavala"),
    _p("sumo-maracuja-1l", "Sumo de maracujá Tundavala 1 L", 1350, "sumo", "maracuja", "1l", "tundavala"),
    _p("refrigerante-cola-2l", "Refrigerante de cola Kalandula 2 L", 1100, "refrigerante", "cola", "2l", "kalandula"),
    _p("refrigerante-laranja-33cl", "Refrigerante de laranja Kalandula lata 33 cl", 350, "refrigerante", "laranja", "lata", "kalandula"),
    _p("refrigerante-ananas-33cl", "Refrigerante de ananás Kalandula lata 33 cl", 350, "refrigerante", "ananas", "lata", "kalandula"),
    _p("agua-1-5l", "Água mineral Serra da Leba 1,5 L", 300, "agua", "1.5l"),
    _p("agua-5l", "Água mineral Serra da Leba 5 L", 800, "agua", "5l"),
    _p("sal-1kg", "Sal fino 1 kg", 400, "sal", "fino"),
    _p("farinha-trigo-1kg", "Farinha de trigo 1 kg", 900, "farinha", "trigo", "1kg"),
    _p("sardinha-lata", "Sardinha em óleo lata 125 g", 550, "sardinha", "lata", "oleo"),
    _p("sardinha-tomate-lata", "Sardinha em molho de tomate lata 125 g", 560, "sardinha", "lata", "tomate"),
    _p("atum-lata", "Atum em óleo lata 120 g", 900, "atum", "lata"),
    _p("bacalhau-seco-1kg", "Bacalhau seco salgado 1 kg", 7500, "bacalhau", "seco", "1kg"),
    _p("peixe-seco-carapau", "Carapau seco 500 g", 2500, "peixe_seco", "carapau"),
    _p("cafe-moido-250g", "Café moído Amboim 250 g", 1800, "cafe", "moido", "250g", "amboim"),
    _p("cafe-soluvel-100g", "Café solúvel Amboim 100 g", 2200, "cafe", "soluvel", "amboim"),
    _p("cha-preto-25", "Chá preto 25 saquetas", 700, "cha", "preto"),
    _p("amendoim-torrado-500g", "Amendoim torrado 500 g", 1100, "amendoim", "torrado"),
    _p("molho-piri-piri", "Molho de piri-piri 150 ml", 600, "piri_piri", "molho"),
    _p("margarina-500g", "Margarina 500 g", 1300, "margarina", "500g"),
    _p("sabao-barra", "Sabão azul em barra 400 g", 450, "sabao", "barra", "azul"),
    _p("sabao-po-1kg", "Detergente em pó para roupa 1 kg", 1500, "sabao", "po", "roupa"),
    _p("detergente-loica", "Detergente da loiça limão 750 ml", 850, "detergente_loica", "limao"),
    _p("papel-higienico-4", "Papel higiénico 4 rolos", 900, "papel_higienico", "4rolos"),
    _p("ovos-30", "Ovos tabuleiro de 30", 3900, "ovos", "30"),
    _p("tomate-pelado-lata", "Tomate pelado lata 400 g", 700, "tomate_lata", "lata"),
    _p("maionese-450g", "Maionese 450 g", 1500, "maionese", "450g"),
)

ELECTRO: Final = (
    _p("frigorifico-250l", "Frigorífico Welwitschia 250 L duas portas", 285000, "frigorifico", "250l", "duas_portas", "welwitschia"),
    _p("frigorifico-350l", "Frigorífico Welwitschia 350 L duas portas inox", 395000, "frigorifico", "350l", "duas_portas", "inox", "welwitschia"),
    _p("frigorifico-combinado", "Frigorífico combinado Cuanza 300 L", 420000, "frigorifico", "300l", "combinado", "cuanza"),
    _p("frigorifico-minibar", "Frigorífico minibar 90 L", 120000, "frigorifico", "90l", "minibar"),
    _p("arca-200l", "Arca congeladora Cuanza 200 L", 230000, "arca", "200l", "cuanza"),
    _p("arca-300l", "Arca congeladora Cuanza 300 L", 310000, "arca", "300l", "cuanza"),
    _p("fogao-4-bocas", "Fogão a gás 4 bocas com forno", 185000, "fogao", "gas", "4bocas", "forno"),
    _p("fogao-2-bocas", "Fogão a gás de mesa 2 bocas", 35000, "fogao", "gas", "2bocas"),
    _p("fogao-eletrico", "Placa eléctrica 2 discos", 42000, "fogao", "electrico", "2discos"),
    _p("micro-ondas-20l", "Micro-ondas 20 L", 68000, "micro_ondas", "20l"),
    _p("micro-ondas-grill", "Micro-ondas com grill 25 L", 89000, "micro_ondas", "25l", "grill"),
    _p("ventoinha-pe", "Ventoinha de pé 16 polegadas", 38000, "ventoinha", "pe"),
    _p("ventoinha-mesa", "Ventoinha de mesa 12 polegadas", 24000, "ventoinha", "mesa"),
    _p("ventoinha-tecto", "Ventoinha de tecto com candeeiro", 55000, "ventoinha", "tecto"),
    _p("ar-condicionado-9000", "Ar condicionado split 9000 BTU", 260000, "ar_condicionado", "9000btu", "split"),
    _p("ar-condicionado-12000", "Ar condicionado split 12000 BTU inverter", 340000, "ar_condicionado", "12000btu", "split", "inverter"),
    _p("televisor-32", "Televisor LED Mukuba 32 polegadas", 145000, "televisor", "32", "led", "mukuba"),
    _p("televisor-43", "Televisor smart Mukuba 43 polegadas", 235000, "televisor", "43", "smart", "mukuba"),
    _p("televisor-55", "Televisor smart 4K Mukuba 55 polegadas", 410000, "televisor", "55", "smart", "4k", "mukuba"),
    _p("telemovel-a10", "Telemóvel Kissama A10 64 GB", 95000, "telemovel", "64gb", "kissama"),
    _p("telemovel-a20", "Telemóvel Kissama A20 128 GB", 145000, "telemovel", "128gb", "kissama"),
    _p("telemovel-basico", "Telemóvel básico com lanterna dual SIM", 18000, "telemovel", "basico", "dual_sim"),
    _p("telemovel-x5", "Telemóvel Chimpanzé X5 256 GB", 380000, "telemovel", "256gb", "chimpanze"),
    _p("carregador-usbc", "Carregador rápido USB-C 25 W", 9500, "carregador", "usbc"),
    _p("carregador-micro", "Carregador micro USB", 4500, "carregador", "micro_usb"),
    _p("powerbank-20000", "Powerbank 20000 mAh", 22000, "powerbank", "20000mah"),
    _p("auscultadores-bt", "Auscultadores bluetooth sem fios", 18500, "auscultadores", "bluetooth"),
    _p("auriculares-fio", "Auriculares com fio", 3500, "auscultadores", "fio"),
    _p("gerador-2-5kva", "Gerador a gasolina 2,5 kVA", 290000, "gerador", "gasolina", "2.5kva"),
    _p("gerador-5kva", "Gerador a gasóleo 5 kVA", 680000, "gerador", "gasoleo", "5kva"),
    _p("estabilizador-1000", "Estabilizador de corrente 1000 VA", 35000, "estabilizador", "1000va"),
    _p("ferro-engomar", "Ferro de engomar a vapor", 19500, "ferro", "vapor"),
    _p("liquidificadora", "Liquidificadora 1,5 L", 32000, "liquidificadora", "1.5l"),
    _p("batedeira", "Batedeira de mão 5 velocidades", 21000, "batedeira", "mao"),
    _p("chaleira-eletrica", "Chaleira eléctrica 1,7 L inox", 16500, "chaleira", "electrica", "inox"),
    _p("maquina-lavar-7kg", "Máquina de lavar roupa 7 kg", 330000, "maquina_lavar", "7kg", "roupa"),
    _p("maquina-lavar-semi", "Máquina de lavar semiautomática 2 tinas", 145000, "maquina_lavar", "semiautomatica"),
    _p("coluna-bt", "Coluna bluetooth portátil", 27000, "coluna", "bluetooth", "portatil"),
    _p("extensao-4", "Extensão eléctrica 4 tomadas 3 m", 6500, "extensao", "4tomadas"),
    _p("lampada-led-9w", "Lâmpada LED 9 W rosca larga", 1200, "lampada", "led", "9w"),
    _p("lampada-recarregavel", "Lâmpada recarregável de emergência", 7500, "lampada", "recarregavel"),
    _p("candeeiro-solar", "Candeeiro solar com painel", 25000, "candeeiro_solar", "solar"),
)

CONSTRUCAO: Final = (
    _p("cimento-50kg", "Cimento Portland 42,5 saco 50 kg", 6800, "cimento", "50kg", "portland"),
    _p("cimento-cola-25kg", "Cimento-cola para azulejo 25 kg", 5200, "cimento_cola", "25kg"),
    _p("chapa-zinco-2m", "Chapa de zinco ondulada 2 m", 7900, "chapa", "zinco", "2m"),
    _p("chapa-zinco-3m", "Chapa de zinco ondulada 3 m", 11500, "chapa", "zinco", "3m"),
    _p("chapa-lusalite", "Chapa de fibrocimento 2,5 m", 9800, "chapa", "fibrocimento"),
    _p("bloco-15", "Bloco de cimento 15 cm", 280, "bloco", "15cm"),
    _p("bloco-20", "Bloco de cimento 20 cm", 340, "bloco", "20cm"),
    _p("tijolo-ceramico", "Tijolo cerâmico furado", 220, "tijolo", "ceramico"),
    _p("varao-8mm", "Varão de ferro nervurado 8 mm 12 m", 3900, "varao", "8mm"),
    _p("varao-12mm", "Varão de ferro nervurado 12 mm 12 m", 8200, "varao", "12mm"),
    _p("areia-m3", "Areia lavada por metro cúbico", 18000, "areia", "lavada"),
    _p("brita-m3", "Brita por metro cúbico", 24000, "brita", "m3"),
    _p("tinta-branca-20l", "Tinta plástica branca 20 L", 38000, "tinta", "plastica", "branca", "20l"),
    _p("tinta-branca-5l", "Tinta plástica branca 5 L", 11500, "tinta", "plastica", "branca", "5l"),
    _p("tinta-esmalte-azul", "Tinta de esmalte azul 1 L", 6200, "tinta", "esmalte", "azul", "1l"),
    _p("impermeabilizante", "Impermeabilizante de terraço 5 L", 21000, "impermeabilizante", "5l"),
    _p("pincel-2", "Pincel 2 polegadas", 900, "pincel", "2pol"),
    _p("rolo-pintura", "Rolo de pintura 23 cm com tabuleiro", 3800, "rolo", "23cm"),
    _p("torneira-cozinha", "Torneira de cozinha monocomando", 14500, "torneira", "cozinha", "monocomando"),
    _p("torneira-jardim", "Torneira de jardim em latão", 3200, "torneira", "jardim"),
    _p("tubo-pvc-50", "Tubo PVC esgoto 50 mm 3 m", 4100, "tubo", "pvc", "50mm"),
    _p("tubo-pvc-110", "Tubo PVC esgoto 110 mm 3 m", 9300, "tubo", "pvc", "110mm"),
    _p("tubo-ppr-20", "Tubo PPR água 20 mm 4 m", 2900, "tubo", "ppr", "20mm"),
    _p("autoclismo", "Autoclismo de plástico", 12500, "autoclismo", "plastico"),
    _p("sanita", "Sanita com tampo branca", 45000, "sanita", "branca"),
    _p("lavatorio", "Lavatório de coluna branco", 32000, "lavatorio", "coluna"),
    _p("azulejo-20x30", "Azulejo branco 20x30 caixa de 1,5 m²", 9500, "azulejo", "branco"),
    _p("mosaico-45", "Mosaico cerâmico 45x45 bege", 11800, "mosaico", "bege"),
    _p("prego-3", "Pregos 3 polegadas 1 kg", 1500, "prego", "3pol"),
    _p("prego-zinco", "Pregos para zinco com anilha 1 kg", 2100, "prego", "zinco"),
    _p("parafuso-madeira", "Parafusos para madeira caixa de 100", 1800, "parafuso", "madeira"),
    _p("bucha-8", "Buchas 8 mm saco de 50", 900, "bucha", "8mm"),
    _p("martelo", "Martelo de carpinteiro", 4500, "martelo", "carpinteiro"),
    _p("serrote", "Serrote 20 polegadas", 5200, "serrote", "20pol"),
    _p("berbequim", "Berbequim de percussão 650 W", 39000, "berbequim", "percussao"),
    _p("fechadura-porta", "Fechadura de porta interior", 7800, "fechadura", "interior"),
    _p("cadeado-50", "Cadeado de latão 50 mm", 3600, "cadeado", "50mm"),
    _p("dobradica", "Dobradiça de porta 3 polegadas", 650, "dobradica", "3pol"),
    _p("fio-2-5", "Fio eléctrico 2,5 mm rolo 100 m", 29000, "fio", "2.5mm"),
    _p("fio-1-5", "Fio eléctrico 1,5 mm rolo 100 m", 19000, "fio", "1.5mm"),
    _p("disjuntor-16a", "Disjuntor 16 A", 2400, "disjuntor", "16a"),
    _p("tomada-dupla", "Tomada dupla de parede", 1900, "tomada", "dupla"),
    _p("carrinho-mao", "Carrinho de mão 65 L", 32000, "carrinho_mao", "65l"),
    _p("pa-quadrada", "Pá quadrada com cabo", 4200, "pa", "quadrada"),
)

MODA: Final = (
    _p("camisola-algodao-branca", "Camisola de algodão branca", 3500, "camisola", "algodao", "branca"),
    _p("camisola-algodao-preta", "Camisola de algodão preta", 3500, "camisola", "algodao", "preta"),
    _p("camisola-estampada", "Camisola estampada Benguela", 4800, "camisola", "estampada", "benguela"),
    _p("camisa-social-branca", "Camisa social branca manga comprida", 9500, "camisa", "social", "branca", "manga_comprida"),
    _p("camisa-xadrez", "Camisa xadrez manga curta", 7200, "camisa", "xadrez", "manga_curta"),
    _p("camisa-africana", "Camisa de tecido africano", 12500, "camisa", "africana"),
    _p("calcas-ganga-azul", "Calças de ganga azul", 14000, "calcas", "ganga", "azul"),
    _p("calcas-ganga-preta", "Calças de ganga preta", 14000, "calcas", "ganga", "preta"),
    _p("calcas-sarja", "Calças de sarja bege", 12000, "calcas", "sarja", "bege"),
    _p("calcao-ganga", "Calção de ganga", 8500, "calcao", "ganga"),
    _p("calcao-praia", "Calção de praia estampado", 6500, "calcao", "praia"),
    _p("vestido-curto", "Vestido curto floral", 13500, "vestido", "curto", "floral"),
    _p("vestido-comprido", "Vestido comprido de tecido africano", 22000, "vestido", "comprido", "africano"),
    _p("vestido-festa", "Vestido de festa vermelho", 28000, "vestido", "festa", "vermelho"),
    _p("saia-comprida", "Saia comprida plissada", 9800, "saia", "comprida"),
    _p("saia-ganga", "Saia de ganga curta", 8800, "saia", "ganga", "curta"),
    _p("pano-africano-6j", "Pano africano estampado 6 jardas", 15000, "pano", "africano", "6jardas"),
    _p("pano-africano-3j", "Pano africano estampado 3 jardas", 8000, "pano", "africano", "3jardas"),
    _p("lenco-cabeca", "Lenço de cabeça estampado", 2500, "lenco", "cabeca"),
    _p("sapatilhas-brancas", "Sapatilhas desportivas brancas Ombaka", 24000, "sapatilhas", "brancas", "desportivas", "ombaka"),
    _p("sapatilhas-pretas", "Sapatilhas de corrida pretas Ombaka", 27000, "sapatilhas", "pretas", "corrida", "ombaka"),
    _p("sapatilhas-crianca", "Sapatilhas de criança com luzes", 12000, "sapatilhas", "crianca"),
    _p("sandalia-mulher", "Sandálias de mulher em pele", 11000, "sandalia", "mulher", "pele"),
    _p("sandalia-homem", "Sandálias de homem", 9500, "sandalia", "homem"),
    _p("chinelos-borracha", "Chinelos de borracha", 1800, "chinelos", "borracha"),
    _p("chinelos-quarto", "Chinelos de quarto", 3200, "chinelos", "quarto"),
    _p("sapato-social-preto", "Sapato social preto em pele", 26000, "sapato", "social", "preto", "pele"),
    _p("sapato-salto", "Sapato de salto alto nude", 21000, "sapato", "salto"),
    _p("bota-trabalho", "Bota de trabalho com biqueira de aço", 23000, "bota", "trabalho"),
    _p("bolsa-mao", "Bolsa de mão preta", 16000, "bolsa", "mao", "preta"),
    _p("bolsa-tiracolo", "Bolsa a tiracolo castanha", 13500, "bolsa", "tiracolo", "castanha"),
    _p("mochila-escolar", "Mochila escolar", 9000, "mochila", "escolar"),
    _p("cinto-pele", "Cinto de pele castanho", 5500, "cinto", "pele"),
    _p("bone", "Boné de pala bordado", 3800, "bone", "pala"),
    _p("meias-3", "Meias desportivas pack de 3", 2400, "meias", "desportivas"),
    _p("fato-treino", "Fato de treino azul-marinho", 19000, "fato_treino", "azul_marinho"),
    _p("casaco-ganga", "Casaco de ganga", 18500, "casaco", "ganga"),
    _p("uniforme-escolar", "Bata escolar branca", 4500, "bata", "escolar", "branca"),
    _p("pijama", "Pijama de algodão", 8200, "pijama", "algodao"),
    _p("relogio-pulso", "Relógio de pulso analógico", 15500, "relogio", "pulso"),
)

BELEZA: Final = (
    _p("creme-corpo-400", "Creme hidratante corporal Moxico 400 ml", 3800, "creme_corpo", "hidratante", "400ml", "moxico"),
    _p("creme-corpo-karite", "Creme corporal com manteiga de karité 250 ml", 4500, "creme_corpo", "karite", "250ml"),
    _p("creme-rosto", "Creme de rosto FPS 30", 7800, "creme_rosto", "fps30"),
    _p("sabonete-coco", "Sabonete de coco 125 g", 450, "sabonete", "coco"),
    _p("sabonete-glicerina", "Sabonete de glicerina 100 g", 600, "sabonete", "glicerina"),
    _p("sabonete-liquido", "Sabonete líquido de mãos 500 ml", 1500, "sabonete", "liquido", "maos"),
    _p("gel-banho", "Gel de banho Moxico 750 ml", 2500, "gel_banho", "750ml", "moxico"),
    _p("champo-cabelo-crespo", "Champô para cabelo crespo 400 ml", 3200, "champo", "crespo", "400ml"),
    _p("champo-anticaspa", "Champô anticaspa 250 ml", 2900, "champo", "anticaspa"),
    _p("condicionador", "Condicionador hidratante 400 ml", 3300, "condicionador", "hidratante"),
    _p("relaxante-cabelo", "Relaxante de cabelo kit completo", 4800, "relaxante", "kit"),
    _p("relaxante-crianca", "Relaxante de cabelo para criança", 4200, "relaxante", "crianca"),
    _p("cabelo-trancas", "Cabelo sintético para tranças", 1500, "cabelo_sintetico", "trancas"),
    _p("extensoes-cabelo", "Extensões de cabelo liso 50 cm", 18000, "cabelo_sintetico", "extensoes", "liso"),
    _p("peruca-cacheada", "Peruca cacheada sintética", 25000, "peruca", "cacheada"),
    _p("oleo-coco-cabelo", "Óleo de coco para cabelo 200 ml", 2800, "oleo_cabelo", "coco"),
    _p("manteiga-karite", "Manteiga de karité pura 250 g", 5200, "manteiga_karite", "pura"),
    _p("desodorizante-spray", "Desodorizante spray homem 150 ml", 2300, "desodorizante", "spray", "homem"),
    _p("desodorizante-roll-on", "Desodorizante roll-on mulher 50 ml", 1900, "desodorizante", "roll_on", "mulher"),
    _p("desodorizante-stick", "Desodorizante em barra sem álcool", 2600, "desodorizante", "barra"),
    _p("perfume-homem-100", "Perfume Namibe homem 100 ml", 22000, "perfume", "homem", "100ml", "namibe"),
    _p("perfume-mulher-50", "Perfume Lubango mulher 50 ml", 18500, "perfume", "mulher", "50ml", "lubango"),
    _p("agua-colonia", "Água de colónia 250 ml", 6500, "perfume", "colonia"),
    _p("pasta-dentes-100", "Pasta de dentes com flúor 100 ml", 900, "pasta_dentes", "fluor"),
    _p("pasta-dentes-branqueadora", "Pasta de dentes branqueadora 75 ml", 1400, "pasta_dentes", "branqueadora"),
    _p("escova-dentes", "Escova de dentes média pack de 2", 800, "escova_dentes", "media"),
    _p("verniz-vermelho", "Verniz de unhas vermelho", 1200, "verniz", "vermelho"),
    _p("verniz-transparente", "Verniz de unhas transparente", 1100, "verniz", "transparente"),
    _p("removedor-verniz", "Removedor de verniz sem acetona", 900, "removedor", "sem_acetona"),
    _p("batom-vermelho", "Batom mate vermelho", 2800, "batom", "vermelho", "mate"),
    _p("batom-nude", "Batom cremoso nude", 2700, "batom", "nude"),
    _p("base-maquilhagem", "Base de maquilhagem tom escuro", 6900, "base", "escuro"),
    _p("lapis-olhos", "Lápis de olhos preto", 1300, "lapis_olhos", "preto"),
    _p("laminas-barbear", "Lâminas de barbear descartáveis pack de 5", 1600, "laminas", "descartaveis"),
    _p("espuma-barbear", "Espuma de barbear 200 ml", 2100, "espuma_barbear", "200ml"),
    _p("pensos-higienicos", "Pensos higiénicos com abas 10 unidades", 950, "pensos", "abas"),
    _p("fraldas-m", "Fraldas de bebé tamanho M 40 unidades", 7800, "fraldas", "m", "bebe"),
    _p("fraldas-g", "Fraldas de bebé tamanho G 36 unidades", 8200, "fraldas", "g", "bebe"),
    _p("toalhitas", "Toalhitas húmidas de bebé 80 unidades", 1700, "toalhitas", "bebe"),
    _p("algodao", "Algodão hidrófilo 100 g", 700, "algodao", "hidrofilo"),
    _p("protector-solar", "Protector solar FPS 50 200 ml", 9800, "protector_solar", "fps50"),
    _p("vaselina", "Vaselina pura 250 ml", 1600, "vaselina", "pura"),
)

#: Os cinco catalogos, com o nome do *tenant* sintetico de cada um. O nome e a
#: chave do ficheiro do *dataset*; o UUID do tenant gera-se na corrida.
CATALOGOS: Final = {
    "mercearia": MERCEARIA,
    "electro": ELECTRO,
    "construcao": CONSTRUCAO,
    "moda": MODA,
    "beleza": BELEZA,
}


def tenant_sintetico(catalogo: str) -> str:
    """O nome do tenant do §14.1 (`tenant-sintetico-NN`), pela ordem dos catalogos."""
    return f"tenant-sintetico-{list(CATALOGOS).index(catalogo) + 1:02d}"


def snapshot(catalogo: str) -> str:
    """O nome do *snapshot*: o catalogo e a versao (`mercearia-v1`)."""
    return f"{catalogo}-{VERSAO}"
