# SPY → SPX 波段期權 Bot

單一 ATM 0DTE 期權表達 SPY/SPX 方向性波段:漲買 Call、跌買 Put,**同一時間只持有一個 position**,用確認反轉 / 停損 / EOD 三道出場盡量貼近峰值出場。這裡是完整的研究 + 執行骨架,對應規格 P1–P6。

> ⚠️ **先讀這段(資料有效性)**
>
> 使用者指示:**2026 是異常("cos")期間,不能拿來訓練/驗證。**
>
> 但本環境唯一的行情來源(IBKR `get_price_history`)有兩個硬限制:
> 1. 每次呼叫 ≤ 1000 根 K;
> 2. **沒有起始日參數 —— 每次呼叫都結束在「現在」**,所以拿不到較舊的 intraday 歷史。日內最多只能回看:5 分 K ≈ 12.8 個交易日、1 分 K ≈ 2.5 天,**全部落在 2026-06 ~ 2026-07**。
>
> 結論:**目前 `bot/data/` 裡的資料全部是 2026,依使用者的規則不可用於正式訓練。** 因此 repo 內的 walk-forward 執行結果只證明「機器能跑、規則正確」,**不是一個被驗證的 edge**。要做真正的驗證,需把一份乾淨的、非 2026 的日內 CSV(六欄:`time,open,high,low,close,volume`)放進 `bot/data/`;程式碼與 IBKR 無耦合,換資料是換一個檔案的事(見 `scripts/fetch_data.py`)。

---

## 規格 → 模組對照

| Phase | 規格 | 模組 |
|---|---|---|
| P1 | 資料 + 成本模型 + 即時監測骨架 | `data.py`, `costs`→`config.CostModel`, `options.py`, `live.py` |
| P2 | 進場偵測 | `signals.entry_signal` + `indicators.py` |
| P3 | 出場(反轉/停損/EOD) | `signals.reversal_or_stop` + `engine.Engine._exit_reason` |
| P4 | Walk-forward 找參數 | `walkforward.py` |
| P5 | 部位大小 → 對齊 $500/天 | `sizing.py` |
| P6 | 移植 SPX | `config.SPX` / `config.spx_run()`(engine 完全 symbol-agnostic) |

## 硬規則怎麼被保證(§8)

- **一個 position**:`engine` 的狀態機在 `pos` 有值時不可能再開新倉;`tests/test_bot.py::test_one_position_at_a_time` 驗證同日成交時間不重疊。
- **無 lookahead**:所有指標都是 causal(`indicators.py`),breakout 位階用「前 N 根」(shift);決策在 K 棒收盤、成交在**下一根開盤**。`test_no_lookahead_past_unaffected_by_future` 用「加入未來 K 棒不改變已平倉交易」來操作型定義並驗證。
- **EOD 一定平倉**:0DTE 不留倉,`eod_flat`(預設 15:55 ET)強制平倉。
- **成本全程扣掉**:spread + slippage + commission 在**進出兩腿**都收,`test_costs_always_reduce_pnl` 驗證零波動來回必虧。

## 期權 P&L 怎麼算(重要假設)

沒有歷史日內 0DTE 期權報價,因此進出場權利金用 **Black-Scholes(r=q=0)** 計算:用當下標的、ATM 履約價、**到 16:00 的剩餘時間**、以及一個 IV。IV 由當日已實現波動估計(`iv_mode="realized"`,含 floor 與 scale)或固定值。這抓住 0DTE 波段最關鍵的兩件事:**移動時的凸性報酬**與**持有時的 theta 流失**。

- 樂觀處:假設能以 mid±(半價差+滑點)成交,未建模盤中報價跳動與流動性衝擊。
- 悲觀/中性處:IV 用已實現估計,通常低估事件前的隱波;成本用零售等級(SPY $0.65/口、$0.02 半價差)。
- 這是「可辯護的近似」,不是真實期權回測。要更嚴謹,把 `options.Pricer` 換成真實期權報價序列即可(介面已隔離)。

## 怎麼跑

```bash
pip install -r bot/requirements.txt
python run_walkforward.py            # SPY:timeframe + 參數 walk-forward → sizing
python run_walkforward.py --spx      # P6:SPX 成本/乘數 profile
python -m pytest tests/ -q           # 或 python tests/test_bot.py
```

即時監測骨架(paper,永不自動下真單):

```python
from bot.config import spy_run
from bot.live import dry_run
dry_run(spy_run(), "bot/data/spy_5min.csv")   # 用 ReplayFeed + PaperBroker 重播
```

`live.py` 的 `IbkrFeed` / `IbkrBroker` 是**刻意留白的 stub**:真正下單要接 `get_option_parameters → get_option_data`(找 ATM 0DTE 合約)+ `create_order_instruction`,且 `IbkrBroker` 預設 `armed=False`,必須人工檢視後明確啟用,避免誤觸真實下單。

## 更新 / 更換資料

```bash
# 1) 用 IBKR get_price_history 取回 JSON(step=FIVE_MINS, step_count=1000, outside_rth=false)
# 2) 轉成 CSV:
python scripts/fetch_data.py raw_5min.json bot/data/spy_5min.csv
```
或直接放入任何來源產生的六欄 CSV。**要滿足「非 2026」的訓練資料需求,就是在這一步換來源。**

## 現況誠實結論

- 系統(P1–P6)可完整執行,不變量有測試守住。
- 目前資料下**沒有**跨足夠 OOS 樣本的正向 edge:5 分 K 的 7 天 OOS 約略打平/微負;2 分 K 只有 1 天 OOS(無統計意義)。SPX profile 因價差較寬,OOS 為負,`sizing` 正確地拒絕放大部位。
- **$500/天目標**的達成邏輯已就緒(`sizing.py`:用 OOS edge 反推口數,受風險預算上限箝制),但在有**被驗證的正 edge**(需非 2026 乾淨資料)之前,不應據此配置真實資金。
