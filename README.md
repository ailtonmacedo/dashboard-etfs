# Dashboard Técnico de Ativos da B3

Este repositório contém um script em Python para montar um painel técnico diário de ativos negociados na B3.

O projeto foi criado para oferecer uma leitura rápida e padronizada do estado técnico de cada ativo, combinando tendência, momentum, volatilidade e confirmação por volume. O resultado é apresentado em um relatório HTML e, opcionalmente, em gráficos de correlação.

> **Importante:** o painel trabalha com **viés técnico**, e não com recomendações automáticas de compra ou venda.

## Ativos acompanhados

A configuração padrão inclui ativos como:

| Ativo | Classe | Perfil técnico |
|---|---|---|
| KDIF11 | FI-Infra | Renda fixa |
| GOLD11 | ETF de commodities | Risco |
| WRLD11 | ETF de ações globais | Risco |
| JURO11 | ETF de renda fixa | Renda fixa |
| FIXA11 | ETF de renda fixa | Renda fixa |
| USDB11 | ETF de renda fixa global | Renda fixa |

> KDIF11 é tratado separadamente como **FI-Infra**, e não como ETF.

A lista pode ser alterada diretamente na configuração de ativos do script.

---

## O que o projeto faz

O script:

- busca cotações diárias dos ativos configurados;
- utiliza somente o último candle diário considerado concluído;
- calcula indicadores de tendência, momentum, volatilidade e volume;
- detecta cruzamentos reais entre as médias móveis de 9 e 21 períodos;
- calcula um score técnico normalizado de `0` a `100`;
- classifica cada ativo por viés técnico;
- gera um painel visual em HTML;
- informa a data da última cotação utilizada;
- registra falhas das fontes de dados;
- pode gerar uma matriz de correlação e uma análise de correlação móvel.

---

## Indicadores calculados

Para cada ativo, o script pode calcular:

- retorno de 1 pregão;
- retorno de 5 pregões;
- retorno de 21 pregões;
- média móvel de 9 períodos;
- média móvel de 21 períodos;
- cruzamento real MM9 × MM21;
- RSI de 14 períodos;
- MACD 12/26/9;
- histograma do MACD;
- Bandas de Bollinger de 20 períodos;
- volume relativo contra a média de 21 pregões;
- ATR de 14 períodos em percentual;
- volatilidade anualizada.

---

## Score técnico

O painel utiliza um score técnico normalizado de:

```text
0 a 100
```

O score combina três dimensões principais:

1. **Tendência**
   - posição da MM9 em relação à MM21;
   - inclinação da média.

2. **Momentum**
   - MACD;
   - RSI.

3. **Volume**
   - utilizado como confirmação do movimento;
   - volume alto não gera sozinho um sinal de alta ou baixa.

O resultado representa o **estado técnico atual do ativo**.

Ele não deve ser interpretado isoladamente como ordem de compra ou venda.

### Classificação do viés

| Score | Viés |
|---:|---|
| 75 a 100 | FORTE ALTA |
| 60 a 74,9 | ALTA |
| acima de 40 até abaixo de 60 | NEUTRO |
| acima de 25 até 40 | BAIXA |
| 0 a 25 | FORTE BAIXA |

---

## RSI

O RSI não é tratado de forma simplista como:

```text
RSI > 70 = vender
RSI < 30 = comprar
```

Um ativo forte pode permanecer sobrecomprado durante uma tendência de alta.

Da mesma forma, um ativo fraco pode permanecer sobrevendido durante uma tendência de baixa.

O RSI é utilizado principalmente como indicador de momentum.

---

## Bandas de Bollinger

Tocar ou ultrapassar a banda superior não significa automaticamente que o ativo está caro.

Da mesma forma, tocar a banda inferior não significa automaticamente que o ativo está barato.

As Bandas de Bollinger são utilizadas principalmente como referência de:

- volatilidade;
- posição relativa do preço;
- expansão ou contração do movimento.

---

## Candle diário concluído

Para evitar distorções durante o pregão, o script tenta trabalhar somente com candles diários concluídos.

Isso é especialmente importante para:

- volume relativo;
- RSI;
- MACD;
- médias móveis;
- volatilidade;
- Bandas de Bollinger.

O projeto utiliza o módulo:

```python
from zoneinfo import ZoneInfo
```

