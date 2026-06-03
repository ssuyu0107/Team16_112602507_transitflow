# TransitFlow 專案團隊分工與進度表

## 👥 隊員職責分配 (Team Assignments)

| 姓名 / 負責人 | 核心實作範疇 (Primary Responsibility) | 涉及文件與工作內容 |
| :--- | :--- | :--- |
| **組員 a** | **後端資料庫進階查詢函數實作** | 負責 `databases/relational/queries.py` `databases/graph/queries.py`  |
| **組員 b** | **資料庫 Schema 設計與環境架設** | 負責 `databases/relational/schema.sql` |
| **組員 c** | **初始資料灌錄與知識庫向量建置** | 負責 `skeleton/seed_postgres.py`  `skeleton/seed_neo4j.py`  |

## 🏁 核心 Stub 函數功能驗收狀態
- [x] 資料庫 Docker 容器開機與埠口配置 (Port 7475/7688 修正)
- [x] 關係型資料表建置與基礎車次資料灌錄
- [x] Neo4j 車站拓樸網絡節點與關係灌錄 (地圖已可視化)
- [x] `queries.py` 內 PostgreSQL 進階 SQL 函數實作
- [x] `queries.py` 內 Neo4j 圖形最短路徑 Cypher 函數實作