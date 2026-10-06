#!/usr/bin/env python3
"""
Painel diário de sinais técnicos para ativos negociados na B3.

Ativos padrão:
- ETFs: GOLD11, WRLD11, ALUG11, IRFM11, USDB11, NUCL11, HTEK11
- FI-Infra: KDIF11

Principais mudanças em relação à versão original:
1. Remove escapes/indentação inválidos de Markdown.
2. Trata KDIF11 como FI-Infra, não como ETF.
3. Usa apenas candle diário concluído.
4. Separa tendência, momentum e confirmação por volume.
5. Detecta cruzamento real de MM9/MM21.
6. RSI/Bollinger não são usados como gatilhos simplistas de reversão.
7. Gera score técnico normalizado de 0 a 100.
8. Melhora tratamento de erros de Yahoo Finance e brapi.
9. Alinha corretamente as séries para correlação móvel.
10. Usa janelas maiores e datas explícitas no painel.

Requisitos:
    pip install --upgrade yfinance pandas numpy requests matplotlib seaborn

Uso:
    python dashboard_assets_reescrito.py
    python dashboard_assets_reescrito.py --corr
    python dashboard_assets_reescrito.py --corr --show
    python dashboard_assets_reescrito.py --no-open

Opcional para fallback da brapi:
    export BRAPI_TOKEN=seu_token            # Linux/macOS
    set BRAPI_TOKEN=seu_token               # Windows cmd
    $env:BRAPI_TOKEN="seu_token"           # PowerShell

AVISO:
    Ferramenta educativa. Score/viés técnico não constitui recomendação
    de investimento.
"""

from __future__ import annotations

import argparse
import html
import math
import os
import sys
import webbrowser
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

try:
    import yfinance as yf
except ModuleNotFoundError:
    yf = None  # type: ignore[assignment]


# -----------------------------------------------------------------------------
# Configuração
# -----------------------------------------------------------------------------

B3_TZ = ZoneInfo("America/Sao_Paulo")
# Margem conservadora: se houver candle de hoje antes deste horário, descartamos.
HORARIO_CANDLE_SEGURO = time(18, 15)

PERIODO_ANALISE = "1y"
PERIODO_CORRELACAO = "3y"
INTERVALO = "1d"
MIN_OBSERVACOES = 60
JANELA_ROLLING = 60
BRAPI_TOKEN = os.environ.get("BRAPI_TOKEN", "").strip()


@dataclass(frozen=True)
class AtivoConfig:
    ticker: str
    nome: str
    classe: str
    perfil: str


ATIVOS: tuple[AtivoConfig, ...] = (
    AtivoConfig("KDIF11", "Kinea Infra", "FI-Infra", "renda_fixa"),
    AtivoConfig("GOLD11", "Trend ETF LBMA Ouro", "ETF Commodities", "risco"),
    AtivoConfig("WRLD11", "Investo FTSE Global", "ETF Ações Globais", "risco"),
    AtivoConfig("ALUG11", "ETF Imobiliário Global", "ETF Imobiliário", "risco"),
    AtivoConfig("IRFM11", "ETF IRF-M", "ETF Renda Fixa BR", "renda_fixa"),
    AtivoConfig("USDB11", "ETF Bonds EUA", "ETF Renda Fixa Global", "renda_fixa"),
    AtivoConfig("NUCL11", "ETF Nuclear/Uranium", "ETF Temático", "risco"),
    AtivoConfig("HTEK11", "ETF Health Tech", "ETF Temático", "risco"),
)

ATIVOS_POR_TICKER = {a.ticker: a for a in ATIVOS}
TICKERS = [a.ticker for a in ATIVOS]

# Fatores de contexto, não necessariamente benchmarks oficiais dos ETFs.
CONTEXTO = {
    "USD/BRL": "BRL=X",
    "IBOV": "^BVSP",
    "OURO_USD": "GC=F",
    "S&P500": "^GSPC",
    "US10Y": "^TNX",
}

# Pares economicamente úteis ou úteis para diversificação da carteira.
PARES_ROLLING = [
    ("GOLD11", "USD/BRL"),
    ("GOLD11", "OURO_USD"),
    ("WRLD11", "USD/BRL"),
    ("WRLD11", "S&P500"),
    ("USDB11", "USD/BRL"),
    ("USDB11", "US10Y"),
    ("NUCL11", "HTEK11"),
]

