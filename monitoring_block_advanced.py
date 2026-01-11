"""
Bittensor Block Monitor - Track Stake/Unstake Transactions

IMPORTANT: NetUID and METHOD come from EXTRINSICS, not EVENTS!
- Events tell us: stake was added/removed (hotkey, coldkey, amount)
- Extrinsics tell us: which subnet (netuid) and method used
- We monitor events, then parse the corresponding extrinsic for details

Staking Methods (Direct):
- add_stake: Basic stake addition
- add_stake_limit: Stake with price protection
- remove_stake: Basic stake removal
- remove_stake_full_limit: Remove with price protection
- move_stake / move_stake_limit: Move stake between hotkeys/subnets (shows origin→dest)
- swap_stake / swap_stake_limit: Swap stakes between hotkeys/subnets (shows origin→dest)
- transfer_stake / transfer_stake_limit: Transfer stake to another coldkey (shows origin→dest)

Wrapped Methods (Batch/Proxy/Utility):
- batch > add_stake: Multiple stakes in one transaction
- batch_all > remove_stake: Batch with all-or-nothing semantics
- proxy > add_stake_limit: Proxy executing stake for another account
- force_batch > move_stake: Forced batch execution
- as_derivative > add_stake: Sub-account operation

The monitor parses nested calls to show both the wrapper and inner method!

Why some methods show as "unknown":
1. extrinsic_idx is None (internal/system event)
2. Wrapper without SubtensorModule inside
3. Parsing errors (rare)

NetUID Sources:
1. EXTRINSIC parameters (direct or nested)
2. Hotkey subnet registrations (fallback)
3. Function type inference (root network)
"""