`zoneinfo` faz parte da biblioteca padrão do Python a partir da versão **3.9**.

Por isso, este projeto requer:

```text
Python 3.9+
```

A versão recomendada é:

```text
Python 3.12
```

---

# Ambiente Python com uv

Este projeto utiliza **uv** para gerenciamento do Python, ambiente virtual e dependências.

Não é recomendado instalar as dependências diretamente no Python global com:

```bash
pip install ...
```

Em instalações gerenciadas pelo `uv`, isso pode gerar:

```text
error: externally-managed-environment
```

Isso é esperado e evita alterações no Python global.

---

## Verificar o uv

```bash
uv --version
```

Se necessário, consulte a documentação oficial do `uv` para instalação.

---

## Verificar o Python disponível

```bash
uv python list
```

Também é possível verificar:

```bash
python3 --version
```

A versão recomendada para este projeto é Python 3.12.

Se necessário, instale-a pelo próprio `uv`:

```bash
uv python install 3.12
```

---

# Configuração do projeto

## Primeira configuração

Entre no diretório do projeto:

```bash
cd dashboard-etfs
```

### Se o projeto já possui `pyproject.toml`

Basta executar:

```bash
uv sync
```

O `uv` criará ou atualizará automaticamente:

```text
.venv/
```

e instalará as dependências declaradas no projeto.

---

## Criando o projeto com uv pela primeira vez

Se ainda não existir um `pyproject.toml`, inicialize:

```bash
uv init
```

Depois adicione as dependências:

```bash
uv add yfinance pandas numpy requests matplotlib seaborn
```

Isso criará ou atualizará:

```text
pyproject.toml
uv.lock
```

e manterá o ambiente virtual sincronizado.

---

## Criar manualmente o ambiente virtual

Também é possível criar explicitamente o `.venv`:

```bash
uv venv --python 3.12
```

Para ativá-lo no Linux/macOS:

```bash
source .venv/bin/activate
```

Depois confirme:

```bash
python --version
which python
```

A saída deve apontar para algo semelhante a:

```text
dashboard-etfs/.venv/bin/python
```

Com o ambiente ativo, as dependências podem ser instaladas com:

```bash
uv pip install yfinance pandas numpy requests matplotlib seaborn
```

> Para projetos mantidos com `pyproject.toml`, prefira `uv add` e `uv sync`.

---

# Estrutura recomendada

```text
dashboard-etfs/
├── dashboard_etfs.py
├── README.md
├── pyproject.toml
├── uv.lock
└── .venv/
```

O diretório `.venv` não deve ser versionado.

Adicione ao `.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
```

---

# Como executar

A forma recomendada é utilizar `uv run`.

## Painel técnico principal

```bash
uv run python dashboard_etfs.py
```

Esse comando:

- baixa os dados;
- calcula os indicadores;
- calcula o score técnico;
- cria uma pasta para a execução;
- gera o painel HTML;
- tenta abrir automaticamente o resultado no navegador.

---

## Executar sem ativar o ambiente virtual

Não é necessário rodar:

```bash
source .venv/bin/activate
```

antes de cada execução.

O próprio `uv` seleciona o ambiente correto:

```bash
uv run python dashboard_etfs.py
```

---

## Executar com ambiente virtual ativado

Se o `.venv` já estiver ativo:

```bash
python dashboard_etfs.py
```

também funciona.

---

## Não abrir o navegador automaticamente

```bash
uv run python dashboard_etfs.py --no-open
```

---

# Análise de correlação

Para gerar também os gráficos de correlação:

```bash
uv run python dashboard_etfs.py --corr
```

Esse modo pode gerar:

- matriz de correlação;
- heatmap das correlações;
- correlações móveis configuradas no script.

---

## Exibir os gráficos na tela

```bash
uv run python dashboard_etfs.py --corr --show
```

Os arquivos continuam sendo salvos normalmente.

---

## Escolher o diretório base de saída

```bash
uv run python dashboard_etfs.py --output ./resultados
```

Também é possível combinar argumentos:

```bash
uv run python dashboard_etfs.py \
  --corr \
  --no-open \
  --output ./resultados
```

---

# Arquivos gerados

Cada execução cria uma pasta com o padrão:

```text
DD-MM-AAAA_HH-MM-SS
```

Exemplo:

```text
06-10-2026_18-30-15/
```

