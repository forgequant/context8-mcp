# Руководство по тестированию системы

## 1. Проверка статуса всех сервисов

```bash
docker compose ps
```

**Ожидаемый результат:** Все контейнеры должны быть `Up` и `healthy`:
- context8-producer
- context8-mcp
- context8-analytics
- context8-redis
- context8-prometheus

---

## 2. Проверка health endpoints

### Producer health
```bash
curl http://localhost:9101/metrics | grep "nt_node_heartbeat"
```
**Ожидается:** `nt_node_heartbeat{node="nt-producer-001"} 1.0`

### MCP Server health
```bash
curl http://localhost:8080/health
```
**Ожидается:** `{"status":"healthy"}`

---

## 3. Получение рыночных отчетов через MCP

### BTCUSDT отчет
```bash
curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | jq .
```

### ETHUSDT отчет
```bash
curl -s "http://localhost:8080/get_report?symbol=ETHUSDT" | jq .
```

### Компактный вывод (основные метрики)
```bash
curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | \
  jq '{symbol, last_price, spread_bps, data_age_ms, health_score: .health.score}'
```

**Ожидаемые поля:**
- `symbol`: "BTCUSDT" или "ETHUSDT"
- `last_price`: текущая цена
- `spread_bps`: спред в базисных пунктах (обычно < 1.0)
- `data_age_ms`: возраст данных (должен быть < 1000ms для "ok" статуса)
- `health_score`: 0-100 (80+ это хорошо)

---

## 4. Проверка метрик Prometheus

### Количество опубликованных отчетов
```bash
curl -s http://localhost:9101/metrics | grep "nt_report_publish_total"
```

### Латентность fast cycle
```bash
curl -s http://localhost:9101/metrics | grep "nt_calc_latency_ms_count"
```

### Все NautilusTrader метрики
```bash
curl -s http://localhost:9101/metrics | grep "^nt_" | grep -v "^#"
```

**Ожидается:**
- `nt_report_publish_total` растет со временем (каждые 250ms новый отчет)
- `nt_calc_latency_ms_count` показывает количество выполненных циклов
- `nt_node_heartbeat` = 1.0 (узел жив)
- `nt_symbols_assigned` = 2 (BTCUSDT + ETHUSDT)

---

## 5. Проверка данных в Redis

### Список ключей
```bash
docker compose exec -T redis redis-cli KEYS "report:*"
```

### Прямое чтение отчета из Redis
```bash
docker compose exec -T redis redis-cli GET "report:BTCUSDT" | jq .
```

### Статистика Redis
```bash
docker compose exec -T redis redis-cli INFO stats | grep -E "ops_per_sec|keyspace_hits"
```

**Ожидается:**
- 2 ключа: `report:BTCUSDT`, `report:ETHUSDT`
- Высокий `ops_per_sec` (> 1000)
- `keyspace_hits` > `keyspace_misses`

---

## 6. Проверка логов

### Producer логи (аналитика)
```bash
docker compose logs producer --tail=50 | grep -E "Analytics|report_published|fast_cycle"
```

### MCP Server логи
```bash
docker compose logs mcp --tail=30 | grep -E "ERROR|cache_read"
```

### Все ошибки в системе
```bash
docker compose logs --tail=100 | grep -iE "error|warn|exception"
```

**Ожидается:**
- Нет критических ошибок (ERROR)
- `fast_cycle_start: processing 2 symbols` каждые 250ms
- Warnings про API key можно игнорировать (для публичных данных API key не нужен)

---

## 7. Мониторинг в реальном времени

### Следить за обновлениями отчетов
```bash
watch -n 1 'curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | jq "{price: .last_price, spread: .spread_bps, age_ms: .data_age_ms}"'
```

### Следить за метриками
```bash
watch -n 2 'curl -s http://localhost:9101/metrics | grep "nt_report_publish_total"'
```

### Логи producer в реальном времени
```bash
docker compose logs producer --follow | grep -E "report_published|fast_cycle"
```

---

## 8. Тестирование производительности

### Проверка частоты обновлений (должно быть ~4 отчета в секунду на символ)
```bash
# Подождать 5 секунд и посчитать разницу
curl -s http://localhost:9101/metrics | grep 'nt_report_publish_total{symbol="BTCUSDT"}' | awk '{print $2}' > /tmp/count1.txt
sleep 5
curl -s http://localhost:9101/metrics | grep 'nt_report_publish_total{symbol="BTCUSDT"}' | awk '{print $2}' > /tmp/count2.txt
echo "Reports per second: $(echo "scale=2; ($(cat /tmp/count2.txt) - $(cat /tmp/count1.txt)) / 5" | bc)"
```

### Проверка задержки данных (должна быть < 1000ms)
```bash
for i in {1..10}; do
  curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | jq -r '.data_age_ms'
  sleep 1
done
```

---

## 9. Тестирование отказоустойчивости

### Перезапуск producer (отчеты должны восстановиться)
```bash
docker compose restart producer
sleep 10
curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | jq '{symbol, last_price}'
```

### Перезапуск MCP (должен сразу читать из Redis)
```bash
docker compose restart mcp
sleep 3
curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | jq '{symbol, last_price}'
```

---

## 10. Проверка обработки ошибок

### Несуществующий символ
```bash
curl -s "http://localhost:8080/get_report?symbol=INVALID" | jq .
```
**Ожидается:** `{"error": "symbol_not_indexed", "message": "Symbol not found in cache"}`

### Пустой символ
```bash
curl -s "http://localhost:8080/get_report" | jq .
```
**Ожидается:** 400 Bad Request

---

## Быстрая проверка (all-in-one)

```bash
#!/bin/bash
echo "=== System Status ==="
docker compose ps

echo -e "\n=== Health Checks ==="
echo "Producer: $(curl -s http://localhost:9101/metrics | grep 'nt_node_heartbeat' | awk '{print $2}')"
echo "MCP: $(curl -s http://localhost:8080/health | jq -r .status)"

echo -e "\n=== Market Data ==="
curl -s "http://localhost:8080/get_report?symbol=BTCUSDT" | \
  jq '{symbol, price: .last_price, spread: .spread_bps, age: .data_age_ms, health: .health.score}'

echo -e "\n=== Metrics ==="
curl -s http://localhost:9101/metrics | grep "nt_report_publish_total"

echo -e "\n=== Redis Stats ==="
docker compose exec -T redis redis-cli INFO stats | grep -E "instantaneous_ops_per_sec|keyspace_hits"
```

Сохраните этот скрипт как `test_system.sh` и запустите:
```bash
chmod +x test_system.sh
./test_system.sh
```

---

## Ожидаемые результаты

✅ **Все сервисы работают** (healthy status)
✅ **Отчеты обновляются каждые 250ms** (~4 reports/sec/symbol)
✅ **Задержка данных < 1000ms** (data_age_ms)
✅ **Health score 80-100** (fresh data, tight spread)
✅ **Redis ops > 1000/sec** (высокая пропускная способность)
✅ **Нет ошибок** в логах (кроме предупреждений про API key)

---

## Проблемы и решения

### Проблема: "data_age_ms" > 2000
**Решение:** Перезапустите producer: `docker compose restart producer`

### Проблема: "symbol_not_indexed"
**Причина:** Данные еще не опубликованы в Redis
**Решение:** Подождите 5-10 секунд после старта producer

### Проблема: "backend_unavailable"
**Причина:** Redis недоступен
**Решение:** Проверьте статус: `docker compose ps redis`

### Проблема: Метрики не обновляются
**Решение:** Проверьте логи: `docker compose logs producer --tail=50`
