# TransitFlow 專案團隊分工與進度表

## 👥 隊員職責分配 (Team Assignments)

| 姓名 / 負責人 | 核心實作範疇 (Primary Responsibility) | 涉及文件與工作內容 |
| :--- | :--- | :--- |
| **組員 a** | **後端資料庫進階查詢函數實作** | 負責 `databases/relational/queries.py` (SQL 條件查詢) 與 `databases/graph/queries.py` (Cypher 最短路徑演算法) 的功能填補與本機端整合測試。 |
| **組員 b** | **資料庫 Schema 設計與環境架設** | 負責 `databases/relational/schema.sql` 的資料表設計，以及 Docker Compose（PostgreSQL、Neo4j）環境部署與網路對應。 |
| **組員 c** | **初始資料灌錄與知識庫向量建置** | 負責 `skeleton/seed_postgres.py` 與 `skeleton/seed_neo4j.py` 腳本撰寫，將原始 JSON 鐵路數據匯入資料庫，並維護 AI 政策知識庫（JSON 擴充）。 |

## 🏁 核心 Stub 函數功能驗收狀態
- [x] 資料庫 Docker 容器開機與埠口配置 (Port 7475/7688 修正)
- [x] 關係型資料表建置與基礎車次資料灌錄
- [x] Neo4j 車站拓樸網絡節點與關係灌錄 (地圖已可視化)
- [ ] `queries.py` 內 PostgreSQL 進階 SQL 函數實作
- [ ] `queries.py` 內 Neo4j 圖形最短路徑 Cypher 函數實作