Estrutura típica:

```text
06-10-2026_18-30-15/
├── painel_ativos.html
├── asset_correlation.png
└── rolling_asset_correlation.png
```

O nome exato do painel pode variar de acordo com a configuração do script.

---

# Fontes de dados

O script tenta utilizar as fontes nesta ordem:

1. Yahoo Finance via `yf.download`;
2. Yahoo Finance via `Ticker().history`;
3. brapi.dev como fallback.

O histórico utilizado na análise técnica é maior que a janela necessária para os indicadores, evitando que médias, RSI e MACD sejam calculados com poucas observações.

---

# Token opcional da brapi

O token da brapi é opcional.

Se disponível, configure:

```text
BRAPI_TOKEN
```

## Linux / macOS

```bash
export BRAPI_TOKEN=seu_token
```

## Windows CMD

```cmd
set BRAPI_TOKEN=seu_token
```

## Windows PowerShell

```powershell
$env:BRAPI_TOKEN="seu_token"
```

Depois execute normalmente:

```bash
uv run python dashboard_etfs.py
```

---

# Análise de correlação

A correlação é calculada sobre **retornos diários**, e não simplesmente sobre os preços dos ativos.

O objetivo é avaliar como os movimentos dos ativos estiveram relacionados durante o período analisado.

O projeto pode utilizar fatores de contexto como:

- USD/BRL;
- Ibovespa;
- ouro;
- mercado acionário americano;
- juros americanos.

A janela padrão da correlação móvel pode ser configurada no próprio script.

Cada par deve ser alinhado pelas datas disponíveis antes do cálculo.

---

## Como interpretar correlação

A correlação varia de:

```text
-1 a +1
```

### Próxima de +1

Os ativos tenderam a apresentar retornos na mesma direção.

### Próxima de 0

Existe pouca relação linear entre os retornos durante o período analisado.

### Próxima de -1

Os ativos tenderam a apresentar movimentos em direções opostas.

> Correlação histórica não garante comportamento futuro e não deve ser interpretada isoladamente como proteção ou hedge.

---

# Atualizar dependências

Para atualizar o ambiente conforme o projeto:

```bash
uv sync --upgrade
```

Para atualizar uma dependência específica:

```bash
uv lock --upgrade-package yfinance
uv sync
```

---

# Diagnóstico do ambiente

Caso o script apresente problemas, rode:

```bash
uv --version
uv python list
uv run python --version
```

Verifique se as principais dependências estão disponíveis:

```bash
uv run python -c "import yfinance, pandas, numpy, requests, matplotlib, seaborn; print('OK')"
```

Se tudo estiver correto, a saída será:

```text
OK
```

---

# Erro: No module named zoneinfo

Se aparecer:

```text
ModuleNotFoundError: No module named 'zoneinfo'
```

confirme a versão:

```bash
python --version
```

ou:

```bash
uv run python --version
```

O projeto precisa de Python 3.9 ou superior.

Com `uv`, a solução recomendada é:

```bash
uv python install 3.12
uv venv --python 3.12
uv sync
```

Depois execute:

```bash
uv run python dashboard_etfs.py
```

---

# Erro: externally-managed-environment

Se aparecer:

```text
error: externally-managed-environment
```

não utilize:

```bash
pip install --break-system-packages
```

A solução correta neste projeto é instalar as dependências dentro do ambiente gerenciado pelo `uv`.

Use:

```bash
uv sync
```

ou, durante a configuração inicial:

```bash
uv add yfinance pandas numpy requests matplotlib seaborn
```

---

# Fluxo recomendado

Depois de clonar o repositório:

```bash
git clone <URL_DO_REPOSITORIO>
cd dashboard-etfs

uv python install 3.12
uv sync

uv run python dashboard_etfs.py
```

Com análise de correlação:

```bash
uv run python dashboard_etfs.py --corr
```

Esse deve ser o fluxo padrão do projeto.

---

# Aviso importante

Este projeto tem finalidade **educativa e analítica**.

O score, os indicadores e os vieses apresentados:

- não constituem recomendação de investimento;
- não substituem análise fundamentalista;
- não substituem análise macroeconômica;
- não substituem gestão de risco;
- não garantem desempenho futuro.

Use o painel como ferramenta de apoio para organizar informações e comparar o comportamento técnico dos ativos.
