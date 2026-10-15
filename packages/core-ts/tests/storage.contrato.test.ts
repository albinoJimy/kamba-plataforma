/**
 * Suite de contrato de `StorageProvider`, nos alvos que correm sem contentor
 * (KAM-011).
 *
 * A bateria está em `apoio/contrato-storage.ts` e é a mesma que
 * `integracao/storage.s3real.test.ts` corre contra um servidor S3 real. Aqui
 * corre duas vezes:
 *
 * - sobre o ***fake***, que é o que os consumidores usam nos seus testes;
 * - sobre o **motor S3 ligado a um servidor S3 em memória** — o mesmo código de
 *   produção (assinatura, XML, envio em partes), com a rede trocada por uma
 *   função.
 *
 * O segundo alvo **não** é a prova de que o motor fala S3: o servidor em
 * memória foi escrito por quem escreveu o motor. Essa prova é a de
 * `docs/evidencia/KAM-011-seaweedfs.md`.
 */

import { alvoFake, alvoS3EmMemoria } from "./apoio/alvos-storage.ts";
import { bateriaDeContrato } from "./apoio/contrato-storage.ts";

bateriaDeContrato("fake", alvoFake);
bateriaDeContrato("s3 em memória", alvoS3EmMemoria);
