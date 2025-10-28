-- Acquire writer lease with fencing token
-- KEYS[1] = report:writer:{symbol}
-- KEYS[2] = report:writer:token:{symbol}
-- ARGV[1] = node_id
-- ARGV[2] = ttl_ms
-- Returns: token (int) if acquired, nil if failed

local acquired = redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2], "NX")
if acquired then
    local token = redis.call("INCR", KEYS[2])
    return token
else
    return nil
end
