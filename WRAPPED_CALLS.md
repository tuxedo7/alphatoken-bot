# Wrapped Staking Calls - Batch, Proxy, Utility

## What Changed?

The monitor now **parses nested calls** in batch, proxy, and utility operations to extract the actual staking method!

## Before vs After

### ❌ Before (Old Behavior):
```
Block      ExIdx  Type     Method      Address            Amount        NetUID
7069425    1      STAKE    unknown     5HGJhgUXAk...      5.000000000   Unknown
7069425    1      STAKE    unknown     5ABCdefGHI...      3.000000000   Unknown
```

### ✅ After (New Behavior):
```
Block      ExIdx  Type     Method              Address            Amount        NetUID
7069425    1      STAKE    batch > add_stake   5HGJhgUXAk...      5.000000000   67
7069425    1      STAKE    batch > add_stake   5ABCdefGHI...      3.000000000   73
```

Now you can see:
- 🎯 **Wrapper type**: `batch`, `proxy`, `as_derivative`, etc.
- 🎯 **Inner method**: `add_stake`, `remove_stake`, etc.
- 🎯 **NetUID**: Extracted from nested call

## Supported Wrappers

### 1. **Batch Operations**

Execute multiple calls in one transaction:

```
batch > add_stake              # Standard batch
batch_all > remove_stake       # All-or-nothing batch
force_batch > move_stake       # Force execution batch
```

**Benefits**:
- Lower transaction fees
- Atomic execution
- Multiple subnets in one tx

### 2. **Proxy Operations**

Execute on behalf of another account:

```
proxy > add_stake_limit        # Proxy executing stake
proxy > remove_stake          # Proxy executing unstake
```

**Benefits**:
- Hot wallet for cold wallet
- Delegated operations
- Security separation

### 3. **Utility Operations**

Advanced account operations:

```
as_derivative > add_stake      # Sub-account operation
```

**Benefits**:
- Sub-account management
- Complex account structures

## Real Examples

### Example 1: Batch Staking to Multiple Subnets

**Transaction**:
```python
Utility.batch([
    SubtensorModule.add_stake_limit(netuid=67, hotkey='5HGJ...', amount=5.0),
    SubtensorModule.add_stake_limit(netuid=73, hotkey='5ABC...', amount=3.0),
    SubtensorModule.add_stake_limit(netuid=82, hotkey='5XYZ...', amount=2.0)
])
```

**Monitor Display**:
```
Block      ExIdx  Type     Method                      Address            Amount        NetUID
7069425    1      STAKE    batch > add_stake_limit     5HGJhgUXAk...      5.000000000   67
7069425    1      STAKE    batch > add_stake_limit     5ABCdefGHI...      3.000000000   73
7069425    1      STAKE    batch > add_stake_limit     5XYZabcDEF...      2.000000000   82
```

✅ **Clear**: User staked to 3 subnets in a single batch transaction

### Example 2: Proxy Unstaking

**Transaction**:
```python
Proxy.proxy(
    real='5COLD...',  # Cold wallet
    call=SubtensorModule.remove_stake_full_limit(
        netuid=71,
        hotkey='5HOT...',
        min_price=0.01
    )
)
```

**Monitor Display**:
```
Block      ExIdx  Type     Method                              Address        Amount        NetUID
7069426    3      UNSTAKE  proxy > remove_stake_full_limit     5HOTkey...     10.00000000   71
```

✅ **Clear**: Hot wallet unstaking from cold wallet's hotkey with price protection

### Example 3: Batch Move Stake

**Transaction**:
```python
Utility.batch_all([
    SubtensorModule.move_stake(netuid=67, old='5OLD...', new='5NEW...', amount=5.0),
    SubtensorModule.move_stake(netuid=73, old='5OLD...', new='5NEW...', amount=3.0)
])
```

**Monitor Display**:
```
Block      ExIdx  Type     Method                  Address        Amount        NetUID
7069427    2      UNSTAKE  batch_all > move_stake  5OLDhotkey...  5.000000000   67
7069427    2      STAKE    batch_all > move_stake  5NEWhotkey...  5.000000000   67
7069427    2      UNSTAKE  batch_all > move_stake  5OLDhotkey...  3.000000000   73
7069427    2      STAKE    batch_all > move_stake  5NEWhotkey...  3.000000000   73
```

✅ **Clear**: Moving stakes from old to new hotkeys across multiple subnets atomically

## How It Works

### 1. **Detect Wrapper**
```python
if call_module in ['Utility', 'Proxy', 'Multisig']:
    # This is a wrapper call
```

### 2. **Find Nested Calls**
```python
for arg in call.get('call_args', []):
    if arg['name'] in ['calls', 'call']:
        # Found nested calls
        nested_calls = arg['value']
```

### 3. **Parse Each Nested Call**
```python
for nested_call in nested_calls:
    if nested_call['call_module'] == 'SubtensorModule':
        method = f"{wrapper_function} > {nested_call['call_function']}"
        netuid = extract_netuid(nested_call)
```

### 4. **Display Result**
```
Method: batch > add_stake_limit
        ↑       ↑
     wrapper   actual staking method
```

## Benefits

### 🎯 **Better Visibility**
- See the actual staking method even when wrapped
- Understand complex transactions
- Track batch operations

### 🎯 **NetUID Extraction**
- Extract netuid from nested calls
- No more "Unknown" for batch operations
- Accurate subnet tracking

### 🎯 **Transaction Context**
- Know if stake was via proxy (security setup)
- Know if multiple stakes were batched (efficiency)
- Understand the user's strategy

## Method String Format

```
Direct calls:
  add_stake
  remove_stake_full_limit
  
Wrapped calls:
  batch > add_stake
  proxy > remove_stake
  batch_all > add_stake_limit
  force_batch > move_stake
  as_derivative > add_stake
```

The `>` symbol clearly shows: `wrapper > inner_method`

## Edge Cases

### Multiple Nested Wrappers
```python
Utility.batch([
    Proxy.proxy(real='5COLD...', call=SubtensorModule.add_stake(...))
])
```

Currently shows the outermost wrapper:
```
Method: batch > add_stake
```

Future enhancement: Show full chain like `batch > proxy > add_stake`

### Non-Staking Nested Calls
```python
Utility.batch([
    System.remark("Hello"),
    SubtensorModule.add_stake(...)
])
```

Only the SubtensorModule call generates a stake event and will be displayed.

## Summary

✅ **Now Supported**: Batch, Proxy, Utility wrappers  
✅ **Extracts**: Both wrapper type and inner staking method  
✅ **NetUID**: Retrieved from nested calls  
✅ **Display**: Clear `wrapper > method` format  

No more "unknown" for wrapped staking operations! 🎉

