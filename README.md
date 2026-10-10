# Paper-Trading Exchange — DBMS Course Project (Group 9)
## CS F212 Database Systems, BITS Pilani Hyderabad

---

### 📌 Project Overview
A full-stack paper trading platform simulating a financial exchange with order matching, multi-instrument support (stocks, bonds, options), settlement, portfolio management, and an audit trail. Built on PostgreSQL with a focus on database design depth.

---

### 📂 Repository Structure & Mid-Sem Submission Deliverables

* 📄 **[Midsem_Submission.pdf](Midsem_Submission.pdf)** — Complete formatted Mid-Semester Submission Report.
* 📝 **[Midsem_Submission.md](Midsem_Submission.md)** — Source Markdown report detailing assumptions, 9-step relational schema mapping, tables/PK/FK lists, integrity constraints, BCNF normalization proofs, application workflows, tech stack, and DBMS features plan.
* 🖼️ **[er_diagram.png](er_diagram.png)** & **[er_diagram.gv](er_diagram.gv)** — Chen-style ER/EER Diagram (Elmasri & Navathe 7th ed.) with disjoint specialization hierarchy (`BOND`/`OPTION`), weak entities, and total/partial participation constraints.
* 📐 **[schema_diagram.png](schema_diagram.png)** & **[schema_diagram.gv](schema_diagram.gv)** — Visual Relational Schema Diagram showing all 12 database tables, PKs, FKs, and relationship connections.

---

### 👥 Team Members & Mid-Sem Contributions

| Name | Student ID | Mid-Sem Contributions |
|---|---|---|
| **Devansh Rupesh Anadkat** | `2024ADPS0198H` | Author of conceptual ER/EER model (Chen notation), EER disjoint specialization hierarchy (`BOND`/`OPTION`), 9-step relational schema mapping procedure, and transaction stored procedure matching engine (`match_and_settle`). |
| **Akarsh Ramadugu** | `2024ADPS0196H` | BCNF normalization proof, design performance trade-off justifications, formulation of non-trivial SQL analytics queries, partial index strategy, and database view specifications. |
| **Shashank Bodala** | `2024ADPS0186H` | Definition of database integrity constraints (`CHECK`, `UNIQUE`, `NOT NULL`) and trigger logic specifications (audit logging, subtype disjointness, fill sync). |
| **Druhin Sourya Datta Bommisetti** | `2024ADPS0182H` | Application design specifications, high-level architecture layout, and definition of the 3 core application workflows. |
| **Hakimkari Sathvika** | `2024ADPS0192H` | Data loading strategy planning (`COPY` ingestion), synthetic pricing formulas (Black-Scholes & yield curves), and GitHub repository structure. |

---

### 📊 Current Progress
* ✅ **ER/EER Model**: 11 entities, 13 relationships, 2 weak entities (`ORDER_FILL`, `PRICE_BAR`), and attribute-defined disjoint partial specialization (`INSTRUMENT` → `BOND` / `OPTION`).
* ✅ **Relational Mapping**: 9-step formal mapping resulting in 12 BCNF relations with 14 foreign key constraints.
* ✅ **Integrity Constraints**: Complete specification of `CHECK`, `UNIQUE`, `NOT NULL`, and 7 trigger-enforced rules.
* ✅ **DBMS Features & Query Plans**: 5 DBMS feature categories and 7 non-trivial SQL analytical queries planned.
* ✅ **Architecture**: High-level PostgreSQL 16 + FastAPI + raw `psycopg3` architecture designed.