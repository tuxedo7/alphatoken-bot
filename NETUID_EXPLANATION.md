# NetUID in Stake/Unstake Operations - Explained

## Key Point: Events vs Extrinsics

**CRITICAL**: NetUID comes from **EXTRINSICS**, not EVENTS!

```
┌─────────────────────────────────────────────────────────────┐
│  BLOCK                                                       │
│                                                               │
│  ┌─────────────────────┐      ┌──────────────────────┐      │
│  │  EXTRINSIC          │      │  EVENT               │      │
│  │  (Function Call)    │      │  (What Happened)     │      │
│  ├─────────────────────┤      ├──────────────────────┤      │
│  │ Function:           │      │ Type: StakeAdded     │      │
│  │   add_stake         │      │                      │      │
│  │                     │      │ Data:                │      │
│  │ Parameters:         │      │  - hotkey            │      │
│  │  - netuid: 67  ✅   │      │  - coldkey           │      │
│  │  - hotkey           │      │  - amount            │      │
│  │  - amount           │      │  - NO NETUID! ❌     │      │
│  └─────────────────────┘      └──────────────────────┘      │
│         │                              ▲                     │
│         │                              │                     │
│         └──────────────────────────────┘                     │
│              extrinsic causes event                          │
└─────────────────────────────────────────────────────────────┘
```

**We monitor EVENTS (to detect stakes), but extract NETUID from EXTRINSICS!**

## Why Some Netuids are None or Unknown

When monitoring Bittensor stake/unstake transactions, you may see different netuid values or "Unknown". Here's why:

## Types of Staking Operations

### 1. **Dynamic Subnet Staking** (Has NetUID)
- **Modern API**: `add_stake(netuid, hotkey, amount)` or similar
- **Alpha Tokens**: Dynamic subnets use alpha tokens
- **NetUID Present**: The extrinsic explicitly includes netuid parameter
- **Example**: Staking to subnet 67, 71, etc.

```python
# Extrinsic has netuid in call_args
{'name': 'netuid', 'value': 67}
```

### 2. **Root Network Staking** (NetUID = 0)
- **Old API**: `add_stake(hotkey, amount)` without netuid
- **Root Network**: Staking to root network (netuid 0)
- **Global Staking**: Not subnet-specific
- **Example**: Traditional TAO staking before dynamic subnets

```python
# No netuid in extrinsic, old-style function
call_function: 'add_stake'  # No netuid parameter
```

### 3. **Ambiguous Cases** (Multiple Subnets)
- **Hotkey on Multiple Subnets**: Can't determine which subnet
- **Shows All**: Displays list like `[1, 3, 21]`
- **Example**: A hotkey registered on 3 different subnets

```python
# Hotkey registered on multiple subnets
netuids: [1, 3, 21]
```

### 4. **Unknown Cases**
- **New Hotkeys**: Not yet registered on any subnet
- **Parsing Errors**: Can't extract data from extrinsic
- **Pre-Registration**: Staking before subnet registration
- **Shows**: "Unknown"

```python
# Hotkey not found on any subnet
netuids: []  # Empty list
```

## NetUID Detection Logic

The monitor uses this priority order:

### Step 1: Check Extrinsic Parameters
```python
# Look for netuid in extrinsic call arguments
for arg in call_args:
    if arg['name'] in ['netuid', 'net_uid']:
        return arg['value']  # Found explicit netuid
```

### Step 2: Check Function Type
```python
# Old-style staking without netuid = root network
if call_function in ['add_stake', 'remove_stake']:
    return 0  # Root network
```

### Step 3: Query Hotkey Registration
```python
# Check which subnets the hotkey is registered on
netuids = get_netuids_for_hotkey(hotkey)

if len(netuids) == 1:
    return netuids[0]  # Only on one subnet
elif len(netuids) > 1:
    return netuids  # Multiple subnets [1, 3, 21]
else:
    return 'Unknown'  # Not registered anywhere
```

## Display Examples

### Example 1: Dynamic Subnet (Clear)
```
Block      ExIdx  Type     Address                                      Amount (TAO)      NetUID
1234567    2      STAKE    5HGJhgUXAk...D7oueJFe                        10.500000000      67
```
✅ **Clear**: Staking to subnet 67 (dynamic subnet with alpha)

### Example 2: Root Network
```
Block      ExIdx  Type     Address                                      Amount (TAO)      NetUID
1234568    1      STAKE    5D1tX2W1wu...zKRe                            5.000000000       0 (Root)
```
✅ **Clear**: Staking to root network (old-style TAO staking)

### Example 3: Multiple Subnets (Ambiguous)
```
Block      ExIdx  Type     Address                                      Amount (TAO)      NetUID
1234569    3      UNSTAKE  5EhvL1FV...pGZP                               2.000000000       [1, 3, 21]
```
⚠️ **Ambiguous**: Hotkey on 3 subnets, can't determine which one

### Example 4: Unknown
```
Block      ExIdx  Type     Address                                      Amount (TAO)      NetUID
1234570    4      STAKE    5FnLYfn...kQwE                                1.000000000       Unknown
```
⚠️ **Unknown**: New hotkey, not registered on any subnet yet

## Common Questions

### Q: Why is my stake showing "Unknown"?
**A:** Your hotkey isn't registered on any subnet yet. This is normal for:
- New hotkeys
- Staking before registration
- Root network operations that didn't parse correctly

