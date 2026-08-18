# Graph Report - .  (2026-08-13)

## Corpus Check
- 28 files · ~446,165 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 182 nodes · 374 edges · 13 communities
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 22 edges (avg confidence: 0.86)
- Token cost: 75,091 input · 0 output

## Community Hubs (Navigation)
- Basketball Reference Parser
- Backend Dependencies & Goldstandard
- FastAPI Server Endpoints
- HTML Parsing Utilities & Registry
- Gold Standard HTML Refresh Tool
- API Request/Response Schemas
- Web Parser REST API
- Frontend UI Routes

## God Nodes (most connected - your core abstractions)
1. `parse_basketball_reference()` - 15 edges
2. `_collect()` - 11 edges
3. `get_parser()` - 10 edges
4. `backend/ module` - 10 edges
5. `server.py (FastAPI server)` - 10 edges
6. `_render_wrapper()` - 9 edges
7. `parse_section_children()` - 9 edges
8. `load_gold_standard_for_domain()` - 9 edges
9. `_fallback_lines()` - 8 edges
10. `parse_wikipedia()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `domains.json (elenco domini supportati)` --conceptually_related_to--> `backend/ module`  [INFERRED]
  README.md → report.pdf
- `FastAPI` --shares_data_with--> `server.py (FastAPI server)`  [INFERRED]
  backend/requirements.txt → report.pdf
- `Web Parser UI Page (index.html)` --conceptually_related_to--> `frontend templates/ (pagine HTML Jinja2)`  [INFERRED]
  frontend/src/templates/index.html → report.pdf
- `Backend (FastAPI + Crawl4AI)` --conceptually_related_to--> `backend/ module`  [INFERRED]
  README.md → report.pdf
- `Frontend (Jinja2 Web UI)` --conceptually_related_to--> `frontend/ module`  [INFERRED]
  README.md → report.pdf

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Backend REST API Endpoints** — backend_src_server_py, report_get_parse, report_post_parse, report_get_domains, report_get_gold_standard, report_get_full_gold_standard, report_post_evaluate, report_get_full_gs_eval [EXTRACTED 1.00]
- **Backend Auxiliary Services (backend/src/services/)** — backend_src_services_evaluator, backend_src_services_markdown_utils, backend_src_services_goldstandard_service [EXTRACTED 0.95]
- **Docker Multi-Container Deployment** — docker_compose_backend_service, docker_compose_frontend_service, report_backend_module, report_frontend_module [EXTRACTED 0.90]

## Communities (13 total, 0 thin omitted)

### Community 0 - "Basketball Reference Parser"
Cohesion: 0.11
Nodes (42): _allowed_tables(), _branch(), _cell_text(), _clean_line(), _collect(), _extract_domain(), _extract_title(), _fallback_blocks() (+34 more)

### Community 1 - "Backend Dependencies & Goldstandard"
Cohesion: 0.09
Nodes (31): Crawl4AI (dependency), Backend Python Dependencies, FastAPI, Playwright, get_goldstandard_entry_by_url(), get_gs_file_path(), load_goldstandard_by_domain(), remove_markdown() (+23 more)

### Community 2 - "FastAPI Server Endpoints"
Cohesion: 0.17
Nodes (26): get_parser(), debug_eval(), debug_gs_health(), domain_to_gs_filename(), evaluate(), full_gs_eval(), get_domains(), get_full_gold_standard() (+18 more)

### Community 3 - "HTML Parsing Utilities & Registry"
Cohesion: 0.17
Nodes (22): build_result(), _build_run_config(), _crawl4ai_fetch(), _crawl4ai_parse_raw_html(), extract_page_title(), make_soup(), parse_raw_html_with_crawl4ai(), BeautifulSoup (+14 more)

### Community 4 - "Gold Standard HTML Refresh Tool"
Cohesion: 0.25
Nodes (15): fetch_html(), fetch_html_crawl4ai(), Fallback HTTP semplice (nessun JS)., html_title(), load(), looks_broken(), main(), Path (+7 more)

### Community 5 - "API Request/Response Schemas"
Cohesion: 0.33
Nodes (10): DomainsResponse, EvaluateRequest, EvaluateResponse, FullGoldStandardResponse, FullGSEvalResponse, GoldStandardEntry, ParsePostRequest, ParseResponse (+2 more)

### Community 6 - "Web Parser REST API"
Cohesion: 0.22
Nodes (11): server.py (FastAPI server), Evaluate GS URL Form (POST /evaluate-ui), Web Parser UI Page (index.html), Parse URL Form (POST /parse-ui), GET /domains, GET /full_gold_standard, GET /full_gs_eval, GET /gold_standard (+3 more)

### Community 7 - "Frontend UI Routes"
Cohesion: 0.42
Nodes (9): evaluate_ui(), home(), load_domains_and_gs_urls(), parse_ui(), get, post, safe_get(), safe_post() (+1 more)

## Ambiguous Edges - Review These
- `registry.py` → `Strategia dei parser specifici per dominio`  [AMBIGUOUS]
  report.pdf · relation: references

## Knowledge Gaps
- **5 isolated node(s):** `Precision, Recall, F1-score`, `GET /parse`, `GET /domains`, `GET /full_gold_standard`, `GET /full_gs_eval`
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `registry.py` and `Strategia dei parser specifici per dominio`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `backend/ module` connect `Backend Dependencies & Goldstandard` to `HTML Parsing Utilities & Registry`, `API Request/Response Schemas`, `Web Parser REST API`?**
  _High betweenness centrality (0.313) - this node is a cross-community bridge._
- **Why does `server.py (FastAPI server)` connect `Web Parser REST API` to `Backend Dependencies & Goldstandard`, `API Request/Response Schemas`?**
  _High betweenness centrality (0.124) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `backend/ module` (e.g. with `domains.json (elenco domini supportati)` and `Backend (FastAPI + Crawl4AI)`) actually correct?**
  _`backend/ module` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Precision, Recall, F1-score`, `GET /parse`, `GET /domains` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Basketball Reference Parser` be split into smaller, more focused modules?**
  _Cohesion score 0.10520487264673312 - nodes in this community are weakly interconnected._
- **Should `Backend Dependencies & Goldstandard` be split into smaller, more focused modules?**
  _Cohesion score 0.08912655971479501 - nodes in this community are weakly interconnected._