# Pesos por perfil. Cada componente já fica em [-1, +1].
PESOS = {
    "risco": {"tendencia": 0.45, "momentum": 0.35, "volume": 0.20},
    "renda_fixa": {"tendencia": 0.55, "momentum": 0.35, "volume": 0.10},
}


# -----------------------------------------------------------------------------
# Utilidades
# -----------------------------------------------------------------------------


def criar_diretorio_execucao(base_dir: str | Path = ".") -> Path:
    nome = datetime.now(B3_TZ).strftime("%d-%m-%Y_%H-%M-%S")
    caminho = Path(base_dir).expanduser().resolve() / nome
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def checar_versao_yfinance() -> None:
    if yf is None:
        raise RuntimeError(
            "Pacote yfinance não instalado. Rode: pip install --upgrade yfinance"
        )

    versao = getattr(yf, "__version__", "desconhecida")
    print(f"yfinance {versao}")

    try:
        partes = versao.split(".")
        if int(partes[0]) == 0 and int(partes[1]) < 2:
            print(">> Versão antiga detectada. Rode: pip install --upgrade yfinance")
    except (ValueError, IndexError):
        pass


def normalizar_colunas_yahoo(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    if isinstance(out.columns, pd.MultiIndex):
        # yf.download pode retornar MultiIndex mesmo para um ticker.
        out.columns = out.columns.get_level_values(0)

    out = out.loc[:, ~out.columns.duplicated()].copy()

    if "Close" not in out.columns:
        return pd.DataFrame()

    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in out.columns]
    out = out[keep].copy()

    idx = pd.to_datetime(out.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(B3_TZ).tz_localize(None)
    out.index = idx

    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")].sort_index()

    for col in keep:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["Close"])
    return out


def remover_candle_em_formacao(df: pd.DataFrame) -> pd.DataFrame:
    """Descarta candle de hoje quando ainda pode estar em formação."""
    if df.empty:
        return df

    out = df.copy()
    agora = datetime.now(B3_TZ)
    ultima_data = pd.Timestamp(out.index[-1]).date()

    if ultima_data == agora.date() and agora.time() < HORARIO_CANDLE_SEGURO:
        out = out.iloc[:-1].copy()

    return out


def ultimo_numero(valor: object, default: float = math.nan) -> float:
    try:
        x = float(valor)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def fmt_num(valor: float | str, casas: int = 2, vazio: str = "-") -> str:
    if isinstance(valor, str):
        return valor
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return vazio
    if not math.isfinite(x):
        return vazio
    return f"{x:.{casas}f}"


# -----------------------------------------------------------------------------
# Dados de mercado
# -----------------------------------------------------------------------------


def baixar_yahoo(ticker: str, period: str = PERIODO_ANALISE) -> tuple[pd.DataFrame, str | None]:
    if yf is None:
        return pd.DataFrame(), "yfinance não instalado"

    simbolo = f"{ticker}.SA"
    erros: list[str] = []

    try:
        df = yf.download(
            simbolo,
            period=period,
            interval=INTERVALO,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        df = normalizar_colunas_yahoo(df)
        if not df.empty:
            return remover_candle_em_formacao(df), None
        erros.append("yf.download sem dados")
    except Exception as exc:  # noqa: BLE001 - queremos fallback e mensagem amigável
        erros.append(f"yf.download: {exc}")

    try:
        df = yf.Ticker(simbolo).history(
            period=period,
            interval=INTERVALO,
            auto_adjust=True,
            actions=False,
        )
        df = normalizar_colunas_yahoo(df)
        if not df.empty:
            return remover_candle_em_formacao(df), None
        erros.append("Ticker.history sem dados")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"Ticker.history: {exc}")

    return pd.DataFrame(), " | ".join(erros)


