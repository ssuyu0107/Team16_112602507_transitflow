# TransitFlow — 專案概覽與 AI 協作指南

---

## 一、專案大綱

### 這是什麼？

**TransitFlow** 是一門資料庫課程的期末作業（IM2002-DBMGT）。

目標是為一個虛構的「雙網絡交通運營商」建構後端資料庫，並讓一個 **AI 聊天助理**（已預先建好的框架）能夠透過查詢這些資料庫來回答乘客的問題。

使用者可以問：
- *「從 NR01 到 NR05 今天有哪些班車？」*
- *「我的火車誤點 45 分鐘，我能申請賠償嗎？」*
- *「如果 MS05 關閉，從 MS01 到 MS09 最快怎麼走？」*

---

### 三種資料庫

| 資料庫 | 負責的功能 | 涵蓋的資料 |
|---|---|---|
| **PostgreSQL（關聯式）** | 結構化記錄、精確查詢、交易操作 | 車站、班表、座位、使用者、訂票、乘車記錄、付款、評價 |
| **PostgreSQL + pgvector（向量）** | 以「語意意思」搜尋文件（RAG） | 退款政策、票種說明、訂票規則、旅行政策 |
| **Neo4j（圖形）** | 路徑搜尋、換乘路線、延誤影響分析 | 地鐵站節點、國鐵站節點、路線邊（METRO_LINK / RAIL_LINK / INTERCHANGE_TO） |

---

### 系統運作流程（Pipeline）

```
使用者輸入問題
      │
      ▼
skeleton/ui.py  (Gradio 網頁介面，處理登入狀態)
      │
      ▼
skeleton/agent.py  ◄──── LLM（Gemini 或 Ollama）
      │   [1] LLM 讀問題，決定呼叫哪些工具
      │   [2] Agent 執行工具，查詢真實資料庫
      │   [3] Python flattener 將 JSON 轉成可讀文字
      │   [4] LLM 根據資料寫最終回答
      │
      ├── databases/relational/queries.py ──► PostgreSQL (port 5433)
      │                                          ├── 關聯式資料表
      │                                          └── policy_documents（向量搜尋）
      │
      └── databases/graph/queries.py ──────► Neo4j (port 7688)
                                                 └── 地鐵 + 國鐵網絡圖
```

---

## 二、專案架構

```
IM2002-DBMGT-Train-final-main/
│
├── .env.example               # 環境變數範本（複製為 .env 後填入 API key）
├── .gitignore
├── docker-compose.yml         # 啟動 PostgreSQL + Neo4j + pgAdmin
├── requirements.txt           # Python 套件清單
├── check_model.py             # 確認 LLM 連線的小工具
│
├── README.md                  # 完整的官方說明文件（英文）
├── SideNote1-RelationalDBPractices.md  # PostgreSQL 生產環境補充說明
├── SideNote2-VectorDBPractices.md      # pgvector 生產環境補充說明
├── SideNote3-GraphDBPractices.md       # Neo4j 生產環境補充說明
│
├── train-mock-data/           # 所有原始 JSON 資料（作業起點）
│   ├── metro_stations.json              # 20 個地鐵站（MS01–MS20）
│   ├── national_rail_stations.json      # 10 個國鐵站（NR01–NR10）
│   ├── metro_schedules.json             # 地鐵班表（M1–M4 線）
│   ├── national_rail_schedules.json     # 國鐵班表（NR1–NR2 線）
│   ├── national_rail_seat_layouts.json  # 國鐵座位配置
│   ├── registered_users.json            # 20 名虛構使用者
│   ├── bookings.json                    # 20 筆國鐵訂票記錄
│   ├── metro_travel_history.json        # 地鐵乘車歷史
│   ├── payments.json                    # 付款記錄
│   ├── feedback.json                    # 乘客評價
│   ├── refund_policy.json               # 退款政策文件（RAG 用）
│   ├── ticket_types.json                # 票種說明文件（RAG 用）
│   ├── booking_rules.json               # 訂票規則文件（RAG 用）
│   ├── travel_policies.json             # 旅行政策文件（RAG 用）
│   └── network_map.html                 # 路線圖視覺化
│
├── databases/                 # ← 學生的主要工作區
│   ├── __init__.py
│   ├── relational/
│   │   ├── __init__.py
│   │   ├── schema.sql         # ← 需要實作：設計並建立所有關聯式資料表
│   │   └── queries.py         # ← 需要實作：所有 PostgreSQL 查詢函式
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── seed.cypher        # ← 可選：也可在 seed_neo4j.py 中建圖
│   │   └── queries.py         # ← 需要實作：所有 Neo4j Cypher 查詢函式
│   └── vector/
│       └── __init__.py        # （vector 層已整合至 relational/queries.py）
│
└── skeleton/                  # ← 不需要修改的預建框架
    ├── __init__.py
    ├── agent.py               # LLM 工具路由與 Agent 主邏輯（768 行）
    ├── ui.py                  # Gradio 網頁介面（登入/註冊/聊天）
    ├── llm_provider.py        # LLM 抽象層（Gemini / Ollama 二選一）
    ├── config.py              # 讀取 .env 設定
    ├── seed_postgres.py       # ← 需要實作：讀 JSON 並 INSERT 進 PostgreSQL
    ├── seed_neo4j.py          # ← 需要實作：讀 JSON 並建立 Neo4j 節點與關係
    └── seed_vectors.py        # 已完成：把政策 JSON 轉成向量並存入 pgvector
```

