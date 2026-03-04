#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEMO_DIR="${DEMO_DIR:-/tmp/gbn_demo}"
INDEX_DIR="${INDEX_DIR:-/tmp/gbn_index}"

echo "[1/5] Проверка зависимостей..."
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import duckdb, pyarrow
print(duckdb.__version__)
print(pyarrow.__version__)
PY
then
  echo "[INFO] Устанавливаю зависимости из requirements.txt"
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
fi

echo "[2/5] Подготовка мини-датасета в $DEMO_DIR"
mkdir -p "$DEMO_DIR/1grams" "$DEMO_DIR/2grams"
cat > "$DEMO_DIR/1grams/sample.txt" <<'DATA'
hello_NOUN	1900,5,2	1901,7,3
world	1900,10,4
DATA
cat > "$DEMO_DIR/2grams/sample.txt" <<'DATA'
new_ADJ year_NOUN	1900,3,2	1901,8,5
DATA

echo "[3/5] Индексация -> $INDEX_DIR"
"$PYTHON_BIN" "$ROOT_DIR/scripts/gbn_index.py" \
  --source-root "$DEMO_DIR" \
  --output-root "$INDEX_DIR" \
  --lang english \
  --n 1 2 \
  --lowercase \
  --batch-rows 2

echo "[4/5] Запрос частот (matches + books)"
"$PYTHON_BIN" "$ROOT_DIR/scripts/gbn_query.py" \
  --index-root "$INDEX_DIR" \
  --lang english \
  --n 2 \
  --exact "new year" \
  --metric both

echo "[5/5] Запрос только количества книг (books)"
"$PYTHON_BIN" "$ROOT_DIR/scripts/gbn_query.py" \
  --index-root "$INDEX_DIR" \
  --lang english \
  --n 2 \
  --exact "new year" \
  --metric books

echo "[DONE] Готово. В PyCharm можно создать Run Configuration для ./run_demo.sh"