### Q: Why do I see multiple netuids like [1, 3, 21]?
**A:** Your hotkey is registered on multiple subnets. The stake operation applies globally to the hotkey, but we can't determine which specific subnet it's for without a netuid parameter in the extrinsic.

### Q: What's the difference between netuid 0 and "Unknown"?
**A:**
- **0 (Root)**: Confirmed root network staking (old-style API)
- **Unknown**: Can't determine the network (new hotkey, parsing error, etc.)

### Q: How can I get accurate netuid for all stakes?
**A:** Use the modern staking API with explicit netuid parameters. The bittensor SDK does this automatically for dynamic subnets.

## Technical Details

### Bittensor Staking Evolution

**Old System (Root Network)**:
- Single TAO token
- Global staking to hotkeys
- No subnet-specific staking
- Functions: `add_stake(hotkey, amount)`

**New System (Dynamic Subnets)**:
- Alpha tokens per subnet
- Subnet-specific staking
- NetUID required
- Functions: `add_stake(netuid, hotkey, amount)`

### Storage Structure

```python
# Root network staking (old)
SubtensorModule::Stake[(hotkey, coldkey)] = amount

# Dynamic subnet staking (new)
SubtensorModule::Stake[(netuid, hotkey, coldkey)] = amount
```

### Event Format (No NetUID!)

**IMPORTANT**: Events do NOT contain netuid information!

Both old and new systems emit the same event format:
```python
# Event attributes (tuple of 3 values):
StakeAdded(hotkey, coldkey, amount)
StakeRemoved(hotkey, coldkey, amount)

# Example:
attributes = ('5HGJhgUXAk...', '5D1tX2W1wu...', 10500000000)
             # hotkey,         coldkey,         amount (RAO)
             # NO NETUID HERE!
```

**The netuid MUST be extracted from the extrinsic call parameters, not the event.**

### Extrinsic Parameters (Has NetUID)

```python
# Modern dynamic subnet staking extrinsic:
SubtensorModule.add_stake(
    netuid=67,           # ✅ NetUID is here!
    hotkey='5HGJh...',
    amount=10.5
)

# Old root network staking extrinsic:
SubtensorModule.add_stake(
    hotkey='5HGJh...',   # ❌ No netuid parameter
    amount=10.5
)
```

**This is why we need to parse extrinsics - events alone don't tell us which subnet!**

## Code Implementation

### Data Flow

```
1. Monitor detects block with events
   ↓
2. Loop through events looking for StakeAdded/StakeRemoved
   ↓
3. Extract from EVENT:
   - hotkey (from attributes[0])
   - coldkey (from attributes[1])
   - amount (from attributes[2])
   - extrinsic_idx (which extrinsic caused this event)
   ↓
4. Extract from EXTRINSIC (using extrinsic_idx):
   - netuid (from call_args if present)
   - call_function (add_stake, remove_stake, etc.)
   ↓
5. If netuid not in extrinsic:
   - Query blockchain for hotkey's subnet registrations
   - Determine netuid based on registrations
```

### Practical Code Example

```python
# Step 1: Loop through events in a block
for event in events:
    if event.value['event_id'] in ['StakeAdded', 'StakeRemoved']:
        
        # Step 2: Get data from EVENT (no netuid here!)
        attributes = event.value['attributes']
        hotkey = str(attributes[0])      # ✅ From event
        coldkey = str(attributes[1])     # ✅ From event
        amount_rao = int(attributes[2])  # ✅ From event
        extrinsic_idx = event.value.get('extrinsic_idx')  # Links to extrinsic
        
        # Step 3: Get netuid from EXTRINSIC (not event!)
        netuid = get_netuid_from_extrinsic(block, extrinsic_idx)  # ✅ From extrinsic
        
        # Inside get_netuid_from_extrinsic():
        extrinsic = block['extrinsics'][extrinsic_idx]
        call = extrinsic.value['call']
        
        # Look for netuid in extrinsic call arguments
        for arg in call.get('call_args', []):
            if arg.get('name') == 'netuid':
                return arg.get('value')  # Found netuid in extrinsic!
        
        # If not found in extrinsic, it's None
        return None
```

### Key Functions in `monitoring_block.py`:

1. **`get_current_block_data()`**: Main function
   - Reads **events** to detect stake operations
   - Gets basic data (hotkey, coldkey, amount) from event
   - Calls `get_netuid_from_extrinsic()` to get netuid

2. **`get_netuid_from_extrinsic()`**: NetUID extraction
   - Parses **extrinsic** (not event!) for netuid parameter
   - Returns netuid if found, 0 for root network, None if can't parse

3. **`get_netuids_for_hotkey()`**: Fallback method
   - Queries blockchain storage for hotkey registrations
   - Used when extrinsic doesn't contain netuid
   - Returns list of all subnets hotkey is registered on

## Summary

**Netuids can be None/Unknown because:**
1. ✅ **By design**: Root network operations don't have netuid
2. ✅ **Timing**: Staking before subnet registration
3. ✅ **Ambiguity**: Hotkey on multiple subnets
4. ⚠️ **Errors**: Parsing issues (rare)

This is **normal behavior** and reflects the different types of staking operations in the Bittensor network!