def baixar_brapi(ticker: str, period: str = PERIODO_ANALISE) -> tuple[pd.DataFrame, str | None]:
    url = f"https://brapi.dev/api/quote/{ticker}"
    params = {"range": period, "interval": INTERVALO}
    if BRAPI_TOKEN:
        params["token"] = BRAPI_TOKEN

    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results") or []
        if not results:
            return pd.DataFrame(), "brapi: resposta sem results"

        dados = results[0].get("historicalDataPrice") or []
        if not dados:
            return pd.DataFrame(), "brapi: historicalDataPrice vazio"

        df = pd.DataFrame(dados)
        if "date" not in df.columns or "close" not in df.columns:
            return pd.DataFrame(), "brapi: campos date/close ausentes"

        data_utc = pd.to_datetime(df["date"], unit="s", utc=True, errors="coerce")
        df["date"] = data_utc.dt.tz_convert(B3_TZ).dt.tz_localize(None)

        rename = {"close": "Close", "volume": "Volume", "open": "Open", "high": "High", "low": "Low"}
        df = df.rename(columns=rename).set_index("date")

        keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
        df = df[keep].copy()
        for col in keep:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["Close"])
        df = df[~df.index.isna()]
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return remover_candle_em_formacao(df), None

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        return pd.DataFrame(), f"brapi HTTP {status}: {exc}"
    except requests.RequestException as exc:
        return pd.DataFrame(), f"brapi conexão: {exc}"
    except (ValueError, KeyError, TypeError) as exc:
        return pd.DataFrame(), f"brapi resposta inválida: {exc}"


def obter_dados(ticker: str, period: str = PERIODO_ANALISE) -> tuple[pd.DataFrame, str, list[str]]:
    erros: list[str] = []

    df, erro = baixar_yahoo(ticker, period=period)
    if erro:
        erros.append(erro)
    if not df.empty and len(df) >= MIN_OBSERVACOES:
        return df, "Yahoo Finance", erros

    df, erro = baixar_brapi(ticker, period=period)
    if erro:
        erros.append(erro)
    if not df.empty and len(df) >= MIN_OBSERVACOES:
        return df, "brapi", erros

    return pd.DataFrame(), "FALHOU", erros


def baixar_contexto_yahoo(symbol: str, period: str = PERIODO_CORRELACAO) -> pd.Series:
    if yf is None:
        return pd.Series(dtype=float)

    try:
        df = yf.download(
            symbol,
            period=period,
            interval=INTERVALO,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        df = normalizar_colunas_yahoo(df)
        df = remover_candle_em_formacao(df)
        if df.empty:
            return pd.Series(dtype=float)
        return df["Close"].astype(float).rename(symbol)
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)


# -----------------------------------------------------------------------------
# Indicadores
# -----------------------------------------------------------------------------


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = close.astype(float)
    delta = close.diff()

    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)

    avg_gain = ganho.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = perda.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))

    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    out = out.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    if not {"High", "Low", "Close"}.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)

    prev_close = df["Close"].shift(1)
    componentes = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return componentes.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    if tr.empty:
        return tr
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def detectar_cruzamento(mm_curta: pd.Series, mm_longa: pd.Series) -> str:
    valid = pd.concat([mm_curta, mm_longa], axis=1).dropna()
    if len(valid) < 2:
        return "-"

    curta_ant, curta_atual = valid.iloc[-2, 0], valid.iloc[-1, 0]
    longa_ant, longa_atual = valid.iloc[-2, 1], valid.iloc[-1, 1]

    if curta_ant <= longa_ant and curta_atual > longa_atual:
        return "ALTA hoje"
    if curta_ant >= longa_ant and curta_atual < longa_atual:
        return "BAIXA hoje"
    return "-"


def estado_bollinger(preco: float, media: float, superior: float, inferior: float) -> str:
    if not all(math.isfinite(x) for x in (preco, media, superior, inferior)):
        return "-"
    if preco >= superior:
        return "acima/superior"
    if preco <= inferior:
        return "abaixo/inferior"
    if preco >= media:
        return "meio superior"
    return "meio inferior"


def estado_rsi(valor: float) -> str:
    if not math.isfinite(valor):
        return "-"
    if valor >= 70:
        return "forte/esticado"
    if valor >= 55:
        return "momentum altista"
    if valor > 45:
        return "neutro"
    if valor > 30:
        return "momentum baixista"
    return "fraco/esticado"


def classificar_vies(score: float) -> str:
    if score >= 75:
        return "FORTE ALTA"
    if score >= 60:
        return "ALTA"
    if score > 40:
        return "NEUTRO"
    if score > 25:
        return "BAIXA"
    return "FORTE BAIXA"


