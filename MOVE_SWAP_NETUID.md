# Move & Swap Stake NetUID Display

## The Problem

`move_stake` and `swap_stake` operations can move stakes **between different subnets**, but the standard netuid field can't show both the origin and destination!

## The Solution

We now extract **both** `origin_netuid` and `destination_netuid` and display them with an arrow: `67→73`

## Display Format

### Regular Operations (Single NetUID)
```
Block      ExIdx  Type     Method          Address        Amount      NetUID
7069420    1      STAKE    add_stake       5HGJh...       5.000000    67
```
Shows: Single subnet (67)

### Move/Swap Operations (Origin→Destination)
```
Block      ExIdx  Type     Method          Address        Amount      NetUID
7069421    2      UNSTAKE  move_stake      5OLD...        3.000000    67→73
7069421    2      STAKE    move_stake      5NEW...        3.000000    67→73
```
Shows: Moving from subnet 67 to subnet 73

## Real Examples

### Example 1: Move Stake Between Subnets

**Operation**:
```python
SubtensorModule.move_stake(
    origin_netuid=67,
    destination_netuid=73,
    old_hotkey='5OLDhotkey...',
    new_hotkey='5NEWhotkey...',
    amount=5.0
)
```

**Monitor Display**:
```
Block      ExIdx  Type     Method          Address            Amount        NetUID
7069425    3      UNSTAKE  move_stake      5OLDhotkey...      5.000000000   67→73
7069425    3      STAKE    move_stake      5NEWhotkey...      5.000000000   67→73
```

✅ **Clear**: 5 TAO moved from old hotkey on subnet 67 to new hotkey on subnet 73

### Example 2: Move Stake Within Same Subnet

**Operation**:
```python
SubtensorModule.move_stake(
    origin_netuid=82,
    destination_netuid=82,  # Same subnet
    old_hotkey='5OLD...',
    new_hotkey='5NEW...',
    amount=2.5
)
```

**Monitor Display**:
```
Block      ExIdx  Type     Method          Address        Amount        NetUID
7069426    5      UNSTAKE  move_stake      5OLD...        2.500000000   82→82
7069426    5      STAKE    move_stake      5NEW...        2.500000000   82→82
```

✅ **Clear**: 2.5 TAO moved between hotkeys within subnet 82

### Example 3: Swap Stake Between Subnets

**Operation**:
```python
SubtensorModule.swap_stake(
    origin_netuid=1,
    destination_netuid=21,
    hotkey1='5ABC...',
    hotkey2='5XYZ...'
)
```

**Monitor Display**:
```
Block      ExIdx  Type     Method          Address        Amount        NetUID
7069427    7      UNSTAKE  swap_stake      5ABC...        10.00000000   1→21
7069427    7      STAKE    swap_stake      5XYZ...        10.00000000   1→21
7069427    7      UNSTAKE  swap_stake      5XYZ...        8.000000000   21→1
7069427    7      STAKE    swap_stake      5ABC...        8.000000000   21→1
```

✅ **Clear**: Swapped stakes between subnet 1 and subnet 21

## Parameter Names

The code looks for these parameter names:

### Origin NetUID:
- `origin_netuid` (most common)
- `netuid_from`
- `src_netuid`

### Destination NetUID:
- `destination_netuid` (most common)
- `netuid_to`
- `dest_netuid`
- `netuid` (fallback)

## Fallback Behavior

If only one netuid is found:
- Shows just that netuid (e.g., `67`)
- Might mean same subnet or parsing issue

If neither is found:
- Attempts to query hotkey registrations
- Shows `Unknown` if can't determine

## Code Implementation

### Extraction Logic:
```python
def _extract_netuid_from_call(self, call, call_function):
    if call_function in ['move_stake', 'swap_stake']:
        origin_netuid = None
        dest_netuid = None
        
        for arg in call.get('call_args', []):
            if arg['name'] in ['origin_netuid', 'netuid_from', 'src_netuid']:
                origin_netuid = int(arg['value'])
            elif arg['name'] in ['destination_netuid', 'netuid_to', 'dest_netuid']:
                dest_netuid = int(arg['value'])
        
        if origin_netuid and dest_netuid:
            return (origin_netuid, dest_netuid)  # Tuple!
```

### Display Logic:
```python
if isinstance(netuid, tuple) and len(netuid) == 2:
    origin, dest = netuid
    netuid_str = f"{origin}→{dest}"
```

## Benefits

### 🎯 **Clear Direction**
- Immediately see stake movement direction
- Understand cross-subnet rebalancing
- Track subnet migration

### 🎯 **Complete Information**
- Both origin and destination visible
- No ambiguity about which subnet
- Easy to audit stake movements

### 🎯 **Same-Subnet Detection**
- `82→82` clearly shows same subnet
- Helps identify hotkey-only changes vs subnet changes

## Comparison

### Before (Without Origin/Dest):
```
NetUID: Unknown    # Which subnet???
NetUID: 67         # Is this origin or destination???
NetUID: [67, 73]   # Which is which???
```
❌ Ambiguous and confusing

### After (With Origin→Dest):
```
NetUID: 67→73      # Clear: from 67 to 73!
NetUID: 82→82      # Clear: within subnet 82!
NetUID: 1→21       # Clear: from 1 to 21!
```
✅ Crystal clear!

## Summary

**For move_stake and swap_stake:**
- ✅ Extracts both `origin_netuid` and `destination_netuid`
- ✅ Displays as `origin→destination` (e.g., `67→73`)
- ✅ Shows movement direction clearly
- ✅ Works for both cross-subnet and same-subnet moves

**Arrow notation** `→` instantly shows the direction of stake movement! 🎯

