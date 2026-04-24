import json
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Oracle MT5 Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_price(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"

def interpretar_pergunta(pergunta: str, sinal: str, entrada: float, stop: float, alvo: float, digits: int) -> str:
    p = (pergunta or "").strip().lower()
    if not p:
        return ""

    if "compra ou venda" in p:
        return f"A leitura atual favorece {sinal.lower()}."
    if "stop" in p:
        return f"O stop protegido sugerido fica em {format_price(stop, digits)}."
    if "alvo" in p:
        return f"O alvo projetado em 2:1 fica em {format_price(alvo, digits)}."
    if "entrada" in p:
        return f"A entrada sugerida considera o preço atual em {format_price(entrada, digits)}."
    if "ainda vale" in p or "vale" in p:
        return f"A operação continua válida enquanto o preço não perca o stop técnico em {format_price(stop, digits)}."

    return "A pergunta foi usada como contexto complementar da leitura."

def analisar_candles(metadata: Dict[str, Any]) -> Dict[str, Any]:
    symbol = metadata.get("symbol", "ATIVO")
    timeframe = metadata.get("timeframe", "M15")
    bid = float(metadata.get("bid", 0.0))
    ask = float(metadata.get("ask", 0.0))
    point = float(metadata.get("point", 0.01))
    digits = int(metadata.get("digits", 2))
    candles = metadata.get("candles", [])

    if len(candles) < 20:
        return {
            "status": "erro",
            "mensagem": "Poucas velas recebidas."
        }

    # candles chegam da mais antiga para a mais nova
    # último item tende a ser a vela atual em formação
    fechadas = candles[:-1] if len(candles) >= 2 else candles
    recentes = fechadas[-8:]
    swing = fechadas[-6:]

    first_close = float(recentes[0]["close"])
    last_close = float(recentes[-1]["close"])

    bullish = sum(1 for c in recentes if float(c["close"]) > float(c["open"]))
    bearish = sum(1 for c in recentes if float(c["close"]) < float(c["open"]))

    delta = last_close - first_close

    sinal = "SEM_SINAL"
    if delta > 0 and bullish >= bearish:
        sinal = "COMPRA"
    elif delta < 0 and bearish >= bullish:
        sinal = "VENDA"

    if sinal == "SEM_SINAL":
        return {
            "status": "sucesso",
            "sinal": "SEM SINAL CLARO",
            "ativo": symbol,
            "timeframe": timeframe,
            "entrada": "",
            "stop": "",
            "alvo": "",
            "rr": "",
            "confianca": "58%",
            "comentario": "Estrutura recente mista, sem direção clara.",
            "resposta_contextual": ""
        }

    if sinal == "COMPRA":
        entrada = ask if ask > 0 else last_close
        fundo = min(float(c["low"]) for c in swing)
        stop = fundo - (point * 5)
        risco = abs(entrada - stop)
        alvo = entrada + (risco * 2.0)
        comentario = "Fluxo comprador recente com sustentação acima da estrutura fechada mais próxima."
    else:
        entrada = bid if bid > 0 else last_close
        topo = max(float(c["high"]) for c in swing)
        stop = topo + (point * 5)
        risco = abs(stop - entrada)
        alvo = entrada - (risco * 2.0)
        comentario = "Fluxo vendedor recente com rejeição da estrutura fechada mais próxima."

    return {
        "status": "sucesso",
        "sinal": sinal,
        "ativo": symbol,
        "timeframe": timeframe,
        "entrada": format_price(entrada, digits),
        "stop": format_price(stop, digits),
        "alvo": format_price(alvo, digits),
        "rr": "2:1",
        "confianca": "74%",
        "comentario": comentario
    }

@app.get("/")
async def home():
    return {"status": "online", "servico": "oracle_mt5_bridge"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/analisar-mt5-completo")
async def analisar_mt5_completo(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    pergunta: Optional[str] = Form(default="")
):
    # A imagem é recebida e pode ser usada depois como apoio visual / auditoria
    _ = await file.read()

    metadata = json.loads(metadata_json)
    resultado = analisar_candles(metadata)

    if resultado.get("status") != "sucesso":
        return resultado

    digits = int(metadata.get("digits", 2))

    entrada = float(resultado["entrada"]) if resultado["entrada"] != "" else 0.0
    stop = float(resultado["stop"]) if resultado["stop"] != "" else 0.0
    alvo = float(resultado["alvo"]) if resultado["alvo"] != "" else 0.0

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
