# seed.py
"""
Aleatoriedade verificável (provably fair) do Dadinho — contrato v1.

A seed da partida é derivada por commit-reveal: o servidor compromete uma
entropia externa (beacon drand) e cada jogador contribui com um nonce gerado no
cliente. Ninguém escolhe o resultado: o servidor não via os nonces dos jogadores
ao comprometer, e os jogadores não veem os nonces uns dos outros antes das
jogadas. No fim da partida tudo é revelado e qualquer um recomputa os dados.

Fórmula v1 (pública, byte-a-byte):

    compromisso(nonce) = SHA256hex("dadinho:v1:commit|" + nonce)

    seed_final = SHA256hex(
        "dadinho:v1:seed|" + fonte + "|" + entropia_externa + "|" + n_1 + "|" + ... + n_k
    )
    onde n_i são os nonces dos participantes ordenados por client_id (UTF-8 asc).

    valor(sala, partida, rodada, client_id, indice) =
        (int_be(HMAC-SHA256(bytes(seed_final),
            "dadinho:v1:roll|" + sala|partida|rodada|client_id|indice)) mod 6) + 1

    indice_inicial(total) =
        int_be(HMAC-SHA256(bytes(seed_final),
            "dadinho:v1:start|" + sala|partida)) mod total

A mesma fórmula está implementada em static/script.js (Web Crypto) para o
cliente conferir a auditoria sem confiar no servidor.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import urllib.request

VERSAO_ATUAL = 1

DOMINIO_COMMIT = "dadinho:v1:commit|"
DOMINIO_SEED = "dadinho:v1:seed|"
DOMINIO_ROLL = "dadinho:v1:roll|"
DOMINIO_START = "dadinho:v1:start|"

REGEX_HEX_64 = re.compile(r"^[0-9a-f]{64}$")

# Beacon drand (League of Entropy). Default: quicknet (período de 3s).
DRAND_URL = os.environ.get("DADINHO_DRAND_URL", "https://api.drand.sh").rstrip("/")
DRAND_CHAIN_PADRAO = os.environ.get(
    "DADINHO_DRAND_CHAIN",
    "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971",
)
# 0 = usa o round já publicado (sempre disponível e verificável). A garantia
# anti-grinding vem da ordem: o servidor fixa o round antes de ver os nonces.
DRAND_MARGEM_ROUNDS = 0
DRAND_TIMEOUT = 6


def valido_nonce(nonce):
    """True se o valor é um nonce hex de 32 bytes (64 chars minúsculos)."""
    return isinstance(nonce, str) and bool(REGEX_HEX_64.match(nonce))


def gerar_nonce():
    """Nonce aleatório de 32 bytes em hex minúsculo (cliente ou servidor)."""
    return secrets.token_hex(32)


def compromisso(nonce):
    """Hash de compromisso de um nonce (publicável antes da revelação)."""
    return hashlib.sha256((DOMINIO_COMMIT + nonce).encode("utf-8")).hexdigest()


def nonce_fallback(compromisso_hex):
    """
    Contribuição determinística de um participante que comprometeu mas não
    revelou o nonce: H(compromisso). Fica marcada como 'sem_reveal' na auditoria.
    """
    return hashlib.sha256((compromisso_hex or "").encode("utf-8")).hexdigest()


def derivar_seed(fonte, entropia_externa, nonces_por_id):
    """
    SHA-256 da concatenação canônica. `nonces_por_id` é um dict
    client_id -> nonce hex; a ordem é fixa (UTF-8 asc) para o servidor não poder
    escolher a ordenação depois de ver os nonces.
    """
    ordem = sorted(nonces_por_id.keys(), key=lambda cid: cid.encode("utf-8"))
    partes = [str(fonte), str(entropia_externa)] + [nonces_por_id[cid] for cid in ordem]
    msg = (DOMINIO_SEED + "|".join(partes)).encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def valor(seed_hex, sala_id, partida_num, rodada_num, client_id, indice):
    """Valor (1-6) do dado `indice` do jogador numa rodada, derivado da seed."""
    chave = bytes.fromhex(seed_hex)
    msg = (DOMINIO_ROLL + "|".join([
        str(sala_id), str(partida_num), str(rodada_num), str(client_id), str(indice),
    ])).encode("utf-8")
    digest = hmac.new(chave, msg, hashlib.sha256).digest()
    return int.from_bytes(digest, "big") % 6 + 1


def indice_inicial(seed_hex, sala_id, partida_num, total):
    """Índice do jogador que começa a partida (ordenado por partida.jogadores)."""
    chave = bytes.fromhex(seed_hex)
    msg = (DOMINIO_START + "|".join([str(sala_id), str(partida_num)])).encode("utf-8")
    digest = hmac.new(chave, msg, hashlib.sha256).digest()
    return int.from_bytes(digest, "big") % total


# ---------------------------------------------------------------------------
# Beacon drand
# ---------------------------------------------------------------------------

def _drand_get(caminho, timeout=DRAND_TIMEOUT):
    url = f"{DRAND_URL}/{caminho}"
    pedido = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def beacon_planejar(chain=None, margem=DRAND_MARGEM_ROUNDS):
    """
    Fixa um round FUTURO do beacon (escolhido antes de conhecer os nonces, para
    o servidor não poder escanear rounds em busca de uma seed favorável).
    Devolve o plano {chain, round, period, public_key} ou None se indisponível.
    """
    chain = chain or DRAND_CHAIN_PADRAO
    try:
        info = _drand_get(f"{chain}/info")
        ultimo = _drand_get(f"{chain}/public/latest")
        round_atual = int(ultimo.get("round", 0))
        if round_atual <= 0:
            return None
        return {
            "chain": chain,
            "round": round_atual + int(margem),
            "period": info.get("period"),
            "public_key": info.get("public_key"),
        }
    except Exception:
        return None


def beacon_buscar(chain, round_num):
    """Randomness (hex) de um round do beacon, ou None se ainda/indisponível."""
    try:
        dados = _drand_get(f"{chain}/public/{int(round_num)}")
    except Exception:
        return None
    randomness = dados.get("randomness")
    if valido_nonce(randomness):
        return randomness
    return None
