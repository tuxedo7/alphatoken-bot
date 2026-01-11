# Transfer Stake Operations

## All Stake Movement Operations Now Supported!

The monitor now correctly extracts `origin_netuid` and `destination_netuid` for **all** stake movement operations:

### ✅ Supported Operations:

1. **move_stake** / **move_stake_limit**
   - Move stake between hotkeys
   - Can be same or different subnets
   - Shows: `origin→dest`

2. **swap_stake** / **swap_stake_limit**
   - Swap stakes between hotkeys
   - Can be cross-subnet swaps
   - Shows: `origin→dest`

3. **transfer_stake** / **transfer_stake_limit**
   - Transfer stake to another coldkey
   - Ownership transfer operation
   - Shows: `origin→dest`

## Real Examples

### Example 1: transfer_stake (Same Subnet)
```
Block      ExIdx  Type     Method              Address                Amount        NetUID
7070990    5      UNSTAKE  transfer_stake      5EjfvkK5NzwDeg...      1.579689290   35→35
7070990    5      STAKE    transfer_stake      5HLBDbdKfP...          1.579689290   35→35
```
✅ Transferring 1.58 TAO within subnet 35 to different coldkey

### Example 2: swap_stake_limit (Cross-Subnet)
```
Block      ExIdx  Type     Method                          Address            Amount        NetUID
7070974    8      UNSTAKE  batch_all > swap_stake_limit    5CJCCmqMWa...      3.000000000   0→121
7070974    8      STAKE    batch_all > swap_stake_limit    5CJCCmqMWa...      3.000000000   0→121
```
✅ Swapping 3 TAO from root network (0) to subnet 121 in a batch with price limit

### Example 3: move_stake (Same Subnet, Different Hotkeys)
```
Block      ExIdx  Type     Method          Address                Amount         NetUID
7070943    15     UNSTAKE  move_stake      5HpMTi3gREU...         27.293728690   120→120
7070943    15     STAKE    move_stake      5HpMTi3gREU...         27.293728690   120→120
```
✅ Moving 27.29 TAO between hotkeys within subnet 120

## Parameter Structure

All three operations use the same parameter names:

```python
{
  "origin_hotkey": "5OLD...",
  "destination_hotkey": "5NEW...",
  "origin_netuid": 35,        ← Origin subnet
  "destination_netuid": 121,  ← Destination subnet
  "alpha_amount": 1579689290
}
```

## Arrow Notation Meaning

### Same Subnet: `120→120`
- **Meaning**: Moving/swapping/transferring within the same subnet
- **Purpose**: Changing hotkeys or coldkeys without changing subnet

### Cross-Subnet: `0→121` or `35→73`
- **Meaning**: Moving between different subnets
- **Purpose**: Rebalancing across subnets or migrating

### Root to Subnet: `0→121`
- **Meaning**: Moving from root network to a dynamic subnet
- **Purpose**: Migrating old stakes to new dynamic subnets

### Subnet to Root: `121→0`
- **Meaning**: Moving from dynamic subnet to root network
- **Purpose**: Moving to more stable root network staking

## What Was Fixed

### Before (Broken):
```python
# Only checked for move_stake and swap_stake
if call_function in ['move_stake', 'swap_stake']:
    # Extract netuids
```

Result: `transfer_stake` showed as "Unknown" ❌

### After (Fixed):
```python
# Now checks for all variants
move_swap_operations = [
    'move_stake', 'swap_stake', 'transfer_stake',
    'swap_stake_limit', 'move_stake_limit', 'transfer_stake_limit'
]

if call_function in move_swap_operations:
    # Extract netuids
```

Result: All operations show `origin→dest` ✅

## Technical Details

### Extraction Logic:
```python
def _extract_netuid_from_call(self, call, call_function):
    # Check if this is a movement operation
    if call_function in move_swap_operations:
        origin_netuid = None
        dest_netuid = None
        
        # Find origin and destination
        for arg in call.get('call_args', []):
            if arg['name'] == 'origin_netuid':
                origin_netuid = int(arg['value'])
            elif arg['name'] == 'destination_netuid':
                dest_netuid = int(arg['value'])
        
        # Return tuple
        if origin_netuid is not None and dest_netuid is not None:
            return (origin_netuid, dest_netuid)
```

### Display Logic:
```python
# In monitor_realtime()
if isinstance(netuid, tuple) and len(netuid) == 2:
    origin, dest = netuid
    netuid_str = f"{origin}→{dest}"
```

## Differences Between Operations

### move_stake
- **What**: Move from one hotkey to another
- **Coldkey**: Same coldkey owns both hotkeys
- **Common use**: Validator rebalancing

### swap_stake
- **What**: Swap stakes between two hotkeys
- **Coldkey**: Can be different coldkeys
- **Common use**: Trading positions

### transfer_stake
- **What**: Transfer to a different coldkey entirely
- **Coldkey**: Different destination coldkey
- **Common use**: Ownership transfer, gifting

## Summary

✅ **Fixed**: All stake movement operations now show `origin→dest`  
✅ **Supported**: move_stake, swap_stake, transfer_stake (all variants)  
✅ **Display**: Clear arrow notation showing direction  
✅ **Nested**: Works even in batch/proxy wrappers  

No more "Unknown" netuids for stake movements! 🎉