from substrateinterface import SubstrateInterface
import time

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ANSI color codes
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class BlockAnalyzer:
    def __init__(self, network='finney'):
        self.substrate = SubstrateInterface(url=self._get_url(network))
        self.hotkey_cache = {}
    
    def _get_url(self, network):
        urls = {
            'finney': 'wss://entrypoint-finney.opentensor.ai:443',
            'test': 'wss://test.finney.opentensor.ai:443',
            'local': 'ws://127.0.0.1:9944'
        }
        return urls.get(network, urls['finney'])
    
    def get_netuids_for_hotkey(self, hotkey: str) -> list:
        """Query which subnets a hotkey is registered in"""
        if not hotkey or len(hotkey) < 10:
            return []
        
        if hotkey in self.hotkey_cache:
            return self.hotkey_cache[hotkey]
        
        netuids = []
        for netuid in range(64):
            try:
                result = self.substrate.query(
                    module='SubtensorModule',
                    storage_function='Uids',
                    params=[netuid, hotkey]
                )
                if result and result.value is not None:
                    netuids.append(netuid)
            except:
                continue
        
        self.hotkey_cache[hotkey] = netuids
        return netuids
    
    def parse_nested_call(self, call, debug=False):
        """Recursively parse nested calls (batch, proxy, utility, etc.)
        
        Returns:
            tuple: (netuid, method_string, is_nested)
            netuid: Can be int, tuple (origin, dest) for move/swap, or None
            method_string: Can be "batch > add_stake" or just "add_stake"
            is_nested: True if wrapped in batch/proxy/utility
        """
        call_module = call.get('call_module', '')
        call_function = call.get('call_function', '')
        
        if debug:
            print(f"  [DEBUG] Parsing call: {call_module}.{call_function}")
        
        # Check if this is a wrapper call (Batch, Proxy, Utility, etc.)
        wrapper_modules = ['Utility', 'Proxy', 'Multisig']
        wrapper_functions = ['batch', 'batch_all', 'force_batch', 'proxy', 'as_multi', 'as_derivative']
        
        is_wrapper = (call_module in wrapper_modules or 
                     call_function in wrapper_functions or
                     call_module == 'Utility' or
                     'batch' in call_function.lower() or
                     'proxy' in call_function.lower())
        
        if is_wrapper:
            # Look for nested calls in arguments
            for arg in call.get('call_args', []):
                if isinstance(arg, dict):
                    arg_name = arg.get('name', '')
                    arg_value = arg.get('value')
                    
                    # Check for 'calls' argument (batch operations)
                    if arg_name in ['calls', 'call'] and arg_value:
                        if debug:
                            print(f"  [DEBUG] Found nested calls in {arg_name}")
                        
                        # Handle single call or list of calls
                        nested_calls = arg_value if isinstance(arg_value, list) else [arg_value]
                        
                        # Process each nested call
                        for nested_call in nested_calls:
                            if isinstance(nested_call, dict) and 'call_module' in nested_call:
                                nested_module = nested_call.get('call_module', '')
                                nested_function = nested_call.get('call_function', '')
                                
                                if debug:
                                    print(f"  [DEBUG] Found nested: {nested_module}.{nested_function}")
                                
                                # Check if nested call is SubtensorModule
                                if nested_module == 'SubtensorModule':
                                    # Extract netuid(s) from nested call
                                    netuid = self._extract_netuid_from_call(nested_call, nested_function, debug)
                                    
                                    # Build method string showing wrapper
                                    method_str = f"{call_function} > {nested_function}"
                                    return netuid, method_str, True
            
            # If we get here, wrapper didn't contain SubtensorModule call
            if debug:
                print(f"  [DEBUG] Wrapper {call_module}.{call_function} but no SubtensorModule inside")
            return None, f"{call_function} (wrapper)", False
        
        # Direct SubtensorModule call (not wrapped)
        if call_module == 'SubtensorModule':
            # Extract netuid(s)
            netuid = self._extract_netuid_from_call(call, call_function, debug)
            return netuid, call_function, False
        
        # Not SubtensorModule and not a wrapper
        return None, None, False
    
    def _extract_netuid_from_call(self, call, call_function, debug=False):
        """Extract netuid(s) from a call's arguments
        
        Returns:
            int: single netuid
            tuple: (origin_netuid, dest_netuid) for move/swap/transfer operations
            None: if no netuid found
        """
        # Check if this is a stake movement operation (have origin and destination)
        # These include: move_stake, swap_stake, transfer_stake, and their variants
        move_swap_operations = [
            'move_stake', 'swap_stake', 'transfer_stake',
            'swap_stake_limit', 'move_stake_limit', 'transfer_stake_limit'
        ]
        
        if call_function in move_swap_operations:
            origin_netuid = None
            dest_netuid = None
            
            for arg in call.get('call_args', []):
                if isinstance(arg, dict):
                    arg_name = arg.get('name', '')
                    if arg_name in ['origin_netuid', 'netuid_from', 'src_netuid']:
                        origin_netuid = int(arg.get('value'))
                    elif arg_name in ['destination_netuid', 'netuid_to', 'dest_netuid', 'netuid']:
                        dest_netuid = int(arg.get('value'))
            
            if debug:
                print(f"  [DEBUG] Move/Swap: origin={origin_netuid}, dest={dest_netuid}")
            
            # Return tuple if we have both, otherwise return what we have
            if origin_netuid is not None and dest_netuid is not None:
                return (origin_netuid, dest_netuid)
            elif origin_netuid is not None:
                return origin_netuid
            elif dest_netuid is not None:
                return dest_netuid
        
        # Regular call with single netuid
        for arg in call.get('call_args', []):
            if isinstance(arg, dict) and arg.get('name') in ['netuid', 'net_uid']:
                netuid = int(arg.get('value'))
                if debug:
                    print(f"  [DEBUG] Found netuid: {netuid}")
                return netuid
        
        # Handle old-style root network staking
        if call_function in ['add_stake', 'remove_stake']:
            if debug:
                print(f"  [DEBUG] Root network operation")
            return 0
        
        return None

    def _check_same_subnet_transfer(self, call, call_function, debug=False):
        """Check if move_stake or transfer_stake has same origin and destination subnet
        
        Returns:
            bool: True if origin and destination subnets are the same (should skip), False otherwise
        """
        # Only check for move_stake and transfer_stake operations
        same_subnet_operations = [
            'move_stake', 'move_stake_limit',
            'transfer_stake', 'transfer_stake_limit'
        ]
        
        if call_function not in same_subnet_operations:
            return False
        
        origin_netuid = None
        dest_netuid = None
        
        for arg in call.get('call_args', []):
            if isinstance(arg, dict):
                arg_name = arg.get('name', '')
                
                # Extract origin and destination netuids
                if arg_name in ['origin_netuid', 'netuid_from', 'src_netuid']:
                    origin_netuid = int(arg.get('value'))
                elif arg_name in ['destination_netuid', 'netuid_to', 'dest_netuid', 'netuid']:
                    dest_netuid = int(arg.get('value'))
        
        # Check if subnets are the same
        if origin_netuid is not None and dest_netuid is not None:
            if origin_netuid == dest_netuid:
                if debug:
                    print(f"  [DEBUG] Skipping {call_function} with same subnet: {origin_netuid}")
                return True
        
        return False
    
    def get_extrinsic_details(self, block, extrinsic_idx, debug=False):
        """Extract netuid and method from extrinsic call arguments
        
        Returns:
            tuple: (netuid, method_name, should_skip)
            netuid: int if found, 0 for root network, None if can't parse
            method: str function name (can include wrapper like "batch > add_stake")
            should_skip: bool if this transaction should be skipped
        """
        try:
            if extrinsic_idx is None:
                if debug:
                    print(f"  [DEBUG] extrinsic_idx is None")
                return None, None, False
                
            if extrinsic_idx >= len(block['extrinsics']):
                if debug:
                    print(f"  [DEBUG] extrinsic_idx {extrinsic_idx} >= len(extrinsics) {len(block['extrinsics'])}")
                return None, None, False
            
            extrinsic = block['extrinsics'][extrinsic_idx]
            
            if not hasattr(extrinsic, 'value'):
                if debug:
                    print(f"  [DEBUG] Extrinsic has no 'value' attribute")
                return None, None, False
                
            if 'call' not in extrinsic.value:
                if debug:
                    print(f"  [DEBUG] Extrinsic.value has no 'call' key")
                return None, None, False
            
            call = extrinsic.value['call']
            
            # Parse the call (handles nested calls)
            netuid, method, _ = self.parse_nested_call(call, debug)
            
            # Check if this is a same-subnet transfer that should be skipped
            should_skip = False
            if method:
                # Check the innermost method (after >) for nested calls
                inner_method = method.split(' > ')[-1] if ' > ' in method else method
                should_skip = self._check_same_subnet_transfer(call, inner_method, debug)
            
            if debug:
                print(f"  [DEBUG] Parsed result: netuid={netuid}, method={method}, skip={should_skip}")
            
            return netuid, method, should_skip
            
        except Exception as e:
            if debug:
                print(f"  [DEBUG] Exception: {e}")
                import traceback
                traceback.print_exc()
            return None, None, False
    
    def _merge_duplicate_transactions(self, transactions):
        """Merge transactions with same extrinsic_index, type, method, address, and netuid
        
        Args:
            transactions: List of transaction dicts
            
        Returns:
            List of merged transactions with summed amounts
        """
        if not transactions:
            return transactions
        
        # Create a dictionary to group transactions
        merged = {}
        
        for tx in transactions:
            # Create a key from the fields that should be unique
            # Convert netuid to string for consistent hashing
            netuid_key = str(tx['netuid']) if tx['netuid'] is not None else 'None'
            
            key = (
                tx['extrinsic_index'],
                tx['type'],
                tx['method'],
                tx['address'],
                netuid_key
            )
            
            if key in merged:
                # Merge: add the amounts together
                merged[key]['tao_amount'] += tx['tao_amount']
            else:
                # First occurrence: store a copy
                merged[key] = tx.copy()
        
        # Return the merged transactions as a list
        return list(merged.values())
    
    def get_current_block_data(self, block_number: int):
        """
        Get stake transactions from current block using events
        
        NetUID Determination:
        1. If extrinsic has netuid parameter: Use that (dynamic subnet staking)
        2. If no netuid but old-style add_stake/remove_stake: Root network (0)
        3. If hotkey registered on 1 subnet: Use that subnet
        4. If hotkey registered on multiple subnets: Show all (can't determine which)
        5. If hotkey not registered anywhere: Mark as "Unknown"
        
        Note: Some stake operations are global (root network), others are subnet-specific.
        """
        transactions = []
        
        try:
            block_hash = self.substrate.get_block_hash(block_number)
            block = self.substrate.get_block(block_hash)
            events = self.substrate.get_events(block_hash)
            
            for event in events:
                if event.value['module_id'] != 'SubtensorModule':
                    continue
                
                event_name = event.value['event_id']
                if event_name not in ['StakeAdded', 'StakeRemoved']:
                    continue
                
                attributes = event.value['attributes']
                extrinsic_idx = event.value.get('extrinsic_idx')
                
                # Event format: (hotkey, coldkey, amount) or extended format with netuid
                # Extended format (EVM transactions): (hotkey, coldkey, amount, ..., netuid, ...)
                if isinstance(attributes, (tuple, list)) and len(attributes) >= 3:
                    hotkey = str(attributes[0])
                    coldkey = str(attributes[1])
                    amount_rao = int(attributes[2])
                    
                    # Check if event has extended format with netuid (position 4 or 5)
                    event_netuid = None
                    if len(attributes) >= 5:
                        # Try position 4 (common in EVM transactions)
                        try:
                            potential_netuid = int(attributes[4])
                            # Sanity check: netuid should be reasonable (0-63 typically)
                            if 0 <= potential_netuid < 256:
                                event_netuid = potential_netuid
                        except (ValueError, TypeError):
                            pass
                    
                    # Try to get netuid and method from extrinsic first
                    netuid, method, should_skip = self.get_extrinsic_details(block, extrinsic_idx)
                    
                    # Skip if this is a same-subnet move_stake or transfer_stake
                    if should_skip:
                        continue
                    
                    # Handle move_stake/swap_stake/transfer_stake with origin→dest
                    # These return a tuple (origin_netuid, dest_netuid)
                    if isinstance(netuid, tuple) and len(netuid) == 2:
                        origin_netuid, dest_netuid = netuid
                        # For display, show the relevant netuid based on event type
                        # But keep both for context
                        if event_name == 'StakeRemoved':
                            # This event is removing from origin
                            display_netuid = (origin_netuid, dest_netuid)  # Keep tuple for arrow display
                        else:  # StakeAdded
                            # This event is adding to destination
                            display_netuid = (origin_netuid, dest_netuid)  # Keep tuple for arrow display
                        netuid = display_netuid
                    
                    # If no netuid in extrinsic, try event_netuid or hotkey registrations
                    if netuid is None:
                        if event_netuid is not None:
                            # Use netuid from event (EVM transactions)
                            netuid = event_netuid
                        else:
                            # Determine based on hotkey registrations
                            netuids = self.get_netuids_for_hotkey(hotkey)
                            if len(netuids) == 1:
                                # Hotkey only on one subnet
                                netuid = netuids[0]
                            elif len(netuids) > 1:
                                # Hotkey on multiple subnets - show all
                                netuid = netuids
                            else:
                                # Not registered on any subnet - likely root network or error
                                netuid = 'Unknown'
                    
                    # Determine method display
                    if method:
                        method_display = method
                    elif extrinsic_idx is None:
                        method_display = 'N/A (no extrinsic)'
                    else:
                        # Check if this is an EVM transaction
                        try:
                            if extrinsic_idx < len(block['extrinsics']):
                                extrinsic = block['extrinsics'][extrinsic_idx]
                                if hasattr(extrinsic, 'value') and 'call' in extrinsic.value:
                                    call = extrinsic.value['call']
                                    if call.get('call_module') == 'Ethereum':
                                        method_display = 'EVM transaction'
                                    else:
                                        method_display = 'unknown'
                                else:
                                    method_display = 'unknown'
                            else:
                                method_display = 'unknown'
                        except Exception:
                            method_display = 'unknown'
                    
                    tx_data = {
                        'block_number': block_number,
                        'extrinsic_index': extrinsic_idx,
                        'address': hotkey,
                        'tao_amount': amount_rao / 1e9,
                        'netuid': netuid,
                        'method': method_display,
                        'type': 'STAKE' if event_name == 'StakeAdded' else 'UNSTAKE',
                        'hotkey': hotkey,
                        'coldkey': coldkey
                    }
                    transactions.append(tx_data)
        
        except Exception as e:
            print(f"Error: {e}")
        
        # Merge transactions with same extrinsic_index, type, method, address, and netuid
        merged_transactions = self._merge_duplicate_transactions(transactions)
        
        return merged_transactions
    
    def monitor_realtime(self, interval=12):
        """Monitor blocks in real-time"""
        print("="*120)
        print("REAL-TIME STAKE MONITOR")
        print(f"({Colors.GREEN}STAKE{Colors.RESET} = Green, {Colors.RED}UNSTAKE{Colors.RESET} = Red)")
        print("="*120)
        
        last_block = self.substrate.get_block_number(self.substrate.get_chain_head())
        
        try:
            while True:
                time.sleep(interval)
                current_block = self.substrate.get_block_number(self.substrate.get_chain_head())
                
                if current_block > last_block:
                    # Get block hash and block data for extrinsic count
                    block_hash = self.substrate.get_block_hash(current_block)
                    block = self.substrate.get_block(block_hash)
                    total_extrinsics = len(block['extrinsics']) if block and 'extrinsics' in block else 0
                    
                    transactions = self.get_current_block_data(current_block)
                    
                    # Display block header
                    print(f"\n{Colors.BOLD}╔═══ BLOCK #{current_block} ═══ Total Extrinsics: {total_extrinsics} ═══╗{Colors.RESET}")
                    
                    if transactions:
                        print(f"{'  ExIdx':<8} {'Type':<8} {'Method':<25} {'Address':<45} {'Amount (TAO)':<16} {'NetUID'}")
                        print(f"  {'-'*115}")
                        
                        for tx in transactions:
                            address = tx['address'][:43] if len(tx['address']) > 43 else tx['address']
                            
                            # Format netuid display
                            netuid = tx['netuid']
                            if netuid is None:
                                netuid_str = 'N/A'
                            elif netuid == 'Unknown':
                                netuid_str = 'Unknown'
                            elif isinstance(netuid, tuple):
                                # Handle (origin, dest) tuple for move_stake/swap_stake
                                if len(netuid) == 2:
                                    origin, dest = netuid
                                    netuid_str = f"{origin}→{dest}"
                                else:
                                    netuid_str = str(netuid)
                            elif isinstance(netuid, int):
                                if netuid == 0:
                                    netuid_str = '0 (Root)'
                                else:
                                    netuid_str = str(netuid)
                            elif isinstance(netuid, list):
                                if len(netuid) == 0:
                                    netuid_str = 'None'
                                else:
                                    netuid_str = f"[{', '.join(map(str, netuid))}]"
                            else:
                                netuid_str = str(netuid)
                            
                            # Get method name
                            method = tx.get('method', 'unknown')
                            
                            # Format extrinsic index
                            ext_idx = str(tx['extrinsic_index']) if tx['extrinsic_index'] is not None else 'N/A'
                            
                            # Color code based on transaction type
                            color = Colors.GREEN if tx['type'] == 'STAKE' else Colors.RED
                            
                            print(
                                f"{color}"
                                f"  {ext_idx:<8} "
                                f"{tx['type']:<8} "
                                f"{method:<25} "
                                f"{address:<45} "
                                f"{tx['tao_amount']:<16.9f} "
                                f"{netuid_str}"
                                f"{Colors.RESET}"
                            )
                        
                        print(f"{Colors.BOLD}╚═══ {len(transactions)} stake transaction(s) found ═══╝{Colors.RESET}")
                    else:
                        print(f"  No stake transactions in this block")
                        print(f"{Colors.BOLD}╚═══════════════════════════════════════════════╝{Colors.RESET}")
                    
                    last_block = current_block
        
        except KeyboardInterrupt:
            print("\n" + "="*120)
            print("Monitoring stopped")
            print("="*120)

if __name__ == "__main__":
    analyzer = BlockAnalyzer(network='finney')
    
    # Start real-time monitoring
    analyzer.monitor_realtime(interval=12)