-- Renew lease only if still owner
-- KEYS[1] = report:writer:{symbol}
-- ARGV[1] = node_id (expected owner)
-- ARGV[2] = ttl_ms (new TTL)
-- Returns: 1 if renewed, 0 if not owner

local current_owner = redis.call("GET", KEYS[1])
if current_owner == ARGV[1] then
    redis.call("PEXPIRE", KEYS[1], ARGV[2])
    return 1
else
    return 0
end
