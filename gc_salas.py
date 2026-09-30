"""
Fase 77: varredura periódica de salas abandonadas (deploy da VPS).

O cancelamento por abandono (janela de 60s sem nenhum humano conectado) só pode
ser decidido por alguém que olhe a sala — e quando o último humano sai, nenhum
cliente mais emite evento naquela sala. Por isso esta peça existe: um processo
que acorda a cada 30s, varre o índice de resumos e cancela o que venceu.

Por que um serviço no compose e não um cron HTTP na API:
  - nada de endpoint público novo (token, rota no nginx e interação com o rate
    limit de borda);
  - compartilha o `store` e o MESMO Redis das 4 réplicas, então o lock
    distribuído (`store.trancar_sala_distribuida`) já serializa contra os
    handlers em andamento;
  - a lógica da varredura é a MESMA que a opportunista do `listar_partidas`
    (`funcoes_gerais.varrer_salas_abandonadas`) — não há caminho de cancelamento
    só de cron.

Importa SÓ `funcoes_gerais`/`store`, nunca `app`: `import app` daria boot no
Flask e no SocketIO (e a varredura não emite nada). Por isso a função de
cancelamento mora em `funcoes_gerais`.

Rodar local (sem Docker), contra o Redis da VPS:
    DADINHO_REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python gc_salas.py
Uma passada só (sem loop), para depurar:
    DADINHO_REDIS_URL=... .venv/Scripts/python gc_salas.py --uma-vez
"""
import argparse
import logging
import os
import sys
import time

# `DADINHO_REDIS_URL` vem do mesmo ambiente das réplicas da API (docker-compose).
# Sem ele, o store cai no backend em memória — que aqui seria inútil, porque cada
# processo teria o seu. Falhar cedo é melhor que varrer o vazio em silêncio.
if not os.environ.get("DADINHO_REDIS_URL") and not os.environ.get("UPSTASH_REDIS_REST_URL"):
    print("gc_salas: defina DADINHO_REDIS_URL (VPS) ou UPSTASH_REDIS_REST_URL "
          "(Vercel) — sem store compartilhado a varredura não vê sala nenhuma.",
          file=sys.stderr)
    sys.exit(2)

import funcoes_gerais  # noqa: E402  (após o guarda de env de propósito)
import store  # noqa: E402

_log = logging.getLogger("gc_salas")

# Cadência da passada. 30s é folgado para uma janela de 60s: o pior caso é a
# sala morrer ~90s depois do último humano sair, e o TTL curto do store (120s)
# é a barreira final de qualquer atraso.
INTERVALO_SEGUNDOS = 30


def uma_passada():
    """Varre uma vez e devolve quantas salas foram canceladas."""
    inicio = time.monotonic()
    try:
        canceladas = funcoes_gerais.varrer_salas_abandonadas(forcar=True)
    except Exception as erro:  # noqa: BLE001 — a varredura nunca derruba o loop
        _log.warning("passada falhou (%s); tentando de novo em %ss",
                     erro, INTERVALO_SEGUNDOS, exc_info=True)
        return 0
    if canceladas:
        _log.info("canceladas por abandono: %s", ", ".join(sorted(canceladas)))
    duracao = time.monotonic() - inicio
    _log.debug("passada em %.0fms, %d cancelada(s)", duracao * 1000, len(canceladas))
    return len(canceladas)


def main():
    parser = argparse.ArgumentParser(description="Varredura de salas abandonadas (Fase 77)")
    parser.add_argument("--uma-vez", action="store_true",
                        help="faz UMA passada e sai (depuração; o serviço usa loop)")
    parser.add_argument("--verbose", action="store_true", help="log em nível DEBUG")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    _log.info("gc_salas iniciado (store=%s, janela sem humano=%ss, intervalo=%ss)",
              type(store.armazenamento).__name__,
              funcoes_gerais.TEMPO_SEM_HUMANO_SEGUNDOS, INTERVALO_SEGUNDOS)

    if args.uma_vez:
        uma_passada()
        return 0

    # Loop sem `while True` cru: o `time.sleep` é o RITMO DO PROCESSO DE FUNDO
    # (container dedicado, igual ao polling do navegador), não um timer de
    # gameplay. Nenhum request da API depende dele — daí ser seguro rodar.
    while True:
        uma_passada()
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    sys.exit(main())
