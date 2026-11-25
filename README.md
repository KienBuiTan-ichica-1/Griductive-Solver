# Griductive Solver (CSC14003 - Project 2)

Game Griductive dạng web (React + TypeScript) với bộ giải Python gồm: encoder CNF tự động,
bộ giải DPLL viết tay, và Logic Agent chỉ suy luận từ tri thức công khai (không đọc đáp án ẩn).
GUI dùng chung phong cách dark/neon với Project 1 (HUD ở trên, bảng điều khiển hai bên, tab kết quả).

## Cách chạy

### Trước khi chạy.

- Tạo và kích hoạt môi trường ảo.

Linux/MacOS
```bash
python -m venv venv
source venv/bin/activate 
```

Window
```bash
python -m venv venv
venv\Scripts\activate.bat     --hoặc Activate.ps1 --
```
Sau khi kích hoạt thì phải có "(venv)" xuất hiện.

- Tải depedency.

```bash
pip install -r requirements.txt
```

### Chạy 

**Cách 1: Trực tiếp Python sử dụng** (frontend đã build sẵn trong `frontend/dist`)

```bash
python main.py <port>            # mở http://127.0.0.1:<port>
```

**Cách 2: chế độ phát triển** (cần Node 18+)

```bash
# terminal 1
uvicorn main:app --port 8000
# terminal 2
cd frontend
npm install
npm run dev               # mở http://localhost:5173 (proxy /api -> :8000)
```

Build lại frontend: `cd frontend && npm run build`.

**Cách 3: Chạy trên front-end prototype, không cần React** 

```bash
# terminal 1
uvicorn main:app --port 8000
# terminal
python prototype/server.py 8001 --api 8000.   # mở http://localhost:8001 từ api port 8000.
```

## Giao diện

- Bàn cờ N×N: cột A… theo chiều ngang, hàng 1… theo chiều dọc. Mỗi ô là một thẻ có tên, nghề nghiệp,
  trạng thái (`CRIMINAL` / `INNOCENT` / `UNKNOWN`) và clue (clue của thẻ úp bị che).
- Chọn thẻ rồi bấm **CRIMINAL** hoặc **INNOCENT**. Verdict chỉ được chấp nhận khi nó bị KB hiện tại
  bắt buộc; nếu không bấm sẽ báo `NOT_PROVABLE`, nếu verdict ngược lại bị bắt buộc thì báo `CONTRADICTED`.
- Bấm một clue đã lật để highlight các ô mà clue đó đề cập/đếm.
- **Hint**: chỉ ra một người tiếp theo bị bắt buộc và clue liên quan (thử leave-one-out).
  **Auto Step** thực hiện một bước; **Auto Solve** lặp cho đến khi solved hoặc STUCK.
- **Restart**, **Puzzle khác**, **Load file JSON**, và tab **Thực nghiệm** (4 biểu đồ + xuất CSV).
- Hiện thống kê KB_t: biến chính, biến phụ, clause, SAT calls, decisions, propagations, backtracks, runtime.

## Cấu trúc

```
Source/
  main.py                  API FastAPI (+ phục vụ frontend/dist)
  griductive/
    model.py               puzzle, vùng (region), 8 template clue, evaluator ngữ nghĩa
    cnf.py                 encoder CNF (mọi clue + unit verdict), thống kê biến/clause
    dpll.py                DPLL: unit propagation, conflict, branching, backtracking, stats
    engine.py              GameEngine: chủ sở hữu đáp án ẩn và clue chưa lật
    agent.py               LogicAgent: entailment, hint, kiểm tra unique
    session.py             giao thức no-guess giữa engine và agent
  levels/*.json            Các level sẵn.
  benchmark.py             Chạy benchmark
  tests/                   Chạy các test
  tools/generate_puzzles.py  --depreciated-- sinh puzzle có chuỗi suy luận chứng minh được
  random_levels/           Tạo ra puzzle có thể điều chỉnh được. (Đọc **README**)
  frontend/                React + TypeScript (src/App.tsx, src/styles.css)
  results/                 benchmark.csv, benchmark.json
```

