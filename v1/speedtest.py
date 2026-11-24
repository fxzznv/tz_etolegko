#!/usr/bin/env python3
"""Простой замер скорости скачивания.

Делает 10 последовательных запросов к заданному URL, дожидается полного
ответа на каждый, считает среднее время запроса и среднюю скорость
скачивания. Скорость выводится в МБ/с (десятичные, 1 МБ = 1 000 000 байт).
"""

import sys
import time
import urllib.request

REQUESTS = 10
TIMEOUT = 60
USER_AGENT = "speedtest-cli/1.0"


def human_size(num_bytes: float) -> str:
    value = float(num_bytes)
    for unit in ("B", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} ГБ"


def fetch(url: str) -> tuple[int, float]:
    """Скачивает url целиком, возвращает (байт, секунды)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        total = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
    elapsed = time.perf_counter() - start
    return total, elapsed


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Использование: {sys.argv[0]} <URL>", file=sys.stderr)
        return 1

    url = sys.argv[1]
    sizes = []
    times = []

    print(f"Скачиваю {REQUESTS} раз: {url}\n")
    for i in range(1, REQUESTS + 1):
        try:
            size, elapsed = fetch(url)
        except Exception as e:
            print(f"Запрос {i}: ОШИБКА — {e}")
            continue
        sizes.append(size)
        times.append(elapsed)
        speed = size / elapsed / 1_000_000 if elapsed > 0 else 0
        print(
            f"Запрос {i:2d}: {human_size(size):>10} за {elapsed:6.2f} с "
            f"({speed:8.2f} МБ/с)"
        )

    if not times:
        print("\nНе удалось получить ни одного ответа.", file=sys.stderr)
        return 1

    avg_time = sum(times) / len(times)
    total_bytes = sum(sizes)
    total_time = sum(times)
    avg_speed = total_bytes / total_time / 1_000_000 if total_time > 0 else 0

    print("\n" + "=" * 50)
    print(f"Успешных запросов:      {len(times)} / {REQUESTS}")
    print(f"Среднее время запроса:  {avg_time:.2f} с")
    print(f"Всего скачано:          {human_size(total_bytes)}")
    print(f"Средняя скорость:       {avg_speed:.2f} МБ/с")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