def calcular_score(
    perfil: str,
    tendencia: float,
    momentum: float,
    volume: float,
) -> tuple[float, float]:
    pesos = PESOS.get(perfil, PESOS["risco"])
    bruto = (
        pesos["tendencia"] * tendencia
        + pesos["momentum"] * momentum
        + pesos["volume"] * volume
    )
    bruto = float(np.clip(bruto, -1.0, 1.0))
    score = 50.0 + 50.0 * bruto
    return round(score, 1), bruto


# -----------------------------------------------------------------------------
# Análise de ativo
# -----------------------------------------------------------------------------


def analisar(config: AtivoConfig) -> dict[str, object]:
    ticker = config.ticker
    df, fonte, erros = obter_dados(ticker)

    if df.empty:
        return {
            "Ativo": ticker,
            "Nome": config.nome,
            "Classe": config.classe,
            "Fonte": "FALHOU",
            "Viés": "sem dados",
            "Erros": " | ".join(erros),
        }

    close = df["Close"].astype(float)
    preco = float(close.iloc[-1])
    data_ref = pd.Timestamp(close.index[-1]).strftime("%d/%m/%Y")

    mm9 = close.rolling(9, min_periods=9).mean()
    mm21 = close.rolling(21, min_periods=21).mean()

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd - macd_signal

    rsi14_series = rsi(close, 14)
    rsi14 = ultimo_numero(rsi14_series.iloc[-1])

    mm20 = close.rolling(20, min_periods=20).mean()
    desvio20 = close.rolling(20, min_periods=20).std(ddof=0)
    banda_sup = mm20 + 2 * desvio20
    banda_inf = mm20 - 2 * desvio20

    retorno_dia = close.pct_change().iloc[-1]
    retorno_5d = close.pct_change(5).iloc[-1]
    retorno_21d = close.pct_change(21).iloc[-1]

    # Componente 1: tendência [-1, +1]
    regime_mm = 1.0 if mm9.iloc[-1] > mm21.iloc[-1] else -1.0
    slope_21 = mm21.pct_change(5).iloc[-1]
    slope_sign = 1.0 if pd.notna(slope_21) and slope_21 > 0 else -1.0
    componente_tendencia = 0.60 * regime_mm + 0.40 * slope_sign

    # Componente 2: momentum [-1, +1]
    macd_value = ultimo_numero(macd_hist.iloc[-1], 0.0)
    macd_sign = 1.0 if macd_value > 0 else -1.0 if macd_value < 0 else 0.0
    rsi_momentum = float(np.clip((rsi14 - 50.0) / 20.0, -1.0, 1.0)) if math.isfinite(rsi14) else 0.0
    componente_momentum = 0.60 * macd_sign + 0.40 * rsi_momentum

    # Componente 3: volume apenas confirma direção; não cria direção sozinho.
    vol_rel = math.nan
    componente_volume = 0.0
    if "Volume" in df.columns:
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        media_vol_21 = vol.rolling(21, min_periods=21).mean().iloc[-1]
        vol_atual = vol.iloc[-1]
        if pd.notna(media_vol_21) and media_vol_21 > 0 and pd.notna(vol_atual):
            vol_rel = float(vol_atual / media_vol_21)
            if vol_rel > 1.0 and pd.notna(retorno_dia) and retorno_dia != 0:
                forca = float(np.clip((vol_rel - 1.0) / 1.5, 0.0, 1.0))
                componente_volume = math.copysign(forca, float(retorno_dia))

    score, bruto = calcular_score(
        config.perfil,
        componente_tendencia,
        componente_momentum,
        componente_volume,
    )

    vies = classificar_vies(score)
    cruzamento = detectar_cruzamento(mm9, mm21)
    tendencia_mm = "alta" if mm9.iloc[-1] > mm21.iloc[-1] else "baixa"

    atr14 = atr(df, 14)
    atr_pct = math.nan
    if not atr14.empty:
        atr_val = ultimo_numero(atr14.iloc[-1])
        if math.isfinite(atr_val) and preco > 0:
            atr_pct = 100.0 * atr_val / preco

    vol20 = close.pct_change().rolling(20, min_periods=20).std().iloc[-1]
    vol_anual = float(vol20 * np.sqrt(252) * 100) if pd.notna(vol20) else math.nan

    boll = estado_bollinger(
        preco,
        ultimo_numero(mm20.iloc[-1]),
        ultimo_numero(banda_sup.iloc[-1]),
        ultimo_numero(banda_inf.iloc[-1]),
    )

    alertas: list[str] = []
    if math.isfinite(rsi14) and rsi14 >= 70:
        alertas.append("RSI elevado; força não implica venda automática")
    elif math.isfinite(rsi14) and rsi14 <= 30:
        alertas.append("RSI baixo; fraqueza não implica compra automática")

    if boll in {"acima/superior", "abaixo/inferior"}:
        alertas.append("preço fora/na extremidade das Bandas de Bollinger")

    if config.ticker == "KDIF11":
        alertas.append("FI-Infra: distribuições e liquidez exigem leitura diferente de ETF")

    return {
        "Ativo": ticker,
        "Nome": config.nome,
        "Classe": config.classe,
        "Fonte": fonte,
        "Data": data_ref,
        "Preço": round(preco, 2),
        "Ret. 1D %": round(float(retorno_dia) * 100, 2) if pd.notna(retorno_dia) else math.nan,
        "Ret. 5D %": round(float(retorno_5d) * 100, 2) if pd.notna(retorno_5d) else math.nan,
        "Ret. 21D %": round(float(retorno_21d) * 100, 2) if pd.notna(retorno_21d) else math.nan,
        "MM9>MM21": tendencia_mm,
        "Cruzamento": cruzamento,
        "RSI14": round(rsi14, 1) if math.isfinite(rsi14) else math.nan,
        "RSI estado": estado_rsi(rsi14),
        "MACD hist": round(macd_value, 4),
        "Bollinger": boll,
        "Vol. rel.": round(vol_rel, 2) if math.isfinite(vol_rel) else math.nan,
        "ATR14 %": round(atr_pct, 2) if math.isfinite(atr_pct) else math.nan,
        "Vol. 20d anual %": round(vol_anual, 1) if math.isfinite(vol_anual) else math.nan,
        "Score": score,
        "Viés": vies,
        "Tendência comp.": round(componente_tendencia, 3),
        "Momentum comp.": round(componente_momentum, 3),
        "Volume comp.": round(componente_volume, 3),
        "Bruto": round(bruto, 3),
        "Alertas": "; ".join(alertas) if alertas else "-",
        "Erros": " | ".join(erros) if erros else "-",
    }


