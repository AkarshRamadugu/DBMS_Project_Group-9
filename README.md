# CS F212 Database Systems — Project Mid-Semester Submission
## Group 9: Paper-Trading Exchange
**Institution:** BITS Pilani, Hyderabad Campus  
**Course:** CS F212 Database Systems  

---

## 1. Project Description
This repository contains the database design and application architecture for a simulated paper-trading exchange supporting multiple financial instruments (stocks, bonds, and options), limit-order matching, settlement, and portfolio tracking. The primary focus of this submission is on formal database modeling, schema normalization, integrity constraints, and application architecture.

---

## 2. Team Members & Task Distribution

| Name | Student ID | Mid-Semester Responsibilities |
|---|---|---|
| **Devansh Rupesh Anadkat** | 2024ADPS0198H | Conceptual ER/EER modeling (Chen notation), EER disjoint specialization (`BOND`/`OPTION`), 9-step relational schema mapping, and stored procedure matching engine design (`match_and_settle`). |
| **Akarsh Ramadugu** | 2024ADPS0196H | BCNF normalization verification, performance denormalization trade-offs, non-trivial analytical SQL queries, partial indexing strategy, and database views. |
| **Shashank Bodala** | 2024ADPS0186H | Domain integrity constraints (`CHECK`, `UNIQUE`, `NOT NULL`) and trigger specifications (audit log, subtype disjointness, fill quantity synchronization). |
| **Druhin Sourya Datta Bommisetti** | 2024ADPS0182H | Application architecture, core workflow definitions, and FastAPI/psycopg3 interface specification. |
| **Hakimkari Sathvika** | 2024ADPS0192H | Data population pipeline planning (PostgreSQL `COPY`), market data seeding logic, and repository organization. |

---

## 3. Mid-Semester Deliverables

* **[Midsem_Submission.pdf](Midsem_Submission.pdf)**: Complete 5-page mid-semester submission report.
* **[Midsem_Submission.md](Midsem_Submission.md)**: Markdown source for the submission report.
* **[er_diagram.png](er_diagram.png)** / **[er_diagram.gv](er_diagram.gv)**: Chen-notation ER/EER diagram (Elmasri & Navathe 7th ed.) including entity types, relationships, weak entities, and specialization hierarchy.
* **[schema_diagram.png](schema_diagram.png)** / **[schema_diagram.gv](schema_diagram.gv)**: Relational schema diagram illustrating table structures, primary keys, foreign keys, and referential constraints.

---

## 4. Current Implementation Status
* **Relational Schema:** 12 normalized relations in BCNF.
* **Foreign Keys:** 14 explicit referential integrity links across tables.
* **Specialization Hierarchy:** Attribute-defined, disjoint, partial specialization mapping `INSTRUMENT` into `BOND` and `OPTION` subclasses.
* **Weak Entities:** `PRICE_BAR` (owner `INSTRUMENT`) and `ORDER_FILL` (owner `ORDER`).
* **Planned Features:** Stored procedures for order matching, triggers for audit logging and domain constraints, and partial indexes for open limit orders.