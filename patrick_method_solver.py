# patrick_method_solver.py
# Patrick Method - Minimal SOP Solver (Single and Multiple Output)
# 完整 Flask 應用（含後端邏輯與前端 HTML 與檔案上傳）

from flask import Flask, render_template_string, request
from datetime import datetime
from itertools import combinations, product
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 頁面模板（直接內嵌 HTML）
HTML_PAGE = """
<!doctype html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Patrick Method Solver</title>
    <style>
        :root {
            --bg: #eef1f7;
            --card: #ffffff;
            --ink: #1f2437;
            --muted: #5b6478;
            --accent: #3f51b5;
            --accent-dark: #32408f;
            --accent-soft: #e8ebfa;
            --line: #d9dee9;
            --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 32px 16px;
            background: var(--bg);
            color: var(--ink);
            font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC",
                         "Noto Sans TC", "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
        }
        .wrap { max-width: 720px; margin: 0 auto; }
        header.hero { margin-bottom: 20px; }
        header.hero h1 {
            margin: 0 0 4px;
            font-size: 1.55rem;
            letter-spacing: .02em;
        }
        header.hero p { margin: 0; color: var(--muted); font-size: .95rem; }
        .card {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 24px;
            box-shadow: 0 2px 10px rgba(31, 36, 55, .06);
        }
        label { display: block; font-weight: 600; margin-bottom: 6px; }
        .hint { color: var(--muted); font-weight: 400; font-size: .85rem; }
        textarea {
            width: 100%;
            height: 88px;
            margin-bottom: 18px;
            padding: 10px 12px;
            border: 1px solid var(--line);
            border-radius: 10px;
            background: #fbfcfe;
            color: var(--ink);
            font-family: var(--mono);
            font-size: .95rem;
            resize: vertical;
        }
        textarea:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-soft);
        }
        .upload {
            border: 1px dashed var(--line);
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 20px;
            background: #fbfcfe;
        }
        .upload label { margin-bottom: 8px; }
        input[type=file] { font-size: .9rem; color: var(--muted); max-width: 100%; }
        input[type=file]::file-selector-button {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 6px 14px;
            margin-right: 10px;
            background: var(--accent-soft);
            color: var(--accent-dark);
            font-weight: 600;
            cursor: pointer;
            transition: background .15s ease;
        }
        input[type=file]::file-selector-button:hover { background: #d8ddf5; }
        .sep {
            display: inline-block;
            min-width: 1.3em;
            padding: 0 4px;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #f2f4fa;
            color: var(--accent-dark);
            font-family: var(--mono);
            font-size: .85em;
            text-align: center;
            line-height: 1.4;
        }
        input[type=submit] {
            display: block;
            width: 100%;
            padding: 12px 20px;
            border: none;
            border-radius: 10px;
            background: var(--accent);
            color: #fff;
            font-size: 1rem;
            font-weight: 600;
            letter-spacing: .05em;
            cursor: pointer;
            transition: background .15s ease;
        }
        input[type=submit]:hover { background: var(--accent-dark); }
        .result {
            margin-top: 20px;
            padding: 18px 20px;
            background: var(--accent-soft);
            border: 1px solid #c9d1f2;
            border-left: 5px solid var(--accent);
            border-radius: 10px;
        }
        .result strong { display: block; margin-bottom: 6px; }
        .result .sop {
            white-space: pre-line;
            font-family: var(--mono);
            font-size: .95rem;
        }
        footer {
            margin-top: 28px;
            text-align: center;
            color: var(--muted);
            font-size: .8rem;
        }
        @media (max-width: 480px) {
            body { padding: 16px 10px; }
            .card { padding: 16px; }
            header.hero h1 { font-size: 1.3rem; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <header class="hero">
            <h1>Patrick Method 最小 SOP 化簡工具</h1>
            <p>輸入 Prime Implicants 與 Minterms，求出涵蓋所有 minterm 的最小 SOP 組合</p>
        </header>
        <div class="card">
            <form method="post" enctype="multipart/form-data">
                <label>PI 輸入 <span class="hint">（多輸出以 <span class="sep">;</span> 分隔，同一輸出內以 <span class="sep">,</span> 分隔）</span></label>
                <textarea name="pi_input">A'B, AB; A'C</textarea>
                <label>Minterm 輸入 <span class="hint">（多輸出以 <span class="sep">;</span> 分隔）</span></label>
                <textarea name="minterms">1,3; 2,6</textarea>
                <div class="upload">
                    <label>或上傳文字檔 (.txt) <span class="hint">第 1 行 PI、第 2 行 Minterms，會覆蓋上方輸入</span></label>
                    <input type="file" name="input_file">
                </div>
                <input type="submit" value="計算最小 SOP">
            </form>
            {% if result %}
            <div class="result">
                <strong>計算結果：</strong>
                <div class="sop">{{ result }}</div>
            </div>
            {% endif %}
        </div>
        <footer>&copy; {{ year }} Patrick Solver</footer>
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    if request.method == "POST":
        pi_input = request.form.get("pi_input", "")
        minterms = request.form.get("minterms", "")
        file = request.files.get("input_file")

        if file and file.filename.endswith(".txt"):
            content = file.read().decode("utf-8")
            lines = content.strip().split('\n')
            if len(lines) >= 2:
                pi_input = lines[0]
                minterms = lines[1]

        result = run_patrick_method(pi_input, minterms)
    return render_template_string(HTML_PAGE, result=result, year=datetime.now().year)


def run_patrick_method(pi_input: str, minterms: str):
    pi_groups, mt_groups = parse_input(pi_input, minterms)
    all_results = []

    for index, (pi_list, mt_list) in enumerate(zip(pi_groups, mt_groups)):
        chart = build_prime_chart(pi_list, mt_list)
        min_sop = find_min_sop(chart, pi_list)
        all_results.append(f"F{index}(Minterms: {mt_list}) → 最小 SOP: {' + '.join(min_sop) if min_sop else '找不到涵蓋所有 minterm 的組合'}")

    return "\n".join(all_results)


def parse_input(pi_input: str, minterm_input: str):
    pi_groups = [x.strip() for x in pi_input.strip().split(';')]
    mt_groups = [x.strip() for x in minterm_input.strip().split(';')]
    pi_list_grouped = [[term.strip() for term in group.split(',')] for group in pi_groups]
    mt_list_grouped = [[int(m) for m in group.split(',') if m.strip().isdigit()] for group in mt_groups]
    return pi_list_grouped, mt_list_grouped


def build_prime_chart(pi_list, mt_list):
    chart = {m: [] for m in mt_list}
    for i, pi in enumerate(pi_list):
        covered = get_covered_minterms(pi)
        for m in mt_list:
            if m in covered:
                chart[m].append(i)
    return chart


def find_min_sop(chart, pi_list):
    minterms = list(chart.keys())
    num_pis = len(pi_list)
    for r in range(1, num_pis + 1):
        for combo in combinations(range(num_pis), r):
            covered = set()
            for idx in combo:
                covered |= get_covered_minterms(pi_list[idx])
            if all(m in covered for m in minterms):
                return [pi_list[i] for i in combo]
    return []


def get_covered_minterms(pi_expr):
    vars_order = ['A', 'B', 'C', 'D']  # 支援最多四變數
    covered = set()

    for bits in product([0, 1], repeat=len(vars_order)):
        terms = [f"{v}'" if b == 0 else v for v, b in zip(vars_order, bits)]
        if match_pi(pi_expr, terms):
            idx = int(''.join(map(str, bits)), 2)
            covered.add(idx)
    return covered


def match_pi(pi_expr, term_bits):
    pi_parts = pi_expr.replace(' ', '').split('+')
    for part in pi_parts:
        if all(t in term_bits for t in split_literals(part)):
            return True
    return False


def split_literals(expr):
    i = 0
    literals = []
    while i < len(expr):
        if i + 1 < len(expr) and expr[i+1] == "'":
            literals.append(expr[i:i+2])
            i += 2
        else:
            literals.append(expr[i])
            i += 1
    return literals


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

