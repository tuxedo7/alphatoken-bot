# Bittensor Staking Methods Explained

## What is a "Method"?

The **method** is the specific function call used to perform the stake/unstake operation. It tells you:
- How the stake was added/removed
- What protection mechanisms were used
- What type of operation it was

## Common Staking Methods

### 📥 **add_stake**
Basic stake addition to a hotkey.
```python
SubtensorModule.add_stake(hotkey, amount)
# or with netuid:
SubtensorModule.add_stake(netuid, hotkey, amount)
```
- **When**: Standard staking operation
- **Protection**: None
- **Use**: Regular TAO staking

### 📥 **add_stake_limit**
Stake addition with price limit protection.
```python
SubtensorModule.add_stake_limit(netuid, hotkey, amount, max_price)
```
- **When**: Staking on dynamic subnets with alpha tokens
- **Protection**: Won't stake if price exceeds limit
- **Use**: Protect against unfavorable alpha/TAO exchange rates

### 📤 **remove_stake**
Basic stake removal from a hotkey.
```python
SubtensorModule.remove_stake(hotkey, amount)
# or with netuid:
SubtensorModule.remove_stake(netuid, hotkey, amount)
```
- **When**: Standard unstaking operation
- **Protection**: None
- **Use**: Regular TAO unstaking

### 📤 **remove_stake_full_limit**
Remove stake with full limit protection.
```python
SubtensorModule.remove_stake_full_limit(netuid, hotkey, min_price)
```
- **When**: Unstaking from dynamic subnets
- **Protection**: Won't unstake if price below limit
- **Use**: Protect against unfavorable alpha/TAO exchange rates

### 🔄 **move_stake**
Move stake from one hotkey to another (can move between subnets).
```python
SubtensorModule.move_stake(
    origin_netuid=67,
    destination_netuid=73,
    old_hotkey='5OLD...',
    new_hotkey='5NEW...',
    amount=5.0
)
```
- **When**: Rebalancing stakes between hotkeys or subnets
- **Protection**: Depends on parameters
- **Use**: Validator operators rebalancing their stakes
- **NetUID Display**: Shows `67→73` (origin to destination)

### 🔄 **swap_stake**
Swap stakes between two hotkeys (can swap between subnets).
```python
SubtensorModule.swap_stake(
    origin_netuid=67,
    destination_netuid=73,
    hotkey1='5ABC...',
    hotkey2='5XYZ...'
)
```
- **When**: Swapping entire stakes between hotkeys or subnets
- **Protection**: Atomic operation
- **Use**: Advanced stake management
- **NetUID Display**: Shows `67→73` (origin to destination)

## Wrapped Operations (Batch, Proxy, Utility)

### 📦 **Batch Operations**
Multiple operations in a single transaction:
```python
Utility.batch([
    SubtensorModule.add_stake(netuid=67, hotkey='5HGJ...', amount=5.0),
    SubtensorModule.add_stake(netuid=73, hotkey='5ABC...', amount=3.0)
])
```
- **Display**: `batch > add_stake` or `batch_all > add_stake`
- **Benefit**: Atomic execution, lower fees
- **Types**: `batch`, `batch_all`, `force_batch`

### 👤 **Proxy Operations**
Execute on behalf of another account:
```python
Proxy.proxy(
    real='5REAL...',
    call=SubtensorModule.add_stake(...)
)
```
- **Display**: `proxy > add_stake`
- **Benefit**: Delegated operations
- **Use**: Hot wallet executing for cold wallet

### 🔧 **Utility Operations**
Various utility wrappers:
```python
Utility.as_derivative(
    index=0,
    call=SubtensorModule.remove_stake(...)
)
```
- **Display**: `as_derivative > remove_stake`
- **Benefit**: Sub-account operations
- **Use**: Advanced account management

## Method Display in Monitor

### ✅ Known Methods
When we can parse the extrinsic, you'll see the actual method:
```
Method: add_stake_limit
Method: remove_stake_full_limit
Method: move_stake
```

### ❌ Unknown Methods
When we can't parse the extrinsic:
```
Method: unknown            # Could not parse extrinsic
Method: N/A (no extrinsic) # Event has no associated extrinsic
```

## NetUID Display for Move/Swap Operations

### 🔀 **Arrow Notation** `67→73`

For `move_stake` and `swap_stake` operations that move between subnets:

```
NetUID: 67→73
        ↑  ↑
     origin destination
```

**Examples**:
```
NetUID: 67→73     # Moving from subnet 67 to subnet 73
NetUID: 1→21      # Moving from subnet 1 to subnet 21
NetUID: 82→82     # Moving within the same subnet (different hotkeys)
```