---

### 目前完成度（開箱狀態）

| 檔案 | 狀態 | 說明 |
|---|---|---|
| `skeleton/agent.py` | ✅ 已完成 | 完整的 LLM 工具路由邏輯 |
| `skeleton/ui.py` | ✅ 已完成 | Gradio 聊天介面（含登入/註冊） |
| `skeleton/llm_provider.py` | ✅ 已完成 | Gemini + Ollama 雙模式 |
| `skeleton/config.py` | ✅ 已完成 | 環境變數讀取 |
| `skeleton/seed_vectors.py` | ✅ 已完成 | 政策文件向量化 |
| `databases/relational/queries.py` | ⚠️ 骨架 | 所有函式都是 `raise NotImplementedError` |
| `databases/relational/schema.sql` | ⚠️ 空白 | 只有向量表定義，關聯式表格全部待設計 |
| `databases/graph/queries.py` | ⚠️ 骨架 | 所有函式都是 `raise NotImplementedError` |
| `databases/graph/seed.cypher` | ⚠️ 空白 | 只有一行說明注解 |
| `skeleton/seed_postgres.py` | ⚠️ 骨架 | 所有 `seed_*` 函式都是 `pass` |
| `skeleton/seed_neo4j.py` | ⚠️ 骨架 | `seed()` 函式是空的 TODO |

---

### Agent 已定義的工具（Tools）

這些是 LLM 可以呼叫的函式，全部對應到 `databases/` 下的 query functions：

| 工具名稱 | 對應函式 | 資料庫 |
|---|---|---|
| `check_national_rail_availability` | `query_national_rail_availability` | PostgreSQL |
| `get_national_rail_fare` | `query_national_rail_fare` | PostgreSQL |
| `check_metro_availability` | `query_metro_schedules` | PostgreSQL |
| `calculate_metro_fare` | `query_metro_fare` | PostgreSQL |
| `get_metro_fare` | `query_metro_schedules` + `query_metro_fare` | PostgreSQL |
| `get_available_seats` | `query_available_seats` | PostgreSQL |
| `make_booking` | `execute_booking` | PostgreSQL |
| `cancel_booking` | `execute_cancellation` | PostgreSQL |
| `get_user_bookings` | `query_user_bookings` | PostgreSQL |
| `search_policy` | `query_policy_vector_search` | pgvector |
| `find_route` | `query_shortest_route` / `query_cheapest_route` / `query_interchange_path` | Neo4j |
| `find_alternative_routes` | `query_alternative_routes` | Neo4j |
| `get_delay_ripple` | `query_delay_ripple` | Neo4j |

---

## 三、若要讓 AI 直接幫你完成此 Project，需要提供的資訊

> **注意：** 以下各項越詳細、越完整，AI 能做的就越多且越準確。

---

### 3.1 環境與設定（必要）

#### 你選擇的 LLM Provider
- **你打算用 Ollama 還是 Gemini？**
  - Ollama：本機運行，免費，需要 ~1.6 GB 硬碟空間，速度慢
  - Gemini：需要 Google AI Studio 的免費 API key
- 如果用 Gemini，請提供 `GEMINI_API_KEY`
- **注意**：如果用 Gemini，`schema.sql` 裡的 `vector(768)` 需要改成 `vector(3072)`

#### Docker 環境確認
- 你的電腦是否已安裝且能執行 `docker compose up -d`？
- 執行後三個容器（postgres、neo4j、pgadmin）是否都顯示 `healthy`？

---

