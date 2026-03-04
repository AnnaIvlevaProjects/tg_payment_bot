# GBN: практичная схема хранения и быстрого поиска (Python 3.12)

Ниже — рабочая стратегия для корпуса Google Books Ngram (GBN), рассчитанная на большой объём данных и быстрые итерации.

## 1) Архитектура

1. **RAW**: храните исходные архивы как есть (`GBN_2020_English/...`, `GBN_2020_Russia/...`).
2. **INDEX**: конвертируйте в Parquet (длинный формат, 1 строка = 1 ngram + 1 год).
3. **QUERY**: делайте ad-hoc запросы через DuckDB без отдельного сервера.

## 2) Схема индекса

В parquet сохраняются колонки:

- `lang`
- `n`
- `ngram_raw`
- `ngram_lex`
- `pos_pattern`
- `year`
- `match_count` — сколько раз ngram встретилась в данном году
- `volume_count` — в скольких книгах встретилась ngram (полезно как «количество книг»)

## 3) Что реализовано в репозитории

### `scripts/gbn_index.py`

Индексация RAW -> Parquet:
- потоковое чтение `.gz/.bz2/.txt/.csv`;
- парсинг строк GBN `ngram<TAB>year,match_count,volume_count...`;
- выделение лексемы и POS-паттерна из `_POS`;
- запись частей в `data/index/lang=<lang>/n=<n>/part-*.parquet`.

### `scripts/gbn_query.py`

Запросы по индексу с фильтрами:
- `--exact`, `--prefix`, `--contains`, `--regex`
- `--n`
- `--pos`
- `--year-from`, `--year-to`
- `--metric both|matches|books`

Где:
- `matches` = сумма `match_count` (частота употребления),
- `books` = сумма `volume_count` (количество книг).

## 4) Запуск одной командой (PyCharm-friendly)

Добавлен `run_demo.sh`.

Он:
1. проверяет/устанавливает зависимости из `requirements.txt`,
2. создаёт мини-датасет,
3. строит parquet-индекс,
4. выполняет 2 запроса (частоты и количество книг).

Запуск:

```bash
./run_demo.sh
```

В PyCharm можно сделать Run Configuration на `run_demo.sh`.

## 5) Полный рабочий сценарий на ваших данных

1. Установить зависимости:

```bash
pip install -r requirements.txt
```

2. Индексация русского:

```bash
python scripts/gbn_index.py \
  --source-root /path/to/GBN_2020_Russia \
  --output-root /path/to/data/index \
  --lang russian \
  --n 1 2 3 4 5 \
  --lowercase
```

3. Индексация английского:

```bash
python scripts/gbn_index.py \
  --source-root /path/to/GBN_2020_English \
  --output-root /path/to/data/index \
  --lang english \
  --n 1 2 3 4 5 \
  --lowercase
```

4. Пример запроса по фразе и годам:

```bash
python scripts/gbn_query.py \
  --index-root /path/to/data/index \
  --lang russian \
  --n 2 \
  --exact "новый год" \
  --year-from 1900 --year-to 2020 \
  --metric both
```

5. Только «количество книг»:

```bash
python scripts/gbn_query.py \
  --index-root /path/to/data/index \
  --lang russian \
  --n 2 \
  --exact "новый год" \
  --metric books
```