# -----------------------------------------------------------------------------
# HTML
# -----------------------------------------------------------------------------


def cor_vies(vies: str) -> tuple[str, str]:
    return {
        "FORTE ALTA": ("#DCFCE7", "#166534"),
        "ALTA": ("#ECFDF3", "#237A45"),
        "NEUTRO": ("#F3F4F6", "#4B5563"),
        "BAIXA": ("#FEF2F2", "#B42318"),
        "FORTE BAIXA": ("#FEE2E2", "#991B1B"),
        "sem dados": ("#F3F4F6", "#6B7280"),
    }.get(vies, ("#F3F4F6", "#4B5563"))


def gerar_html(resultados: Iterable[dict[str, object]], caminho: Path) -> Path:
    agora = datetime.now(B3_TZ)
    linhas: list[str] = []

    for r in resultados:
        ticker = html.escape(str(r.get("Ativo", "-")))
        classe = html.escape(str(r.get("Classe", "-")))
        vies = str(r.get("Viés", "sem dados"))
        bg, fg = cor_vies(vies)

        if "Preço" not in r:
            erro = html.escape(str(r.get("Erros", "sem detalhes")))
            linhas.append(
                f"<tr><td class='tk'>{ticker}</td><td>{classe}</td>"
                f"<td colspan='11' class='muted'>sem dados — {erro}</td>"
                f"<td><span class='pill' style='background:{bg};color:{fg}'>{html.escape(vies)}</span></td></tr>"
            )
            continue

        score = float(r["Score"])
        score_class = "score-high" if score >= 60 else "score-low" if score <= 40 else "score-mid"

        vol_rel = r.get("Vol. rel.", math.nan)
        vol_txt = fmt_num(vol_rel, 2)
        vol_class = "strong" if isinstance(vol_rel, (int, float)) and math.isfinite(float(vol_rel)) and float(vol_rel) >= 1.5 else ""

        linhas.append(
            "<tr>"
            f"<td class='tk'>{ticker}</td>"
            f"<td>{classe}</td>"
            f"<td>{html.escape(str(r['Data']))}</td>"
            f"<td>R$ {float(r['Preço']):.2f}</td>"
            f"<td>{fmt_num(r['Ret. 21D %'], 2)}%</td>"
            f"<td>{html.escape(str(r['MM9>MM21']))}</td>"
            f"<td>{html.escape(str(r['Cruzamento']))}</td>"
            f"<td>{fmt_num(r['RSI14'], 1)}</td>"
            f"<td>{html.escape(str(r['RSI estado']))}</td>"
            f"<td>{'+' if float(r['MACD hist']) > 0 else ''}{fmt_num(r['MACD hist'], 4)}</td>"
            f"<td>{html.escape(str(r['Bollinger']))}</td>"
            f"<td class='{vol_class}'>{vol_txt}</td>"
            f"<td class='{score_class}'>{score:.1f}</td>"
            f"<td><span class='pill' style='background:{bg};color:{fg}'>{html.escape(vies)}</span></td>"
            "</tr>"
        )

    html_doc = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel técnico de ativos — {agora:%d/%m/%Y}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f7f7f5;
  color: #18181b;
  margin: 0;
  padding: 28px;
}}
.wrap {{ max-width: 1500px; margin: 0 auto; }}
h1 {{ font-size: 22px; margin: 0 0 6px; }}
.sub {{ margin: 0 0 18px; color: #71717a; font-size: 13px; }}
.card {{
  background: white;
  border: 1px solid #e4e4e7;
  border-radius: 12px;
  overflow-x: auto;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
table {{ width: 100%; border-collapse: collapse; min-width: 1280px; font-size: 13px; }}
th {{
  position: sticky;
  top: 0;
  background: #f4f4f5;
  text-align: left;
  padding: 10px 12px;
  color: #52525b;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .035em;
  white-space: nowrap;
}}
td {{ border-top: 1px solid #eeeeef; padding: 10px 12px; white-space: nowrap; }}
.tk {{ font-weight: 700; }}
.muted {{ color: #71717a; white-space: normal; }}
.strong {{ font-weight: 800; }}
.score-high {{ color: #166534; font-weight: 800; }}
.score-mid {{ color: #52525b; font-weight: 800; }}
.score-low {{ color: #991b1b; font-weight: 800; }}
.pill {{ display:inline-block; padding:4px 9px; border-radius:999px; font-size:12px; font-weight:700; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; margin-top:16px; }}
.info {{ background:white; border:1px solid #e4e4e7; border-radius:12px; padding:16px; }}
.info h2 {{ font-size:14px; margin:0 0 10px; }}
.info p, .info li {{ font-size:12.5px; line-height:1.55; color:#52525b; }}
.info ul {{ margin:8px 0 0; padding-left:18px; }}
code {{ background:#f4f4f5; padding:1px 4px; border-radius:4px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Painel técnico de ativos</h1>
  <p class="sub">Executado em {agora:%d/%m/%Y %H:%M} · fuso America/Sao_Paulo · candle diário concluído · Yahoo Finance com fallback brapi</p>

  <div class="card">
    <table>
      <thead>
        <tr>
          <th>Ativo</th><th>Classe</th><th>Data</th><th>Preço</th><th>Ret. 21D</th>
          <th>MM9x21</th><th>Cruzamento</th><th>RSI14</th><th>RSI estado</th>
          <th>MACD hist</th><th>Bollinger</th><th>Vol. rel.</th><th>Score</th><th>Viés</th>
        </tr>
      </thead>
      <tbody>{''.join(linhas)}</tbody>
    </table>
  </div>

  <div class="grid">
    <div class="info">
      <h2>Como o score funciona</h2>
      <p>O score vai de 0 a 100 e combina três dimensões independentes:</p>
      <ul>
        <li><b>Tendência:</b> posição e inclinação de MM9/MM21.</li>
        <li><b>Momentum:</b> MACD + RSI tratado como força, não como gatilho automático de reversão.</li>
        <li><b>Volume:</b> apenas confirma a direção do movimento quando está acima da média.</li>
      </ul>
    </div>
    <div class="info">
      <h2>Faixas do viés</h2>
      <ul>
        <li>75–100: <b>FORTE ALTA</b></li>
        <li>60–74,9: <b>ALTA</b></li>
        <li>40,1–59,9: <b>NEUTRO</b></li>
        <li>25,1–40: <b>BAIXA</b></li>
        <li>0–25: <b>FORTE BAIXA</b></li>
      </ul>
    </div>
    <div class="info">
      <h2>Cuidados</h2>
      <ul>
        <li>RSI &gt; 70 não significa venda automática.</li>
        <li>Tocar a banda superior de Bollinger não significa ativo “caro”.</li>
        <li>KDIF11 é FI-Infra, não ETF; distribuições e liquidez mudam a leitura.</li>
        <li>O score descreve estado técnico. Não é recomendação de investimento.</li>
      </ul>
    </div>
  </div>
</div>
</body>
</html>
"""

    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(html_doc, encoding="utf-8")
    return caminho.resolve()


# -----------------------------------------------------------------------------
# Correlação
# -----------------------------------------------------------------------------


def coletar_series_fechamento() -> tuple[pd.DataFrame, pd.DataFrame]:
    series: dict[str, pd.Series] = {}

    for config in ATIVOS:
        df, fonte, _ = obter_dados(config.ticker, period=PERIODO_CORRELACAO)
        if not df.empty:
            series[config.ticker] = df["Close"].astype(float).rename(config.ticker)
        else:
            print(f"  aviso: sem série para {config.ticker} ({fonte})")

    for nome, ysym in CONTEXTO.items():
        s = baixar_contexto_yahoo(ysym, period=PERIODO_CORRELACAO)
        if not s.empty:
            series[nome] = s.rename(nome)
        else:
            print(f"  aviso: não consegui baixar contexto {nome} ({ysym})")

    precos = pd.concat(series.values(), axis=1).sort_index() if series else pd.DataFrame()
    if precos.empty:
        return pd.DataFrame(), pd.DataFrame()

    retornos = np.log(precos / precos.shift(1))
    retornos = retornos.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    return precos, retornos


def gerar_heatmap(retornos: pd.DataFrame, caminho: Path, mostrar: bool = False) -> pd.DataFrame:
    import matplotlib

    if not mostrar:
        matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    import seaborn as sns

    # pandas.corr usa observações pareadas; min_periods evita relações frágeis.
    corr = retornos.corr(method="pearson", min_periods=60)

    fig = plt.figure(figsize=(11, 9))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)

    sns.heatmap(
        corr,
        mask=mask,
        annot=True,
        fmt=".2f",
        cmap="RdBu_r",
        vmin=-1,
        vmax=1,
        center=0,
        square=True,
        linewidths=0.5,
        cbar_kws={"shrink": 0.8, "label": "Correlação de Pearson"},
        annot_kws={"size": 9},
    )

    plt.title("Correlação entre retornos logarítmicos diários", fontsize=13, pad=14)
    fig.text(
        0.5,
        0.018,
        "Correlação histórica não garante hedge futuro. Cada célula usa apenas datas disponíveis para o respectivo par (mínimo 60 observações).",
        ha="center",
        va="bottom",
        fontsize=8.5,
        wrap=True,
    )
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    plt.savefig(caminho, dpi=140, bbox_inches="tight")

    if mostrar:
        plt.show()
    plt.close(fig)
    return corr


def gerar_rolling(retornos: pd.DataFrame, caminho: Path, mostrar: bool = False) -> None:
    import matplotlib

    if not mostrar:
        matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    pares_validos = [(a, b) for a, b in PARES_ROLLING if a in retornos.columns and b in retornos.columns]
    if not pares_validos:
        print("  correlação móvel: nenhum par disponível")
        return

    fig = plt.figure(figsize=(12, 7))
    plotados = 0

    for a, b in pares_validos:
        pair = retornos[[a, b]].dropna()
        if len(pair) < JANELA_ROLLING:
            print(f"  aviso: {a} x {b} tem apenas {len(pair)} observações em comum")
            continue

        roll = pair[a].rolling(JANELA_ROLLING, min_periods=JANELA_ROLLING).corr(pair[b])
        plt.plot(roll.index, roll, label=f"{a} × {b}", linewidth=1.5)
        plotados += 1

    if plotados == 0:
        plt.close(fig)
        print("  correlação móvel: dados insuficientes para os pares")
        return

    plt.axhline(0, linewidth=0.8, linestyle="--", alpha=0.7)
    plt.axhspan(0.5, 1, alpha=0.08, zorder=0)
    plt.axhspan(-1, -0.5, alpha=0.08, zorder=0)
    plt.ylim(-1, 1)
    plt.title(f"Correlação móvel — janela de {JANELA_ROLLING} pregões", fontsize=13, pad=12)
    plt.ylabel("Correlação")
    plt.legend(loc="best", fontsize=8.5, framealpha=0.9)
    plt.grid(alpha=0.2)
    fig.text(
        0.5,
        0.015,
        "Cada par é alinhado por data antes do cálculo. Mudanças de regime podem alterar rapidamente a correlação.",
        ha="center",
        fontsize=8.5,
    )
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    plt.savefig(caminho, dpi=140, bbox_inches="tight")

    if mostrar:
        plt.show()
    plt.close(fig)


def analise_correlacao(diretorio_saida: Path, mostrar: bool = False) -> None:
    print("\nColetando séries para correlação...")
    _, retornos = coletar_series_fechamento()

    if retornos.shape[1] < 2:
        print("  dados insuficientes para correlação")
        return

    # Quantidade de linhas úteis no conjunto total; não chamamos isto de "dias em comum".
    print(f"  séries disponíveis: {retornos.shape[1]}")
    print(f"  datas com pelo menos uma série válida: {retornos.shape[0]}")

    caminho_heatmap = diretorio_saida / "asset_correlation.png"
    caminho_rolling = diretorio_saida / "rolling_asset_correlation.png"

    corr = gerar_heatmap(retornos, caminho_heatmap, mostrar=mostrar)
    gerar_rolling(retornos, caminho_rolling, mostrar=mostrar)

    print(f"  heatmap salvo: {caminho_heatmap.resolve()}")
    if caminho_rolling.exists():
        print(f"  correlação móvel salva: {caminho_rolling.resolve()}")

    print("\nMatriz de correlação:")
    print(corr.round(2).to_string())


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Painel técnico diário de ativos da B3")
    parser.add_argument("--corr", action="store_true", help="gera matriz e correlação móvel")
    parser.add_argument("--show", action="store_true", help="exibe gráficos além de salvá-los")
    parser.add_argument("--no-open", action="store_true", help="não abre o HTML automaticamente")
    parser.add_argument(
        "--output",
        default=".",
        help="diretório base de saída (padrão: diretório atual)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    try:
        checar_versao_yfinance()
    except RuntimeError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2

    print("\nAnalisando ativos...")
    resultados = [analisar(config) for config in ATIVOS]
    tabela = pd.DataFrame(resultados)

    colunas_console = [
        c
        for c in (
            "Ativo",
            "Classe",
            "Fonte",
            "Data",
            "Preço",
            "Ret. 21D %",
            "MM9>MM21",
            "Cruzamento",
            "RSI14",
            "Vol. rel.",
            "Score",
            "Viés",
        )
        if c in tabela.columns
    ]

    print(f"\nPainel técnico — {datetime.now(B3_TZ):%d/%m/%Y %H:%M}")
    print(tabela[colunas_console].to_string(index=False))

    diretorio_saida = criar_diretorio_execucao(args.output)
    print(f"\nDiretório da execução: {diretorio_saida}")

    caminho_html = gerar_html(resultados, diretorio_saida / "painel_ativos.html")
    print(f"Painel visual gerado: {caminho_html}")

    falhas = [r for r in resultados if r.get("Fonte") == "FALHOU"]
    if falhas:
        print("\nAlguns ativos falharam:")
        for r in falhas:
            print(f"  - {r['Ativo']}: {r.get('Erros', '-')}")
        print("\nChecklist:")
        print("  1. pip install --upgrade yfinance pandas numpy requests")
        print("  2. Se necessário, configure BRAPI_TOKEN")
        print("  3. Verifique VPN/proxy/firewall da rede")

    if not args.no_open:
        try:
            webbrowser.open(caminho_html.as_uri())
            print("Abrindo painel no navegador...")
        except Exception as exc:  # noqa: BLE001
            print(f"Não foi possível abrir o navegador automaticamente: {exc}")

    if args.corr:
        analise_correlacao(diretorio_saida, mostrar=args.show)

    print("\nLeitura correta: o score representa viés técnico, não recomendação de compra/venda.")
    print("Ferramenta educativa — não constitui recomendação de investimento.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
