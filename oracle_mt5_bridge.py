import json
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Oracle MT5 Bridge", version="3.2")

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


def interpretar_pergunta(pergunta: str, sinal: str, entrada: float, stop: float, alvo: float, digits: int) -> str:
    p = (pergunta or "").strip().lower()

    if not p:
        return ""

    if "compra ou venda" in p:
        return f"A leitura atual favorece {sinal.lower()}."

    if "stop" in p:
        return f"O stop protegido sugerido fica em {format_price(stop, digits)}."

    if "alvo" in p or "target" in p:
        return f"O alvo projetado em 2:1 fica em {format_price(alvo, digits)}."

    if "entrada" in p:
        return f"A entrada sugerida considera o preço atual em {format_price(entrada, digits)}."

    if "ainda vale" in p or "vale a pena" in p or "vale" in p:
        return f"A operação continua válida enquanto o preço não perder o nível técnico de stop em {format_price(stop, digits)}."

    if "ema" in p:
        return "A leitura considerou a posição do preço em relação à EMA20 e à EMA200."

    if "vwap" in p:
        return "A leitura considerou a posição do preço em relação à VWAP diária, semanal e mensal."

    return "A pergunta foi usada como contexto complementar da leitura."


def obter_indicadores(metadata: Dict[str, Any]) -> Dict[str, float]:
    ind = metadata.get("indicadores", {}) or {}
    return {
        "ema20": to_float(ind.get("ema20", 0.0)),
        "ema200": to_float(ind.get("ema200", 0.0)),
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


def classificar_cenario(preco: float, ema20: float, ema200: float, vwap_d: float, zscore: float, candles_recentes: List[Dict[str, Any]]) -> Dict[str, Any]:
    pressao = contar_pressao(candles_recentes)
    bullish = pressao["bullish"]
    bearish = pressao["bearish"]

    score_compra = 0
    score_venda = 0
    fatores_compra = []
    fatores_venda = []

    if ema20 > 0 and preco > ema20:
        score_compra += 1
        fatores_compra.append("preço acima da EMA20")
    elif ema20 > 0 and preco < ema20:
        score_venda += 1
        fatores_venda.append("preço abaixo da EMA20")

    if ema20 > 0 and ema200 > 0 and ema20 > ema200:
        score_compra += 1
        fatores_compra.append("EMA20 acima da EMA200")
    elif ema20 > 0 and ema200 > 0 and ema20 < ema200:
        score_venda += 1
        fatores_venda.append("EMA20 abaixo da EMA200")

    if vwap_d > 0 and preco > vwap_d:
        score_compra += 1
        fatores_compra.append("preço acima da VWAP diária")
    elif vwap_d > 0 and preco < vwap_d:
        score_venda += 1
        fatores_venda.append("preço abaixo da VWAP diária")

    if zscore > 0.20:
        score_compra += 1
        fatores_compra.append("z-score de volume positivo")
    elif zscore < -0.20:
        score_venda += 1
        fatores_venda.append("z-score de volume negativo")

    if bullish > bearish:
        score_compra += 1
        fatores_compra.append("pressão compradora recente")
    elif bearish > bullish:
        score_venda += 1
        fatores_venda.append("pressão vendedora recente")

    if score_compra >= 3 and score_compra > score_venda:
        confianca = min(88, 62 + score_compra * 4)
        return {
            "sinal": "COMPRA",
            "confianca": f"{confianca}%",
            "comentario_base": "Confluência compradora entre estrutura recente e indicadores de tendência.",
            "fatores": fatores_compra,
            "tipo_cenario": "COMPRA INSTITUCIONAL"
        }

    if score_venda >= 3 and score_venda > score_compra:
        confianca = min(88, 62 + score_venda * 4)
        return {
            "sinal": "VENDA",
            "confianca": f"{confianca}%",
            "comentario_base": "Confluência vendedora entre estrutura recente e indicadores de tendência.",
            "fatores": fatores_venda,
            "tipo_cenario": "VENDA INSTITUCIONAL"
        }

    return {
        "sinal": "SEM SINAL CLARO",
        "confianca": "58%",
        "comentario_base": "Os fatores atuais ainda não formam confluência forte o suficiente para uma entrada profissional.",
        "fatores": [],
        "tipo_cenario": "SEM SINAL CLARO"
    }


def calcular_stop_alvo(symbol: str, timeframe: str, preco_entrada: float, point: float, digits: int, candles_fechados: List[Dict[str, Any]], sinal: str) -> Dict[str, float]:
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


def montar_comentario_final(sinal_info: Dict[str, Any], indicadores: Dict[str, float], preco_referencia: float, digits: int) -> str:
    base = sinal_info["comentario_base"]
    fatores = sinal_info.get("fatores", [])

    if not fatores:
        return base

    fatores_txt = ", ".join(fatores[:4])

    ema20 = indicadores["ema20"]
    ema200 = indicadores["ema200"]
    vwap_d = indicadores["vwap_diaria"]
    zscore = indicadores["zscore_volume"]

    detalhes = []
    if ema20 > 0:
        detalhes.append(f"EMA20 {format_price(ema20, digits)}")
    if ema200 > 0:
        detalhes.append(f"EMA200 {format_price(ema200, digits)}")
    if vwap_d > 0:
        detalhes.append(f"VWAP D {format_price(vwap_d, digits)}")
    detalhes.append(f"Z-Score Vol {zscore:.2f}")

    return f"{base} Fatores: {fatores_txt}. Contexto técnico: {', '.join(detalhes)}."


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

    # última vela tende a estar em formação
    candles_fechados = candles[:-1] if len(candles) >= 2 else candles
    recentes = candles_fechados[-8:] if len(candles_fechados) >= 8 else candles_fechados

    ultimo_close = to_float(candles_fechados[-1]["close"])
    preco_referencia = ask if ask > 0 else ultimo_close

    sinal_info = classificar_cenario(
        preco=preco_referencia,
        ema20=indicadores["ema20"],
        ema200=indicadores["ema200"],
        vwap_d=indicadores["vwap_diaria"],
        zscore=indicadores["zscore_volume"],
        candles_recentes=recentes
    )

    sinal = sinal_info["sinal"]

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
            "confianca": sinal_info["confianca"],
            "comentario": sinal_info["comentario_base"],
            "tipo_cenario": sinal_info["tipo_cenario"],
            "fatores": sinal_info["fatores"],
            "resposta_contextual": ""
        }

    preco_entrada = ask if sinal == "COMPRA" and ask > 0 else bid if sinal == "VENDA" and bid > 0 else ultimo_close

    niveis = calcular_stop_alvo(
        symbol=symbol,
        timeframe=timeframe,
        preco_entrada=preco_entrada,
        point=point,
        digits=digits,
        candles_fechados=candles_fechados,
        sinal=sinal
    )

    comentario = montar_comentario_final(
        sinal_info=sinal_info,
        indicadores=indicadores,
        preco_referencia=preco_entrada,
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
        "confianca": sinal_info["confianca"],
        "comentario": comentario,
        "tipo_cenario": sinal_info["tipo_cenario"],
        "fatores": sinal_info["fatores"]
    }


@app.get("/")
async def home():
    return {"status": "online", "servico": "oracle_mt5_bridge", "versao": "3.2"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analisar-mt5-completo")
async def analisar_mt5_completo(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    pergunta: Optional[str] = Form(default="")
):
    # A imagem já entra no fluxo para futura auditoria e apoio visual
    _ = await file.read()

    metadata = json.loads(metadata_json)
    resultado = analisar_candles(metadata)

    if resultado.get("status") != "sucesso":
        return resultado

    digits = to_int(metadata.get("digits", 2), 2)

    entrada = to_float(resultado["entrada"]) if resultado["entrada"] != "" else 0.0
    stop = to_float(resultado["stop"]) if resultado["stop"] != "" else 0.0
    alvo = to_float(resultado["alvo"]) if resultado["alvo"] != "" else 0.0

    resposta_contextual = interpretar_pergunta(
        pergunta=pergunta or "",
        sinal=resultado["sinal"],
        entrada=entrada,
        stop=stop,
        alvo=alvo,
        digits=digits
    )

    resultado["pergunta_usuario"] = (pergunta or "").strip()
    resultado["resposta_contextual"] = resposta_contextual

    return resultado
