-- Release lease only if still owner
-- KEYS[1] = report:writer:{symbol}
-- ARGV[1] = node_id (expected owner)
-- Returns: 1 if released, 0 if not owner

local current_owner = redis.call("GET", KEYS[1])
if current_owner == ARGV[1] then
    redis.call("DEL", KEYS[1])
    return 1
else
    return 0
end
