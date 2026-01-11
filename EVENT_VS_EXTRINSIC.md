# Events vs Extrinsics: Where NetUID Comes From

## Quick Answer

**NetUID comes from EXTRINSICS, not EVENTS.**

## Why?

Bittensor's `StakeAdded` and `StakeRemoved` events **do not include netuid** in their data structure.

## Data Structure Comparison

### Event Structure ❌ (No NetUID)

```python
Event: StakeAdded
Attributes: (hotkey, coldkey, amount)
           ↓        ↓        ↓
           str      str      int (RAO)
           
# Example:
('5HGJhgUXAk...D7oueJFe', '5D1tX2W1wu...zKRe', 10500000000)
 └─ hotkey                  └─ coldkey          └─ amount
 
❌ NO NETUID IN THE EVENT!
```

### Extrinsic Structure ✅ (Has NetUID)

```python
Extrinsic: SubtensorModule.add_stake()
Call Args: {
    'netuid': 67,          ✅ NetUID is here!
    'hotkey': '5HGJh...',
    'amount': 10.5
}
```

## Why Events Don't Have NetUID

Events are **standardized notifications** emitted by the blockchain. They tell you:
- ✅ **What happened**: Stake was added or removed
- ✅ **Who**: Which hotkey and coldkey
- ✅ **How much**: Amount in RAO

But they **don't tell you**:
- ❌ **Which subnet**: NetUID is not in the event data

## Why This Design?

1. **Backwards Compatibility**: Old root network staking didn't have netuid concept
2. **Event Simplicity**: Events are generic, extrinsics are specific
3. **Storage Efficiency**: Events are compact, full details are in extrinsics

## In Practice

### What We Do

```python
# 1. Monitor events to DETECT stake operations
for event in block_events:
    if event.type == 'StakeAdded':
        hotkey = event.attributes[0]    # From event
        coldkey = event.attributes[1]   # From event
        amount = event.attributes[2]    # From event
        
        # 2. Get netuid from corresponding extrinsic
        extrinsic = block.extrinsics[event.extrinsic_idx]
        netuid = parse_netuid(extrinsic)  # From extrinsic!
```

### Why We Need Both

| Data Point | Source | Reason |
|------------|--------|--------|
| Hotkey | Event | Direct attribute |
| Coldkey | Event | Direct attribute |
| Amount | Event | Direct attribute |
| NetUID | Extrinsic | Not in event! |
| Timestamp | Block | Block metadata |

## Real Examples

### Example 1: Dynamic Subnet Stake

**Event**:
```json
{
  "event_id": "StakeAdded",
  "attributes": [
    "5HGJhgUXAk...D7oueJFe",  // hotkey
    "5D1tX2W1wu...zKRe",      // coldkey  
    10500000000               // amount (10.5 TAO)
  ]
}
```

**Corresponding Extrinsic**:
```json
{
  "call_function": "add_stake",
  "call_args": [
    {"name": "netuid", "value": 67},     // ← NetUID HERE!
    {"name": "hotkey", "value": "5HGJh..."},
    {"name": "amount", "value": 10.5}
  ]
}
```

**Result**: NetUID = 67 (from extrinsic, not event)

### Example 2: Root Network Stake (No NetUID)

**Event**:
```json
{
  "event_id": "StakeAdded",
  "attributes": [
    "5EhvL1FV...pGZP",
    "5FnLYfn...kQwE",
    5000000000
  ]
}
```

**Corresponding Extrinsic**:
```json
{
  "call_function": "add_stake",
  "call_args": [
    {"name": "hotkey", "value": "5EhvL1FV...pGZP"},
    {"name": "amount", "value": 5.0}
    // NO NETUID PARAMETER!
  ]
}
```

**Result**: NetUID = 0 (root network, inferred from lack of netuid parameter)

## Summary

✅ **Events**: Tell us stake operations happened (who, how much)  
✅ **Extrinsics**: Tell us the full context (including netuid)  
✅ **We need both**: Events for detection, extrinsics for details

**That's why some netuids are None** - if the extrinsic doesn't have a netuid parameter, we can't get it from anywhere in the blockchain data!

## Related Documentation

- See `NETUID_EXPLANATION.md` for detailed netuid handling logic
- See `monitoring_block.py` for implementation code