### 3.2 資料庫 Schema 設計決策（最關鍵）

AI 需要知道你打算如何設計資料表，或者你可以讓 AI 直接根據 JSON 資料設計。

**請告訴 AI 以下問題的答案（或讓 AI 自行決定）：**

#### 關聯式 Schema（`schema.sql`）需要的資料表清單：

每個 JSON 資料檔需要你決定如何對應到資料表：

| JSON 檔案 | 需決定的設計問題 |
|---|---|
| `metro_stations.json` | `lines` 是陣列（用 TEXT ARRAY、或正規化成獨立的 `station_lines` 表？） |
| `metro_schedules.json` | 班表的 `stops` 是陣列，要不要正規化成 `metro_schedule_stops` 表？ |
| `national_rail_schedules.json` | `stops`、`fares` 是巢狀結構，怎麼展開？ |
| `national_rail_seat_layouts.json` | `seats` 是陣列，每個座位一筆資料，還是用 JSON 欄位存？ |
| `registered_users.json` | `password`（明文）、`secret_question/answer`、`railcard_type` 要不要都存？ |
| `bookings.json` | `status` 欄位要用 ENUM 還是 VARCHAR？ |
| `metro_travel_history.json` | `trip_type`（single_ticket / day_pass）怎麼處理？ |
| `payments.json` | 付款與訂票是 1:1 還是 1:N？ |
| `feedback.json` | 需要 `feedback_type` 欄位（metro / national_rail）區分嗎？ |

**如果你想讓 AI 自動設計，請說：「請根據 JSON 自動設計所有資料表，盡量正規化。」**

---

### 3.3 Graph Schema 設計決策（Neo4j）

#### 節點標籤與屬性
- 地鐵站用 `:MetroStation`，國鐵站用 `:NationalRailStation`（或合併成 `:Station`？）
- 節點上要存哪些屬性？（`station_id`、`name`、`lines`、`zone` 等）

#### 關係類型與屬性
- 地鐵連線：`:METRO_LINK`，邊上存 `line`（e.g. "M1"）和 `travel_time_min`
- 國鐵連線：`:RAIL_LINK`，邊上存 `line`（e.g. "NR1"）和 `travel_time_min`
- 換乘連線：`:INTERCHANGE_TO`，連接 MS 站與 NR 站
- 需不需要存 `fare_per_stop` 在邊上（用於最便宜路線的 Dijkstra）？

**Neo4j 的 Dijkstra 最短路徑需要 APOC 套件（已在 docker-compose.yml 中啟用）。**

---

### 3.4 Query Functions 的預期回傳格式（重要）

AI 需要知道 `agent.py` 預期每個函式回傳什麼格式，才能正確實作。以下是根據 `agent.py` 推導出的規格：

#### PostgreSQL 函式（`databases/relational/queries.py`）

```python
# query_national_rail_availability
# 回傳: list[dict]，每筆包含:
#   schedule_id, service_type, departure_time, origin_name, destination_name,
#   stops_in_order (list), stops_between (int),
#   total_seats, booked_seats, available_seats

# query_national_rail_fare
# 回傳: dict，包含:
#   fare_class, base_fare_usd, per_stop_rate_usd, total_fare_usd

# query_metro_schedules
# 回傳: list[dict]，每筆包含:
#   schedule_id, line, origin_name, destination_name,
#   stops_in_order (list of station_ids), frequency_min

# query_metro_fare
# 回傳: dict，包含:
#   base_fare_usd, per_stop_rate_usd, total_fare_usd

# query_available_seats
# 回傳: list[dict]，每筆包含:
#   seat_id, coach, row (int), column (str), fare_class

# query_user_profile
# 回傳: dict，包含:
#   user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active

# query_user_bookings
# 回傳: dict，包含:
#   national_rail: list[dict] (booking records)
#   metro: list[dict] (metro trip records)

# execute_booking
# 回傳: tuple[bool, dict | str]
#   成功: (True, {booking_id, schedule_id, travel_date, ...})
#   失敗: (False, "error message")

# execute_cancellation
# 回傳: tuple[bool, dict | str]
#   成功: (True, {booking_id, refund_amount_usd, policy_note})
#   失敗: (False, "error message")

# register_user
# 回傳: tuple[bool, str]  → (True, user_id) 或 (False, error_msg)

# login_user
# 回傳: Optional[dict]，包含:
#   user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active
```

#### Neo4j 函式（`databases/graph/queries.py`）

