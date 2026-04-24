import json
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Oracle MT5 Bridge", version="3.4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def format_price(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def interpretar_pergunta(
    pergunta: str,
    sinal: str,
    entrada: float,
    stop: float,
    alvo: float,
    digits: int,
    vies: str,
    modo_operacional: str
) -> str:
    p = (pergunta or "").strip().lower()

    if not p:
        return "Sem pergunta adicional."

    if "compra ou venda" in p:
        return f"Leitura atual favorece {sinal.lower()}."

    if "stop" in p:
        return f"Stop tecnico sugerido em {format_price(stop, digits)}."

    if "alvo" in p or "target" in p:
        return f"Alvo 2:1 projetado em {format_price(alvo, digits)}."

    if "entrada" in p:
        return f"Entrada operacional em {format_price(entrada, digits)}."

    if "vale" in p or "ainda" in p:
        return f"Operacao segue valida enquanto nao perder o stop em {format_price(stop, digits)}."

    if "vies" in p:
        return f"Vies atual do fluxo: {vies}."

    if "modo" in p:
        return f"Modo operacional sugerido: {modo_operacional}."

    if "ema" in p:
        return "A leitura considerou EMA20 e EMA200 no contexto de tendencia."

    if "vwap" in p:
        return "A leitura considerou VWAP diaria, semanal e mensal."

    return "Pergunta usada como contexto complementar da leitura."


def obter_indicadores(metadata: Dict[str, Any]) -> Dict[str, float]:
    ind = metadata.get("indicadores", {}) or {}
    return {
        "ema20": to_float(ind.get("ema20", 0.0)),
        "ema200": to_float(ind.get("ema200", 0.0)),
        "atr": to_float(ind.get("atr", 0.0)),
        "vwap_diaria": to_float(ind.get("vwap_diaria", 0.0)),
        "vwap_semanal": to_float(ind.get("vwap_semanal", 0.0)),
        "vwap_mensal": to_float(ind.get("vwap_mensal", 0.0)),
        "zscore_volume": to_float(ind.get("zscore_volume", 0.0)),
    }


def contar_pressao(candles: List[Dict[str, Any]]) -> Dict[str, int]:
    bullish = 0
    bearish = 0

    for c in candles:
        o = to_float(c.get("open", 0.0))
        cl = to_float(c.get("close", 0.0))
        if cl > o:
            bullish += 1
        elif cl < o:
            bearish += 1

    return {"bullish": bullish, "bearish": bearish}


def classificar_fluxo(
    preco: float,
    indicadores: Dict[str, float],
    candles_recentes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    ema20 = indicadores["ema20"]
    ema200 = indicadores["ema200"]
    atr = indicadores["atr"]
    vwap_d = indicadores["vwap_diaria"]
    vwap_w = indicadores["vwap_semanal"]
    vwap_m = indicadores["vwap_mensal"]
    zscore = indicadores["zscore_volume"]

    pressao = contar_pressao(candles_recentes)
    bullish = pressao["bullish"]
    bearish = pressao["bearish"]

    score_compra = 0
    score_venda = 0
    fatores_compra: List[str] = []
    fatores_venda: List[str] = []

    if ema20 > 0 and preco > ema20:
        score_compra += 1
        fatores_compra.append("preco acima EMA20")
    elif ema20 > 0 and preco < ema20:
        score_venda += 1
        fatores_venda.append("preco abaixo EMA20")

    if ema20 > 0 and ema200 > 0 and ema20 > ema200:
        score_compra += 1
        fatores_compra.append("EMA20 acima EMA200")
    elif ema20 > 0 and ema200 > 0 and ema20 < ema200:
        score_venda += 1
        fatores_venda.append("EMA20 abaixo EMA200")

    if vwap_d > 0 and preco > vwap_d:
        score_compra += 1
        fatores_compra.append("preco acima VWAP diaria")
    elif vwap_d > 0 and preco < vwap_d:
        score_venda += 1
        fatores_venda.append("preco abaixo VWAP diaria")

    if vwap_w > 0 and preco > vwap_w:
        score_compra += 1
        fatores_compra.append("preco acima VWAP semanal")
    elif vwap_w > 0 and preco < vwap_w:
        score_venda += 1
        fatores_venda.append("preco abaixo VWAP semanal")

    if vwap_m > 0 and preco > vwap_m:
        score_compra += 1
        fatores_compra.append("preco acima VWAP mensal")
    elif vwap_m > 0 and preco < vwap_m:
        score_venda += 1
        fatores_venda.append("preco abaixo VWAP mensal")

    if zscore > 0.20:
        score_compra += 1
        fatores_compra.append("zscore volume positivo")
    elif zscore < -0.20:
        score_venda += 1
        fatores_venda.append("zscore volume negativo")

    if bullish > bearish:
        score_compra += 1
        fatores_compra.append("pressao compradora recente")
    elif bearish > bullish:
        score_venda += 1
        fatores_venda.append("pressao vendedora recente")

    if atr > 0:
        fatores_base = f"ATR ativo {atr:.2f}"
    else:
        fatores_base = "ATR indisponivel"

    if score_compra >= 4 and score_compra > score_venda:
        confianca = min(92, 64 + score_compra * 4)
        return {
            "sinal": "COMPRA",
            "tipo_cenario": "COMPRA INSTITUCIONAL",
            "confianca": f"{confianca}%",
            "vies": "Comprador",
            "modo_operacional": "Pullback comprador",
            "comentario_base": "Confluencia compradora detectada com sustentacao estrutural.",
            "fatores": fatores_compra[:6],
            "fatores_base": fatores_base,
        }

    if score_venda >= 4 and score_venda > score_compra:
        confianca = min(92, 64 + score_venda * 4)
        return {
            "sinal": "VENDA",
            "tipo_cenario": "VENDA INSTITUCIONAL",
            "confianca": f"{confianca}%",
            "vies": "Vendedor",
            "modo_operacional": "Pullback vendedor",
            "comentario_base": "Confluencia vendedora detectada com rejeicao estrutural.",
            "fatores": fatores_venda[:6],
            "fatores_base": fatores_base,
        }

    return {
        "sinal": "SEM SINAL CLARO",
        "tipo_cenario": "SEM SINAL CLARO",
        "confianca": "58%",
        "vies": "Neutro",
        "modo_operacional": "Aguardar confirmacao",
        "comentario_base": "Os fatores atuais ainda nao formam confluencia forte o suficiente.",
        "fatores": [],
        "fatores_base": fatores_base,
    }


def calcular_stop_alvo(
    preco_entrada: float,
    point: float,
    digits: int,
    candles_fechados: List[Dict[str, Any]],
    sinal: str
) -> Dict[str, float]:
    swing = candles_fechados[-6:] if len(candles_fechados) >= 6 else candles_fechados

    if not swing:
        risco_padrao = max(point * 120, abs(preco_entrada) * 0.001)
        if sinal == "COMPRA":
            stop = preco_entrada - risco_padrao
            alvo = preco_entrada + risco_padrao * 2.0
        else:
            stop = preco_entrada + risco_padrao
            alvo = preco_entrada - risco_padrao * 2.0

        return {
            "entrada": round(preco_entrada, digits),
            "stop": round(stop, digits),
            "alvo": round(alvo, digits),
        }

    buffer_preco = max(point * 5, point)

    if sinal == "COMPRA":
        fundo = min(to_float(c["low"]) for c in swing)
        stop = fundo - buffer_preco
        risco = abs(preco_entrada - stop)
        if risco <= 0:
            risco = max(point * 120, abs(preco_entrada) * 0.001)
            stop = preco_entrada - risco
        alvo = preco_entrada + (risco * 2.0)
    else:
        topo = max(to_float(c["high"]) for c in swing)
        stop = topo + buffer_preco
        risco = abs(stop - preco_entrada)
        if risco <= 0:
            risco = max(point * 120, abs(preco_entrada) * 0.001)
            stop = preco_entrada + risco
        alvo = preco_entrada - (risco * 2.0)

    return {
        "entrada": round(preco_entrada, digits),
        "stop": round(stop, digits),
        "alvo": round(alvo, digits),
    }


def montar_comentario_final(
    fluxo: Dict[str, Any],
    indicadores: Dict[str, float],
    digits: int
) -> str:
    base = fluxo["comentario_base"]
    fatores = fluxo.get("fatores", [])

    if not fatores:
        return base

    fatores_txt = ", ".join(fatores[:4])

    partes = []
    if indicadores["ema20"] > 0:
        partes.append(f"EMA20 {format_price(indicadores['ema20'], digits)}")
    if indicadores["ema200"] > 0:
        partes.append(f"EMA200 {format_price(indicadores['ema200'], digits)}")
    if indicadores["vwap_diaria"] > 0:
        partes.append(f"VWAP D {format_price(indicadores['vwap_diaria'], digits)}")
    partes.append(f"ZVol {indicadores['zscore_volume']:.2f}")

    return f"{base} Fatores: {fatores_txt}. Contexto: {', '.join(partes)}."


def analisar_candles(metadata: Dict[str, Any]) -> Dict[str, Any]:
    symbol = metadata.get("symbol", "ATIVO")
    timeframe = metadata.get("timeframe", "M15")
    bid = to_float(metadata.get("bid", 0.0))
    ask = to_float(metadata.get("ask", 0.0))
    point = to_float(metadata.get("point", 0.01), 0.01)
    digits = to_int(metadata.get("digits", 2), 2)
    candles = metadata.get("candles", []) or []

    if len(candles) < 20:
        return {
            "status": "erro",
            "mensagem": "Poucas velas recebidas."
        }

    indicadores = obter_indicadores(metadata)

    candles_fechados = candles[:-1] if len(candles) >= 2 else candles
    recentes = candles_fechados[-8:] if len(candles_fechados) >= 8 else candles_fechados

    ultimo_close = to_float(candles_fechados[-1]["close"])
    preco_ref_buy = ask if ask > 0 else ultimo_close
    preco_ref_sell = bid if bid > 0 else ultimo_close
    preco_referencia = preco_ref_buy if preco_ref_buy > 0 else ultimo_close

    fluxo = classificar_fluxo(
        preco=preco_referencia,
        indicadores=indicadores,
        candles_recentes=recentes
    )

    sinal = fluxo["sinal"]

    if sinal == "SEM SINAL CLARO":
        return {
            "status": "sucesso",
            "sinal": "SEM SINAL CLARO",
            "ativo": symbol,
            "timeframe": timeframe,
            "entrada": "",
            "stop": "",
            "alvo": "",
            "rr": "",
            "confianca": fluxo["confianca"],
            "comentario": fluxo["comentario_base"],
            "tipo_cenario": fluxo["tipo_cenario"],
            "vies": fluxo["vies"],
            "modo_operacional": fluxo["modo_operacional"],
            "fatores": fluxo["fatores"],
            "resposta_contextual": ""
        }

    preco_entrada = preco_ref_buy if sinal == "COMPRA" else preco_ref_sell

    niveis = calcular_stop_alvo(
        preco_entrada=preco_entrada,
        point=point,
        digits=digits,
        candles_fechados=candles_fechados,
        sinal=sinal
    )

    comentario = montar_comentario_final(
        fluxo=fluxo,
        indicadores=indicadores,
        digits=digits
    )

    return {
        "status": "sucesso",
        "sinal": sinal,
        "ativo": symbol,
        "timeframe": timeframe,
        "entrada": format_price(niveis["entrada"], digits),
        "stop": format_price(niveis["stop"], digits),
        "alvo": format_price(niveis["alvo"], digits),
        "rr": "2:1",
        "confianca": fluxo["confianca"],
        "comentario": comentario,
        "tipo_cenario": fluxo["tipo_cenario"],
        "vies": fluxo["vies"],
        "modo_operacional": fluxo["modo_operacional"],
        "fatores": fluxo["fatores"]
    }


@app.get("/")
async def home():
    return {"status": "online", "servico": "oracle_mt5_bridge", "versao": "3.4"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analisar-mt5-completo")
async def analisar_mt5_completo(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    pergunta: Optional[str] = Form(default="")
):
    _ = await file.read()

    metadata = json.loads(metadata_json)
    resultado = analisar_candles(metadata)

    if resultado.get("status") != "sucesso":
        return resultado

    digits = to_int(metadata.get("digits", 2), 2)

    entrada = to_float(resultado["entrada"]) if resultado["entrada"] != "" else 0.0
    stop = to_float(resultado["stop"]) if resultado["stop"] != "" else 0.0
    alvo = to_float(resultado["alvo"]) if resultado["alvo"] != "" else 0.0
    vies = resultado.get("vies", "Neutro")
    modo_operacional = resultado.get("modo_operacional", "Aguardar confirmacao")

    resposta_contextual = interpretar_pergunta(
        pergunta=pergunta or "",
        sinal=resultado["sinal"],
        entrada=entrada,
        stop=stop,
        alvo=alvo,
        digits=digits,
        vies=vies,
        modo_operacional=modo_operacional
    )

    resultado["pergunta_usuario"] = (pergunta or "").strip()
    resultado["resposta_contextual"] = resposta_contextual

    return resultado