## Mô hình bài toán

- Biến chính `C_i = True` nếu nhân vật `i` là Criminal, `False` nếu Innocent.
  Ánh xạ tên → biến theo thứ tự alphabet (xem `CNFEncoder.name_to_var`), chạy cùng một thứ tự ở mọi bước.
- Vùng được hỗ trợ: `row`, `col`, `neighbors` (8 hướng, có chéo), `cells`, `intersection`,
  `common_neighbors`, `boundary`, `corners`, `between`.
- 6 template bắt buộc: `FACT`, `SAME`, `DIFFERENT`, `EXACTLY`, `AT_LEAST`, `AT_MOST`.
  2 mở rộng: `PARITY` (chẵn/lẻ số criminal) và `COMPARE` (so sánh số criminal của hai vùng).
- Ở bước t: `KB_t = CNF(clue đã lật) ∧ unit clause(verdict đã chứng minh)`.
  Clue chưa lật và đáp án ẩn **không bao giờ** nằm trong `KB_t`.
- Phán quyết: `KB ⊨ C_i` iff `KB ∧ ¬C_i` UNSAT; `KB ⊨ ¬C_i` iff `KB ∧ C_i` UNSAT;
  nếu cả hai SAT thì `UNKNOWN`; nếu `KB` UNSAT thì `INCONSISTENT`.

## Ví dụ suy luận CNF (dùng cho báo cáo)

**Binary clue** `DIFFERENT(A, B)`: `A ⊕ B` tương đương

```
(C_A ∨ C_B) ∧ (¬C_A ∨ ¬C_B)
```

Hai clause này loại bỏ đúng hai trường hợp `A = B`; các trường hợp `(T,F)` và `(F,T)` đều thỏa.

**Counting clue** `EXACTLY(2, {A, B, C})` dùng combinatorial encoding. Viết `S = A+B+C`:

- `S ≤ 2`: với mọi tập con 3 phần tử (duy nhất `{A,B,C}`) thêm `(¬A ∨ ¬B ∨ ¬C)`.
- `S ≥ 2`: với mọi tập con `3-2+1 = 2` phần tử thêm
  `(A ∨ B) ∧ (A ∨ C) ∧ (B ∨ C)`.

Nói chung `at_most(k)`: mọi tập `k+1` biến cho một clause các literal phủ định;
`at_least(k)`: mọi tập `|R|-k+1` biến cho một clause các literal dương.
`PARITY` dùng xâu XOR với biến phụ: `z = x ⊕ y` được mã bằng 4 clause
`(¬x∨¬y∨¬z), (x∨y∨¬z), (x∨¬y∨z), (¬x∨y∨z)`.
`COMPARE` tạo biến chỉ số `e_j` ("vùng có đúng j criminal") rồi chặn các cặp `(i,j)` vi phạm
bằng clause `(¬e_i ∨ ¬e_j)`.

Mỗi lần xây KB đều đếm số biến chính, biến phụ và clause; API trả các con số đó trong `analysis.kb`.

## Thuật toán

- **DPLL**: unit propagation đến cố định điểm, phát hiện conflict, chọn biến nhỏ nhất còn chưa gán
  (deterministic), nhánh True trước, backtracking khi nhánh thất bại. Có thể bật pure-literal elimination.
  Mỗi lần solve ghi decisions, propagations, backtracks, conflicts và thời gian.
- **Logic Agent**: với mỗi người chưa solved gọi DPLL hai lần (giả sử Criminal / Innocent) để phân loại;
  chỉ chọn verdict bị bắt buộc theo thứ tự row-major. Hint dùng phép thử bỏ từng clue để tìm clue cần thiết.
- **Unique check**: xây KB từ toàn bộ clue + trạng thái lật ban đầu, sau đó kiểm tra từng biến có bị bắt buộc hay không.
- **GameEngine** là nơi duy nhất giữ solution ẩn và clue chưa lật; `public_state()` không trả hai dữ liệu đó.