```python
# query_shortest_route
# 回傳: dict，包含:
#   found (bool), origin_id, destination_id,
#   total_time_min (float), path (list of station dicts), legs (list)

# query_cheapest_route
# 回傳: dict，包含:
#   found (bool), total_fare_usd (float), stations (list), legs (list)

# query_alternative_routes
# 回傳: list[list[dict]]（每個元素是一條路線，由 leg dicts 組成）
# agent.py 包裝成: [{"route_number": 1, "legs": [...]}, ...]

# query_interchange_path
# 回傳: dict，包含:
#   found (bool), stations (list), interchange_points (list), total_time_min

# query_delay_ripple
# 回傳: list[dict]，每筆包含:
#   station_id, name, hops_away (int), lines_affected (list)
```

---

### 3.5 退款計算邏輯（`execute_cancellation` 用）

根據 README，退款計算有兩套規則：
- **一般班次（RF001）**：100%（很早）/ 75% / 50% / 0%（太晚）
- **特快班次（RF002）**：100% / 50% / 0%

請提供 `refund_policy.json` 的具體時間窗口定義，或讓 AI 直接讀取該 JSON 來實作。

---

### 3.6 Docker + 套件環境確認

請確認以下工具已安裝，或讓 AI 提供安裝指令：

```
✅ Docker Desktop（含 WSL2，Windows 必要）
✅ Python 3.10+
✅ pip install -r requirements.txt 已執行
✅ .env 檔案已複製並填妥
✅ docker compose up -d 已執行，容器顯示 healthy
```

如果用 Ollama：
```
✅ ollama pull llama3.2:1b
✅ ollama pull nomic-embed-text
```

---

### 3.7 作業繳交的完整需求（你需要確認的）

請確認以下問題的答案，AI 才能以正確方向幫你完成：

1. **作業要求的任務是哪幾個？** 根據 README 的 `Your Tasks` 章節，必做的是：
   - `schema.sql` — 設計所有資料表
   - `seed_postgres.py` — 實作所有 seed 函式
   - `seed_neo4j.py` — 實作建圖邏輯
   - `databases/relational/queries.py` — 實作所有 query 函式
   - `databases/graph/queries.py` — 實作所有 Cypher 查詢函式
   - 政策 JSON 擴充（可選）

2. **是否有額外的作業規定、報告格式、或評分標準？** 請提供作業說明書（PDF 或截圖）

3. **有沒有不能使用的外部套件？** 目前的 `requirements.txt` 只用了 `psycopg2-binary`、`neo4j`、`google-genai`、`requests`、`gradio`、`python-dotenv`

4. **是否要加選做功能？** 例如：
   - 新增 `delay_records` 資料表
   - 新增更多政策文件
   - 修改 `agent.py` 加入新工具

---

### 3.8 給 AI 的一句話指令範例

如果你想讓 AI 直接開始，可以這樣說：

> 「請幫我完成這個 TransitFlow 資料庫 project。  
> LLM 我選 Ollama。  
> 請自動根據 JSON 資料設計 PostgreSQL schema，盡量正規化。  
> 地鐵站和國鐵站在 Neo4j 用不同的 label（:MetroStation 和 :NationalRailStation）。  
> 請依序完成：schema.sql → seed_postgres.py → seed_neo4j.py → relational/queries.py → graph/queries.py。  
> 完成後告訴我怎麼驗證一切正常運作。」

---

## 四、快速參考

### 本機服務 URL（Docker 啟動後）

| 服務 | URL |
|---|---|
| TransitFlow 聊天介面 | http://localhost:7860 |
| pgAdmin（PostgreSQL GUI） | http://localhost:5051 |
| Neo4j Browser | http://localhost:7475 |

### pgAdmin 連線設定

| 欄位 | 值 |
|---|---|
| Host | `postgres` |
| Port | `5432` |
| Database | `transitflow` |
| Username | `transitflow` |
| Password | `transitflow` |

### Neo4j 連線設定

| 欄位 | 值 |
|---|---|
| Connect URL | `bolt://localhost:7688` |
| Username | `neo4j` |
| Password | `transitflow` |

### 常用指令

```powershell
# 啟動資料庫容器
docker compose up -d

# 重置資料庫（schema 有改動時必做）
docker compose down -v && docker compose up -d

# 填入 PostgreSQL 資料
python skeleton/seed_postgres.py

# 建立 Neo4j 圖形
python skeleton/seed_neo4j.py

# 填入向量資料（政策文件）
python skeleton/seed_vectors.py

# 啟動聊天介面
python skeleton/ui.py
```