This clearly shows the direction of the stake movement!

## Why Some Methods Show as "Unknown"

### 1. **No Extrinsic Index** (N/A)
Some events don't have an associated extrinsic:
- Internal system operations
- Automatic stake adjustments
- Events emitted by other events

### 2. **Wrapped Calls** (Shows wrapper)
The staking call is wrapped in batch/proxy/utility:
```
Method: batch > add_stake           # Batch operation containing add_stake
Method: proxy > remove_stake        # Proxy call for remove_stake
Method: batch_all > add_stake_limit # Batch with limit staking
```
These show both the wrapper and the inner staking method!

### 3. **Parsing Errors** (unknown)
Rare cases where extrinsic structure is unexpected:
- New staking methods not yet documented
- Custom implementations
- Malformed data

## Examples from Real Blocks

### Example 1: Dynamic Subnet Staking
```
Block      ExIdx  Type     Method              Address                Amount        NetUID
7069423    5      STAKE    add_stake_limit     5ELVWX5CVW...          4.000000000   73
```
✅ Clear: User staked 4 TAO to subnet 73 using limit protection

### Example 2: Move Stake (Between Subnets)
```
Block      ExIdx  Type     Method              Address                Amount        NetUID  
7069423    3      UNSTAKE  move_stake          5OLDhotkey...          0.045225659   67→73
7069423    3      STAKE    move_stake          5NEWhotkey...          0.045225659   67→73
```
✅ Clear: User moved 0.045 TAO from subnet 67 to subnet 73 using move_stake

### Example 3: Root Network Staking
```
Block      ExIdx  Type     Method              Address                Amount        NetUID
7069422    7      UNSTAKE  unknown             5Cr6nbmTqH...          31.000000000  Unknown
7069422    7      STAKE    unknown             5Cr6nbmTqH...          31.850777000  Unknown
```
⚠️ Ambiguous: Could be root network staking or unparseable extrinsic

### Example 4: Full Limit Unstake
```
Block      ExIdx  Type     Method                      Address            Amount        NetUID
7069424    2      UNSTAKE  remove_stake_full_limit     5ELVWX5CVW...      4.001802227   78
```
✅ Clear: User unstaked 4 TAO from subnet 78 with price protection

### Example 5: Batch Operation
```
Block      ExIdx  Type     Method                      Address            Amount        NetUID
7069425    1      STAKE    batch > add_stake           5HGJhgUXAk...      5.000000000   67
7069425    1      STAKE    batch > add_stake           5ABCdefGHI...      3.000000000   73
```
✅ Clear: User staked to multiple subnets in a single batch transaction

### Example 6: Proxy Operation
```
Block      ExIdx  Type     Method                      Address            Amount        NetUID
7069426    3      STAKE    proxy > add_stake_limit     5FnLYfnKQw...      10.00000000   71
```
✅ Clear: Proxy wallet staking on behalf of another account

## Method vs Event Type

**Event Type** (from event):
- STAKE = StakeAdded event
- UNSTAKE = StakeRemoved event

**Method** (from extrinsic):
- Specific function that caused the event
- Provides more details about how/why

### Relationship:
```
STAKE events can come from:
  - add_stake
  - add_stake_limit
  - move_stake (target hotkey)
  - swap_stake
  
UNSTAKE events can come from:
  - remove_stake
  - remove_stake_full_limit
  - move_stake (source hotkey)
  - swap_stake
```

## For Developers

### Extracting Method from Extrinsic:
```python
extrinsic = block['extrinsics'][extrinsic_idx]
call = extrinsic.value['call']

if call.get('call_module') == 'SubtensorModule':
    method = call.get('call_function')  # Returns method name
    # Examples: 'add_stake', 'add_stake_limit', etc.
```

### Common Patterns:
```python
# Dynamic subnet staking (with netuid)
add_stake(netuid=67, hotkey='5HGJ...', amount=10.5)

# Root network staking (no netuid)
add_stake(hotkey='5HGJ...', amount=10.5)

# With price protection
add_stake_limit(netuid=67, hotkey='5HGJ...', amount=10.5, max_price=0.05)
```

## Summary

**Method shows you HOW the stake operation was performed:**
- ✅ Regular methods: `add_stake`, `remove_stake`
- 🛡️ Protected methods: `add_stake_limit`, `remove_stake_full_limit`  
- 🔄 Movement methods: `move_stake`, `swap_stake`
- ❌ Unparseable: `unknown` or `N/A (no extrinsic)`

The method provides important context that the event type alone doesn't give you!