## Kiểm tra

### Kiểm tra logic 

Cần cài thêm dependency cho test (file `requirements-dev.txt`):

```bash
pip install -r requirements-dev.txt
```

Chạy các test qua : 

```bash
pytest tests/*
```

### Benchmark

Chạy benchmark qua tất cả các level trong thư mục `levels`.

```bash
python benchmark.py
```

Tạo `benchmark.csv` và `benchmark.json` file trên `results/`

Benchmark mẫu (máy phát triển, sau khi tách thống kê): 3×3 ~0.25–0.35 ms,
4×4 ~0.9–1.4 ms (level GEN-hard ~8–17 ms), 5×5 ~4 ms cho toàn bộ chuỗi suy luận;
mọi puzzle đều solved, unique, và hidden solution thỏa mãn
mọi clue. Mỗi bản ghi trace gồm số bước, clue đang active, SAT query và clue vừa lật. Mỗi bản ghi
benchmark/CSV có `sat_calls` (chỉ entailment), `hint_sat_calls` (giải thích hint), `total_sat_calls`,
`timeout_ms`, `timed_out` và `failure`; giới hạn mặc định là 5000 ms cho mỗi puzzle (`UNKNOWN`,
`STUCK`, `INCONSISTENT` hoặc `TIMEOUT` được ghi rõ trong `failure`). `auto_step` không gọi
`relevant_clue`, nên Auto Solve chỉ tạo query entailment; các query chuẩn bị cho verdict đã được gộp
vào chính dòng trace của verdict đó thay vì nằm ở dòng hint riêng.

Puzzle có thể có thẻ không kèm clue: đây là điểm khác thiết kế so với đề ("mỗi ô có một clue có cấu
trúc"). Engine tạo clue `NO_CLUE` khi lật thẻ đó, clue này không thêm clause nào vào KB, không bao giờ
được chọn làm clue liên quan của hint, và có trong `/api/health`.

Bộ clue tự mâu thuẫn vẫn được nạp (HTTP 200) để demo trạng thái `INCONSISTENT`, dù điều này trái với
định nghĩa "puzzle hợp lệ có đúng một nghiệm". API chỉ từ chối khi các clue thỏa mãn được nhưng đáp án
ẩn lại vi phạm chúng. Trường hợp đó cũng được ghi `failure=INCONSISTENT` trong benchmark.

`COMPARE` dùng mã hóa chỉ số combinatorial, nên số clause tăng nhanh theo kích thước vùng
(khoảng 1.3×10^5 clause cho vùng 5×5, 2.1×10^6 cho 6×6). Với vùng lớn hơn, nên chia nhỏ vùng
hoặc chỉ dùng `EXACTLY`/`AT_MOST`; benchmark sẽ báo `failure=TIMEOUT` nếu vượt giới hạn.

## Định dạng puzzle (JSON)

```json
{
  "id": "G01", "name": "Puzzle G01", "group": "3x3", "size": 3,
  "characters": [{"cell": "A1", "name": "Abel", "job": "Baker"}, "..."],
  "clues": [
    {"id": "c1", "owner": "Abel", "type": "DIFFERENT", "a": "Abel", "b": "Bea"},
    {"id": "c2", "owner": "Bea", "type": "EXACTLY", "k": 1,
     "region": {"kind": "cells", "cells": ["C1", "A1"]}}
  ],
  "solution": {"Abel": "CRIMINAL", "Bea": "INNOCENT", "...": "..."},
  "initial_revealed": ["Abel", "Bea"]
}
```

`owner` là nhân vật sở hữu thẻ clue; `initial_revealed` là danh sách tên các thẻ lật sẵn (status + clue đều public).
Mọi tham số và vùng đều được validate trước khi encode; clue type hoặc cell không hợp lệ bị từ chối.

### random_levels.

[Đọc ở đây (Tiếng Anh)](./random_levels/README.md)