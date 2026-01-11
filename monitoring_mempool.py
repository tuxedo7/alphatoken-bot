"""
Bittensor Mempool Monitor - Real-Time Stake Operations Tracker

Continuously monitors:
- Mempool: Add pending transactions when they appear, remove when mined
- Last Block: Show all stake transactions from most recent block
"""

from substrateinterface import SubstrateInterface
import time
import signal
import sys
from datetime import datetime

# ANSI color codes
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


class MempoolMonitor:
    def __init__(self, whitelist=None):
        print("Connecting to Bittensor Finney network...")
        sys.stdout.flush()
        
        self.substrate = SubstrateInterface(url='wss://entrypoint-finney.opentensor.ai:443')
        self.running = False
        self.mempool_txs = {}  # hex -> {parsed_data, first_seen_time}
        self.last_block_data = []
        # Whitelist: dict mapping address -> name
        self.whitelist = dict(whitelist) if whitelist else {}
        
        # Enable alternate screen buffer to eliminate blinking
        print("\033[?1049h", end='', flush=True)
        
        print(f"{Colors.GREEN}✓ Connected!{Colors.RESET}\n")
        sys.stdout.flush()
    
    def set_whitelist(self, address_name_map):
        """Set the whitelist of addresses with their names
        
        Args:
            address_name_map: Dict mapping address -> name
        """
        self.whitelist = dict(address_name_map) if address_name_map else {}
    
    def add_to_whitelist(self, address, name):
        """Add an address and name to the whitelist
        
        Args:
            address: Address to add
            name: Name to display for this address
        """
        self.whitelist[address] = name
    
    def get_display_name(self, address):
        """Get display name for an address (name if whitelisted, otherwise address)
        
        Args:
            address: Address to get display name for
            
        Returns:
            tuple: (display_text, is_whitelisted)
        """
        if address in self.whitelist:
            return (f"{self.whitelist[address]}", True)
        return (address, False)
    
    def is_stake_operation(self, call_function):
        """Check if this is a stake/unstake operation"""
        stake_operations = [
            'add_stake', 'add_stake_limit',
            'remove_stake', 'remove_stake_full_limit',
            'move_stake', 'move_stake_limit',
            'swap_stake', 'swap_stake_limit',
            'transfer_stake', 'transfer_stake_limit',
            'unstake_all'
        ]
        return call_function in stake_operations
    
    def parse_extrinsic(self, ext_hex):
        """Parse extrinsic and check if it's a stake operation"""
        try:
            extrinsic = self.substrate.decode_scale(
                type_string='Extrinsic',
                scale_bytes=ext_hex
            )
            
            if not extrinsic:
                return None
            
            extrinsic_data = extrinsic.value if hasattr(extrinsic, 'value') else extrinsic
            
            if 'call' not in extrinsic_data:
                return None
            
            call = extrinsic_data['call']
            call_module = call.get('call_module', '')
            call_function = call.get('call_function', '')
            call_args = call.get('call_args', [])
            
            # Try to get better structured call args using substrate decode_call
            # This gives us properly named parameters
            try:
                # Create a call dict for decode_call
                call_dict = {
                    'call_module': call_module,
                    'call_function': call_function,
                    'call_args': call_args
                }
                decoded_call = self.substrate.decode_call(call_dict)
                if decoded_call and 'call_args' in decoded_call:
                    # Use decoded call args which have better structure
                    call_args = decoded_call['call_args']
            except Exception:
                # If decode_call fails, use original call_args
                pass
            
            # Extract signer and nonce
            signer = None
            nonce = None
            if 'account_id' in extrinsic_data:
                signer = str(extrinsic_data['account_id'])
            elif 'address' in extrinsic_data:
                signer = str(extrinsic_data['address'])
            
            # Extract nonce from signature - can be in different places
            if 'signature' in extrinsic_data:
                sig_data = extrinsic_data['signature']
                if isinstance(sig_data, dict):
                    # Try different possible locations for nonce
                    if 'nonce' in sig_data:
                        try:
                            nonce = int(sig_data['nonce'])
                        except (ValueError, TypeError):
                            pass
                    elif 'era' in sig_data and isinstance(sig_data['era'], dict) and 'nonce' in sig_data['era']:
                        try:
                            nonce = int(sig_data['era']['nonce'])
                        except (ValueError, TypeError):
                            pass
            
            # Also check at top level
            if nonce is None and 'nonce' in extrinsic_data:
                try:
                    nonce = int(extrinsic_data['nonce'])
                except (ValueError, TypeError):
                    pass
            
            # Track EVM transactions - they may contain stake operations
            if call_module == 'Ethereum' and call_function == 'transact':
                # Try to extract signer from EVM transaction data
                evm_signer = signer
                evm_tx_data = None
                for arg in call_args:
                    if isinstance(arg, dict) and arg.get('name') == 'transaction':
                        tx_data = arg.get('value', {})
                        if isinstance(tx_data, dict):
                            evm_tx_data = tx_data
                            # Check for EIP1559 or Legacy transaction format
                            if 'EIP1559' in tx_data:
                                action = tx_data['EIP1559'].get('action', {})
                                if 'Call' in action:
                                    # EVM address in hex format
                                    evm_signer = action['Call']
                            elif 'Legacy' in tx_data:
                                action = tx_data['Legacy'].get('action', {})
                                if 'Call' in action:
                                    evm_signer = action['Call']
                
                # Decode EVM transaction data to extract stake operation details
                evm_details = None
                if evm_tx_data:
                    evm_details = self._decode_evm_transaction_data(evm_tx_data)
                
                # Only return if this is actually a stake operation
                if evm_details and evm_details.get('netuid') is not None:
                    # Extract amount, netuid, and nonce from decoded EVM data
                    evm_amount = evm_details.get('amount')
                    evm_netuid = evm_details.get('netuid')
                    evm_function = evm_details.get('function', 'EVM transaction')
                    evm_nonce = nonce  # Default to extrinsic nonce
                    
                    # Use EVM transaction nonce if available, otherwise use extrinsic nonce
                    if 'nonce' in evm_details:
                        evm_nonce = evm_details.get('nonce')
                    
                    return {
                        'type': 'evm',
                        'module': call_module,
                        'function': evm_function,
                        'signer': evm_signer or signer,
                        'netuid': evm_netuid,
                        'amount': evm_amount,
                        'nonce': evm_nonce
                    }
            
            # Check direct stake operation
            if call_module == 'SubtensorModule' and self.is_stake_operation(call_function):
                netuid = self._extract_netuid(call_args, call_function)
                amount = self._extract_amount(call_args, call_function)
                
                return {
                    'type': 'direct',
                    'module': call_module,
                    'function': call_function,
                    'signer': signer,
                    'netuid': netuid,
                    'amount': amount,
                    'nonce': nonce
                }
            
            # Check for nested stake operations in batch/wrapper calls
            # Recursively search through nested calls to find stake operations
            nested_result = self._find_nested_stake_operation(call_module, call_function, call_args, signer, nonce)
            if nested_result:
                return nested_result
            
            return None
            
        except Exception:
            return None
    
    def _find_nested_stake_operation(self, wrapper_module, wrapper_function, call_args, signer, nonce, depth=0, max_depth=5):
        """Recursively search for stake operations in nested calls
        
        Args:
            wrapper_module: The wrapper module name (e.g., 'Utility', 'Proxy')
            wrapper_function: The wrapper function name (e.g., 'batch', 'proxy')
            call_args: The call arguments to search through
            signer: The signer address
            nonce: The nonce
            depth: Current recursion depth
            max_depth: Maximum recursion depth to prevent infinite loops
            
        Returns:
            dict: Parsed stake operation or None
        """
        if depth >= max_depth:
            return None
        
        # Check common wrapper modules that can contain nested calls
        wrapper_modules = ['Utility', 'Proxy', 'Multisig', 'Sudo', 'XcmPallet']
        
        if wrapper_module not in wrapper_modules:
            return None
        
        # Look for nested calls in the arguments
        for arg in call_args:
            if not isinstance(arg, dict):
                continue
                
            arg_name = arg.get('name', '').lower()
            # Check for various argument names that might contain nested calls
            if arg_name in ['calls', 'call', 'other_signatories', 'call_hash', 'call_encoded']:
                nested = arg.get('value')
                if nested is None:
                    continue
                
                # Handle both single calls and lists of calls
                nested_list = nested if isinstance(nested, list) else [nested]
                
                for nested_call in nested_list:
                    if not isinstance(nested_call, dict):
                        continue
                    
                    nested_module = nested_call.get('call_module', '')
                    nested_function = nested_call.get('call_function', '')
                    nested_args = nested_call.get('call_args', [])
                    
                    # Check if this is a direct stake operation
                    if nested_module == 'SubtensorModule' and self.is_stake_operation(nested_function):
                        netuid = self._extract_netuid(nested_args, nested_function)
                        amount = self._extract_amount(nested_args, nested_function)
                        return {
                            'type': 'nested',
                            'wrapper': f"{wrapper_module}.{wrapper_function}",
                            'module': nested_module,
                            'function': nested_function,
                            'signer': signer,
                            'netuid': netuid,
                            'amount': amount,
                            'nonce': nonce
                        }
                    
                    # Recursively check deeper nesting
                    deeper_result = self._find_nested_stake_operation(
                        nested_module, nested_function, nested_args, signer, nonce, depth + 1, max_depth
                    )
                    if deeper_result:
                        # Update wrapper chain to show full nesting path
                        if 'wrapper' in deeper_result:
                            deeper_result['wrapper'] = f"{wrapper_module}.{wrapper_function}>{deeper_result['wrapper']}"
                        else:
                            deeper_result['wrapper'] = f"{wrapper_module}.{wrapper_function}"
                        return deeper_result
        
        return None
    
    def _extract_netuid(self, call_args, call_function=None):
        """Extract netuid(s) from call arguments
        
        Returns:
            int: single netuid for regular operations
            tuple: (origin_netuid, dest_netuid) for move/swap/transfer operations
            None: if no netuid found
        """
        if not call_args:
            return None
        
        # Check if this is a move/swap/transfer operation
        move_swap_transfer = ['move_stake', 'move_stake_limit', 'swap_stake', 'swap_stake_limit', 
                              'transfer_stake', 'transfer_stake_limit']
        
        if call_function and any(op in call_function for op in move_swap_transfer):
            # Extract origin and destination netuids
            origin_netuid = None
            dest_netuid = None
            netuid_values = []  # Track all netuid-like values found
            
            for arg in call_args:
                if isinstance(arg, dict):
                    arg_name = arg.get('name', '').lower()
                    int_value = self._extract_value_from_arg(arg)
                    
                    if int_value is None:
                        continue
                    
                    # Validate it looks like a netuid (0-255)
                    if not (0 <= int_value < 256):
                        continue
                    
                    # Check for origin netuid parameter names
                    if any(name in arg_name for name in ['origin_netuid', 'netuid_from', 'src_netuid', 'from_netuid', 'source_netuid', 'hotkey_netuid']):
                        origin_netuid = int_value
                    # Check for destination netuid parameter names
                    elif any(name in arg_name for name in ['destination_netuid', 'netuid_to', 'dest_netuid', 'to_netuid', 'target_netuid', 'coldkey_netuid']):
                        dest_netuid = int_value
                    # For move/swap/transfer, track netuid values
                    elif 'netuid' in arg_name:
                        netuid_values.append(int_value)
            
            # If we found named parameters, use them
            if origin_netuid is not None and dest_netuid is not None:
                return (origin_netuid, dest_netuid)
            elif origin_netuid is not None:
                return origin_netuid
            elif dest_netuid is not None:
                return dest_netuid
            
            # If we found netuid values but not named, use position
            # For move/swap/transfer, typically: param 0 = origin, param 1 = dest
            if len(netuid_values) >= 2:
                return (netuid_values[0], netuid_values[1])
            elif len(netuid_values) == 1:
                return netuid_values[0]
            
            # Fallback: try by position (first two params are usually netuids)
            if len(call_args) >= 2:
                val0 = self._extract_value_from_arg(call_args[0])
                val1 = self._extract_value_from_arg(call_args[1])
                if val0 is not None and val1 is not None:
                    if 0 <= val0 < 256 and 0 <= val1 < 256:
                        return (val0, val1)
                if val0 is not None and 0 <= val0 < 256:
                    return val0
        
        # Regular operation - extract single netuid
        # Try by name first
        for arg in call_args:
            if isinstance(arg, dict):
                arg_name = arg.get('name', '').lower()
                if 'netuid' in arg_name or 'net_uid' in arg_name:
                    value = self._extract_value_from_arg(arg)
                    if value is not None:
                        try:
                            potential_netuid = int(value)
                            if 0 <= potential_netuid < 256:
                                return potential_netuid
                        except (ValueError, TypeError):
                            continue
        
        # If not found by name, try by position (netuid is often the first parameter)
        # Try all positions to find a value that looks like a netuid
        for arg in call_args:
            value = self._extract_value_from_arg(arg)
            if value is not None:
                try:
                    potential_netuid = int(value)
                    # Netuids are typically 0-255, but we'll accept up to 1000 to be safe
                    if 0 <= potential_netuid < 1000:
                        # For regular operations, first param is usually netuid
                        # But check all positions
                        return potential_netuid
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _extract_value_from_arg(self, arg):
        """Helper to extract integer value from an argument dict, handling various formats"""
        if not isinstance(arg, dict):
            if isinstance(arg, (int, str)):
                try:
                    return int(arg)
                except (ValueError, TypeError):
                    return None
            return None
        
        # Try direct 'value' key
        value = arg.get('value')
        if value is not None:
            if isinstance(value, (int, str)):
                try:
                    return int(value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(value, dict):
                # Nested value structures
                if 'value' in value:
                    try:
                        return int(value['value'])
                    except (ValueError, TypeError):
                        pass
                # Handle Substrate type wrappers
                for key in ['U8', 'U16', 'U32', 'U64', 'U128', 'U256', 'Compact']:
                    if key in value:
                        try:
                            val = value[key]
                            # Handle nested Compact values
                            if isinstance(val, dict) and 'value' in val:
                                return int(val['value'])
                            return int(val)
                        except (ValueError, TypeError):
                            continue
        
        # Try Substrate type wrappers at top level
        for key in ['U8', 'U16', 'U32', 'U64', 'U128', 'U256', 'Compact']:
            if key in arg:
                try:
                    val = arg[key]
                    # Handle nested Compact values
                    if isinstance(val, dict) and 'value' in val:
                        return int(val['value'])
                    return int(val)
                except (ValueError, TypeError):
                    continue
        
        # Try to find any numeric value in the dict (but avoid infinite recursion)
        # Only check common keys to avoid checking everything
        for key in ['value', 'amount', 'stake', 'netuid', 'net_uid']:
            if key in arg:
                val = arg[key]
                if isinstance(val, (int, str)):
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        continue
                elif isinstance(val, dict):
                    # Try to extract from nested dict (one level only)
                    if 'value' in val:
                        try:
                            return int(val['value'])
                        except (ValueError, TypeError):
                            pass
                    # Try Substrate type wrappers in nested dict
                    for subkey in ['U8', 'U16', 'U32', 'U64', 'U128', 'U256', 'Compact']:
                        if subkey in val:
                            try:
                                subval = val[subkey]
                                if isinstance(subval, dict) and 'value' in subval:
                                    return int(subval['value'])
                                return int(subval)
                            except (ValueError, TypeError):
                                continue
        
        return None
    
    def _extract_amount(self, call_args, call_function=None):
        """Extract amount from call arguments (in RAO, will convert to TAO)
        
        Args:
            call_args: List of call arguments
            call_function: Optional function name to determine parameter position
        """
        if not call_args:
            return None
        
        # Try different parameter names that might contain the amount
        amount_param_names = ['amount', 'stake', 'value', 'stake_amount', 'tao_amount', 'rao_amount', 'hotkey_amount']
        
        # First pass: try to find by name
        for arg in call_args:
            if isinstance(arg, dict):
                arg_name = arg.get('name', '').lower()
                # Skip netuid parameters
                if 'netuid' in arg_name:
                    continue
                if any(param in arg_name for param in amount_param_names):
                    value = self._extract_value_from_arg(arg)
                    if value is not None and value > 0:
                        # If found by parameter name, trust it's an amount
                        # Amounts in RAO are typically large (1 TAO = 1e9 RAO)
                        # But we accept any positive value if it's named as an amount
                        return value / 1e9  # Convert RAO to TAO
        
        # Second pass: try by position
        # For move/swap/transfer operations: param 0 = origin_netuid, param 1 = dest_netuid, param 2 = amount
        # For regular operations: param 0 = netuid, param 1 = amount
        move_swap_transfer = ['move_stake', 'move_stake_limit', 'swap_stake', 'swap_stake_limit', 
                              'transfer_stake', 'transfer_stake_limit']
        
        is_move_swap_transfer = call_function and any(op in call_function.lower() for op in move_swap_transfer)
        
        if is_move_swap_transfer:
            # For move/swap/transfer, amount is the third parameter (index 2)
            if len(call_args) >= 3:
                value = self._extract_value_from_arg(call_args[2])
                if value is not None and value > 0:
                    # Validate it's not a netuid (netuids are typically 0-255, we use < 1000 to be safe)
                    if value >= 1000:  # Amounts in RAO should be much larger than netuids
                        return value / 1e9
            # Fallback: try other positions if expected position doesn't work
            for idx in [1, 0]:
                if idx < len(call_args):
                    value = self._extract_value_from_arg(call_args[idx])
                    if value is not None and value > 0:
                        # Validate it's not a netuid (netuids are typically 0-255, we use < 1000 to be safe)
                        if value >= 1000:  # Amounts in RAO should be much larger than netuids
                            return value / 1e9
        else:
            # For regular operations, amount is typically the second parameter (index 1)
            # But try all positions to be safe
            for idx in range(len(call_args)):
                # Skip if we already know this is a netuid (first param for regular ops)
                if idx == 0:
                    # Check if this looks like a netuid
                    value = self._extract_value_from_arg(call_args[idx])
                    if value is not None and 0 <= value < 1000:
                        continue  # Skip, this is likely netuid
                
                value = self._extract_value_from_arg(call_args[idx])
                if value is not None and value > 0:
                    # Validate it's not a netuid (netuids are typically 0-255, we use < 1000 to be safe)
                    if value >= 1000:  # Amounts in RAO should be much larger than netuids
                        return value / 1e9
        
        return None
    
    def _decode_evm_transaction_data(self, tx_data):
        """Decode EVM transaction data to extract stake operation details
        
        Returns:
            dict: {'function': str, 'amount': float, 'netuid': int, 'nonce': int} or None
        """
        try:
            # Extract input data and nonce from transaction
            input_data = None
            evm_nonce = None
            if isinstance(tx_data, dict):
                if 'EIP1559' in tx_data:
                    eip1559_data = tx_data['EIP1559']
                    # Try different possible field names
                    input_data = eip1559_data.get('input') or eip1559_data.get('data') or eip1559_data.get('input_data')
                    # Extract nonce from EIP1559 transaction
                    evm_nonce = eip1559_data.get('nonce')
                elif 'Legacy' in tx_data:
                    legacy_data = tx_data['Legacy']
                    # Try different possible field names
                    input_data = legacy_data.get('input') or legacy_data.get('data') or legacy_data.get('input_data')
                    # Extract nonce from Legacy transaction
                    evm_nonce = legacy_data.get('nonce')
            
            if not input_data:
                return None
            
            # Convert to bytes if needed
            if isinstance(input_data, bytes):
                pass  # Already bytes
            elif isinstance(input_data, str):
                if input_data.startswith('0x'):
                    input_data = bytes.fromhex(input_data[2:])
                else:
                    input_data = bytes.fromhex(input_data)
            elif isinstance(input_data, (list, tuple)):
                # Convert list of integers to bytes
                input_data = bytes(input_data)
            else:
                return None
            
            if len(input_data) < 4:
                return None
            
            # Extract function selector (first 4 bytes)
            function_selector = input_data[0:4]
            selector_hex = '0x' + function_selector.hex()
            
            # Common Bittensor EVM function selectors
            # These are keccak256 hashes of function signatures (first 4 bytes)
            FUNCTION_SELECTORS = {
                # stake(uint256,uint256) / addStake(uint256,uint256) - netuid, amount
                '0x694e80c3': 'stake',
                # removeStake(uint256,uint256) / unstake(uint256,uint256) - netuid, amount  
                '0x2c5211c6': 'remove_stake',
            }
            
            # Try to identify function from selector
            function_name = FUNCTION_SELECTORS.get(selector_hex, None)
            if function_name is None:
                # Try common variations - some contracts might use different selectors
                # For now, we'll try to infer from the data structure
                function_name = 'EVM_stake_op'
            
            # Check if this looks like a stake operation (has enough data for function + 2 uint256 params)
            # Each uint256 is 32 bytes, so we need at least 4 (selector) + 64 (2 params) = 68 bytes
            if len(input_data) >= 68:
                # Decode parameters (skip first 4 bytes which are the function selector)
                params_data = input_data[4:]
                
                # Extract netuid (first 32 bytes after selector)
                netuid_bytes = params_data[0:32]
                netuid = int.from_bytes(netuid_bytes, 'big')
                
                # Extract amount (next 32 bytes, in RAO)
                amount_bytes = params_data[32:64]
                amount_rao = int.from_bytes(amount_bytes, 'big')
                
                # Validate extracted values
                # Netuid should be in valid range (0-255 for Bittensor)
                if not (0 <= netuid < 256):
                    # If netuid is out of range, try swapping the parameters
                    # Some functions might have amount first, then netuid
                    potential_netuid = amount_rao
                    potential_amount_rao = netuid
                    if 0 <= potential_netuid < 256 and potential_amount_rao > 0:
                        netuid = potential_netuid
                        amount_rao = potential_amount_rao
                    else:
                        # If still invalid, return None
                        return None
                
                # Amount should be positive
                if amount_rao <= 0:
                    return None
                
                amount_tao = amount_rao / 1e9
                
                result = {
                    'function': function_name,
                    'amount': amount_tao,
                    'netuid': int(netuid),  # Ensure it's an int
                    'selector': selector_hex
                }
                
                # Add nonce if available
                if evm_nonce is not None:
                    try:
                        # Handle different nonce formats (int, hex string, etc.)
                        if isinstance(evm_nonce, str):
                            # Try hex string
                            if evm_nonce.startswith('0x'):
                                result['nonce'] = int(evm_nonce, 16)
                            else:
                                result['nonce'] = int(evm_nonce)
                        else:
                            result['nonce'] = int(evm_nonce)
                    except (ValueError, TypeError):
                        pass
                
                return result
            
            return None
            
        except Exception as e:
            # Debug: print error if needed
            # print(f"EVM decode error: {e}")
            return None
    
    def get_pending_extrinsics(self):
        """Get all pending extrinsics from mempool"""
        try:
            result = self.substrate.rpc_request(
                method="author_pendingExtrinsics",
                params=[]
            )
            
            if result and 'result' in result:
                return result['result']
            return []
        except Exception:
            return []
    
    def parse_block_stake_transactions(self, block_number):
        """Parse stake transactions from a block"""
        try:
            block_hash = self.substrate.get_block_hash(block_number)
            block = self.substrate.get_block(block_hash)
            events = self.substrate.get_events(block_hash)
            
            transactions = []
            
            for event in events:
                if event.value['module_id'] != 'SubtensorModule':
                    continue
                
                event_name = event.value['event_id']
                if event_name not in ['StakeAdded', 'StakeRemoved']:
                    continue
                
                attributes = event.value['attributes']
                extrinsic_idx = event.value.get('extrinsic_idx')
                
                # Parse event attributes
                if isinstance(attributes, (tuple, list)) and len(attributes) >= 3:
                    hotkey = str(attributes[0])
                    amount_rao = int(attributes[2])
                    
                    # Check for extended format with netuid (EVM transactions)
                    event_netuid = None
                    if len(attributes) >= 5:
                        try:
                            potential_netuid = int(attributes[4])
                            if 0 <= potential_netuid < 256:
                                event_netuid = potential_netuid
                        except (ValueError, TypeError):
                            pass
                    
                    # Get method and netuid from extrinsic
                    method = 'unknown'
                    netuid = event_netuid
                    
                    if extrinsic_idx is not None and extrinsic_idx < len(block['extrinsics']):
                        extrinsic = block['extrinsics'][extrinsic_idx]
                        if hasattr(extrinsic, 'value') and 'call' in extrinsic.value:
                            call = extrinsic.value['call']
                            call_module = call.get('call_module', '')
                            call_function = call.get('call_function', '')
                            
                            if call_module == 'SubtensorModule':
                                method = call_function
                                if netuid is None:
                                    netuid = self._extract_netuid(call.get('call_args', []), call_function)
                            elif call_module == 'Ethereum':
                                # Try to decode EVM transaction to get more details
                                evm_details = None
                                for arg in call.get('call_args', []):
                                    if isinstance(arg, dict) and arg.get('name') == 'transaction':
                                        tx_data = arg.get('value', {})
                                        if isinstance(tx_data, dict):
                                            evm_details = self._decode_evm_transaction_data(tx_data)
                                            break
                                
                                if evm_details:
                                    evm_function = evm_details.get('function', 'transact')
                                    method = f"EVM.{evm_function}"
                                    if netuid is None:
                                        netuid = evm_details.get('netuid')
                                else:
                                    method = 'EVM.transact'
                            elif call_module in ['Utility', 'Proxy']:
                                for arg in call.get('call_args', []):
                                    if isinstance(arg, dict) and arg.get('name') in ['calls', 'call']:
                                        nested = arg.get('value')
                                        nested_list = nested if isinstance(nested, list) else [nested]
                                        for nested_call in nested_list:
                                            if isinstance(nested_call, dict):
                                                if nested_call.get('call_module') == 'SubtensorModule':
                                                    nested_function = nested_call.get('call_function')
                                                    method = f"{call_function}>{nested_function}"
                                                    if netuid is None:
                                                        netuid = self._extract_netuid(nested_call.get('call_args', []), nested_function)
                                                    break
                    
                    # Check if extrinsic succeeded
                    success = False
                    for evt in events:
                        if evt.value.get('extrinsic_idx') == extrinsic_idx:
                            if evt.value['module_id'] == 'System':
                                if evt.value['event_id'] == 'ExtrinsicSuccess':
                                    success = True
                                elif evt.value['event_id'] == 'ExtrinsicFailed':
                                    success = False
                    
                    transactions.append({
                        'extrinsic_idx': extrinsic_idx,
                        'type': 'STAKE' if event_name == 'StakeAdded' else 'UNSTAKE',
                        'method': method,
                        'address': hotkey,
                        'amount': amount_rao / 1e9,
                        'netuid': netuid,
                        'success': success
                    })
            
            return transactions
            
        except Exception:
            return []
    
    def display_screen(self, current_block):
        """Display mempool and last block data"""
        # On alternate screen buffer, clearing is instant without blinking
        # Hide cursor, move to home, clear screen
        print("\033[?25l\033[H\033[2J", end='', flush=False)
        
        timestamp = time.strftime("%H:%M:%S")
        
        print("="*120)
        print(f"{Colors.BOLD}REAL-TIME STAKE MEMPOOL MONITOR{Colors.RESET} - {timestamp}")
        print(f"Current Block: #{current_block}")
        print("="*120)
        
        # Display mempool transactions (tracked continuously)
        print(f"\n{Colors.CYAN}{Colors.BOLD}MEMPOOL - PENDING TRANSACTIONS ({len(self.mempool_txs)}):{Colors.RESET}")
        
        if self.mempool_txs:
            print(f"  {'Age':<7} {'Type':<8} {'Method':<30} {'Address':<47} {'Amount (TAO)':<16} {'NetUID':<8} {'Nonce':<8} {'Status'}")
            print(f"  {'-'*140}")
            
            # Group transactions by (type, method, address, netuid) and merge amounts
            merged_mempool_txs = {}
            
            for _, tx_data in self.mempool_txs.items():
                parsed = tx_data['parsed']
                
                # Build method string (same as block section)
                if parsed['type'] == 'nested':
                    method = f"{parsed['wrapper']}>{parsed['function']}"
                elif parsed['type'] == 'evm':
                    method = parsed['function']  # "stake", "removeStake", or "EVM transaction"
                else:
                    method = parsed['function']
                
                # Determine type (STAKE/UNSTAKE) from function name
                function_name = parsed['function'].lower()
                # Check for unstake/remove operations (handle both direct and EVM function names)
                if any(op in function_name for op in ['remove_stake', 'removestake', 'unstake', 'remove']):
                    tx_type = 'UNSTAKE'
                else:
                    tx_type = 'STAKE'
                
                # Get address and netuid
                address = parsed['signer'] or 'Unknown'
                netuid = parsed['netuid']
                
                # Skip move_stake and transfer_stake if origin and destination are the same
                is_move_stake = 'move_stake' in function_name
                is_transfer_stake = 'transfer_stake' in function_name
                if (is_move_stake or is_transfer_stake) and isinstance(netuid, tuple) and len(netuid) == 2:
                    origin, dest = netuid
                    if origin == dest:
                        continue  # Skip displaying this transaction
                
                # Create a key for grouping (method, address, netuid)
                key = (method, address, netuid)
                
                if key not in merged_mempool_txs:
                    # Get the oldest age for this group
                    merged_mempool_txs[key] = {
                        'type': tx_type,
                        'method': method,
                        'address': address,
                        'netuid': netuid,
                        'amount': 0.0,
                        'age': int((datetime.now() - tx_data['time']).total_seconds()),
                        'nonce': parsed.get('nonce'),
                        'function_name': function_name,
                        'parsed_type': parsed['type']
                    }
                else:
                    # Update age to the oldest one
                    current_age = int((datetime.now() - tx_data['time']).total_seconds())
                    if current_age > merged_mempool_txs[key]['age']:
                        merged_mempool_txs[key]['age'] = current_age
                
                # Sum amounts
                amount = parsed.get('amount', 0.0) if parsed.get('amount') is not None else 0.0
                merged_mempool_txs[key]['amount'] += amount
            
            # Display merged transactions
            for key, merged_tx in merged_mempool_txs.items():
                age = merged_tx['age']
                full_address = merged_tx['address']
                # Get display name (name if whitelisted, otherwise truncated address)
                display_name, is_whitelisted = self.get_display_name(full_address)
                if is_whitelisted:
                    # For whitelisted addresses, get the actual name text (without color codes)
                    actual_text = self.whitelist[full_address]
                    # Truncate name if too long
                    if len(actual_text) > 47:
                        actual_text = actual_text[:44] + "..."
                    # Create colored display with proper padding
                    display_name = f"{actual_text}"
                    address_display = display_name + ' ' * (47 - len(actual_text))
                else:
                    # Truncate address if not whitelisted
                    display_name = full_address[:44] + "..." if len(full_address) > 47 else full_address
                    address_display = display_name + ' ' * (47 - len(display_name))
                amount = merged_tx['amount']
                netuid = merged_tx['netuid']
                function_name = merged_tx['function_name']
                
                # Format nonce
                nonce = merged_tx.get('nonce')
                nonce_str = str(nonce) if nonce is not None else 'Unknown'
                
                # Status is always PENDING for mempool
                status = 'PENDING'
                
                # Check if this is a move/swap/transfer operation with tuple netuid
                is_move_swap_transfer = any(op in function_name for op in ['move_stake', 'swap_stake', 'transfer_stake'])
                
                if isinstance(netuid, tuple) and len(netuid) == 2 and is_move_swap_transfer:
                    # Display as 2 rows: origin (UNSTAKE) and destination (STAKE)
                    origin_netuid, dest_netuid = netuid
                    
                    # Format amount - show Unknown if 0 or None
                    if amount is None or amount == 0.0:
                        amount_str = 'Unknown'
                    else:
                        amount_str = f"{amount:.9f}"
                    
                    # First row: UNSTAKE from origin
                    print(
                        f"{Colors.RED}"
                        f"  {age}s{' ':<5} "
                        f"{'UNSTAKE':<8} "
                        f"{merged_tx['method']:<30} "
                        f"{address_display} "
                        f"{amount_str:<16} "
                        f"{str(origin_netuid):<8} "
                        f"{nonce_str:<8} "
                        f"{status}"
                        f"{Colors.RESET}"
                    )
                    
                    # Second row: STAKE to destination
                    print(
                        f"{Colors.GREEN}"
                        f"  {age}s{' ':<5} "
                        f"{'STAKE':<8} "
                        f"{merged_tx['method']:<30} "
                        f"{address_display} "
                        f"{amount_str:<16} "
                        f"{str(dest_netuid):<8} "
                        f"{nonce_str:<8} "
                        f"{status}"
                        f"{Colors.RESET}"
                    )
                else:
                    # Regular operation - single row
                    # Format netuid
                    if netuid is None:
                        netuid_str = 'Unknown'
                    elif isinstance(netuid, tuple) and len(netuid) == 2:
                        origin, dest = netuid
                        netuid_str = f"{origin}→{dest}"
                    else:
                        netuid_str = str(netuid)
                    
                    # Color: green for stake operations, red for unstake operations
                    if merged_tx['type'] == 'STAKE':
                        color = Colors.GREEN
                    else:  # UNSTAKE
                        color = Colors.RED
                    
                    # Format amount - show Unknown if 0 or None
                    if amount is None or amount == 0.0:
                        amount_str = 'Unknown'
                    else:
                        amount_str = f"{amount:.9f}"
                    
                    print(
                        f"{color}"
                        f"  {age}s{' ':<5} "
                        f"{merged_tx['type']:<8} "
                        f"{merged_tx['method']:<30} "
                        f"{address_display} "
                        f"{amount_str:<16} "
                        f"{netuid_str:<8} "
                        f"{nonce_str:<8} "
                        f"{status}"
                        f"{Colors.RESET}"
                    )
        else:
            print(f"  {Colors.DIM}No pending stake operations{Colors.RESET}")
        
        # Display last block transactions
        print(f"\n{Colors.YELLOW}{Colors.BOLD}LAST BLOCK #{current_block} ({len(self.last_block_data)} transactions):{Colors.RESET}")
        
        if self.last_block_data:
            print(f"  {'ExIdx':<7} {'Type':<8} {'Method':<30} {'Address':<47} {'Amount (TAO)':<16} {'NetUID':<8} {'Status'}")
            print(f"  {'-'*125}")
            
            # Group transactions by (extrinsic_idx, type, method, address, netuid)
            merged_txs = {}
            
            # First pass: filter and group transactions
            
            for tx in self.last_block_data:
                # Skip move_stake and transfer_stake if origin and destination are the same
                method = tx.get('method', '').lower()
                netuid = tx.get('netuid')
                
                # Check if this is a move_stake or transfer_stake operation
                is_move_stake = 'move_stake' in method
                is_transfer_stake = 'transfer_stake' in method
                
                if (is_move_stake or is_transfer_stake) and isinstance(netuid, tuple) and len(netuid) == 2:
                    origin, dest = netuid
                    if origin == dest:
                        continue  # Skip displaying this transaction
                
                # Create a key for grouping
                ext_idx = tx['extrinsic_idx']
                tx_type = tx['type']
                tx_method = tx['method']
                tx_address = tx['address']
                
                # Use netuid as part of the key (handle tuples properly)
                key = (ext_idx, tx_type, tx_method, tx_address, netuid)
                
                if key not in merged_txs:
                    merged_txs[key] = {
                        'extrinsic_idx': ext_idx,
                        'type': tx_type,
                        'method': tx_method,
                        'address': tx_address,
                        'netuid': netuid,
                        'amount': 0.0,
                        'success': True,  # Start as True, will be False if any fails
                        'count': 0
                    }
                
                # Sum amounts and track success status
                merged_txs[key]['amount'] += tx['amount']
                merged_txs[key]['success'] = merged_txs[key]['success'] and tx['success']
                merged_txs[key]['count'] += 1
            
            # Display merged transactions
            for key, merged_tx in merged_txs.items():
                # Skip move_stake and transfer_stake if origin and destination are the same
                method = merged_tx.get('method', '').lower()
                netuid = merged_tx.get('netuid')
                
                # Check if this is a move_stake or transfer_stake operation
                is_move_stake = 'move_stake' in method
                is_transfer_stake = 'transfer_stake' in method
                
                if (is_move_stake or is_transfer_stake) and isinstance(netuid, tuple) and len(netuid) == 2:
                    origin, dest = netuid
                    if origin == dest:
                        continue  # Skip displaying this transaction
                
                full_address = merged_tx['address']
                # Get display name (name if whitelisted, otherwise truncated address)
                display_name, is_whitelisted = self.get_display_name(full_address)
                if is_whitelisted:
                    # For whitelisted addresses, get the actual name text (without color codes)
                    actual_text = self.whitelist[full_address]
                    # Truncate name if too long
                    if len(actual_text) > 47:
                        actual_text = actual_text[:44] + "..."
                    # Create colored display with proper padding
                    display_name = f"{actual_text}"
                    address_display = display_name + ' ' * (47 - len(actual_text))
                else:
                    # Truncate address if not whitelisted
                    display_name = full_address[:44] + "..." if len(full_address) > 47 else full_address
                    address_display = display_name + ' ' * (47 - len(display_name))
                
                # Format netuid (handle tuples for move/swap/transfer)
                netuid = merged_tx.get('netuid')
                if netuid is None:
                    netuid_str = 'Unknown'
                elif isinstance(netuid, tuple) and len(netuid) == 2:
                    origin, dest = netuid
                    netuid_str = f"{origin}→{dest}"
                else:
                    netuid_str = str(netuid)
                
                # Format amount - show Unknown if 0 or None
                amount = merged_tx.get('amount', 0.0)
                if amount is None or amount == 0.0:
                    amount_str = 'Unknown'
                else:
                    amount_str = f"{amount:.9f}"
                
                ext_idx = str(merged_tx['extrinsic_idx']) if merged_tx['extrinsic_idx'] is not None else 'Unknown'
                
                # Determine color based on operation type
                # STAKE operations are always green, UNSTAKE operations are red
                if merged_tx['success']:
                    if merged_tx['type'] == 'STAKE':
                        color = Colors.GREEN
                    else:  # UNSTAKE
                        color = Colors.RED
                    status = '✓ SUCCESS'
                else:
                    color = Colors.DIM
                    status = '✗ FAILED'
                
                print(
                    f"{color}"
                    f"  {ext_idx:<7} "
                    f"{merged_tx['type']:<8} "
                    f"{merged_tx['method']:<30} "
                    f"{address_display} "
                    f"{amount_str:<16} "
                    f"{netuid_str:<8} "
                    f"{status}"
                    f"{Colors.RESET}"
                )
        else:
            print(f"  {Colors.DIM}No stake transactions in last block{Colors.RESET}")
        
        print("\n" + "="*120)
        print(f"{Colors.DIM}Tracking: +Add to mempool | -Remove when mined | Press Ctrl+C to stop{Colors.RESET}")
        
        # Show cursor again after update
        print("\033[?25h", end='', flush=True)
        sys.stdout.flush()
    
    def get_block_extrinsic_hashes(self, block_hash):
        """Get extrinsic hashes from a block"""
        try:
            block = self.substrate.get_block(block_hash)
            hashes = []
            if block and 'extrinsics' in block:
                for ext in block['extrinsics']:
                    if hasattr(ext, 'value_serialized'):
                        hashes.append(f"0x{ext.value_serialized}")
            return set(hashes)
        except Exception:
            return set()
    
    def monitor(self):
        """Main monitoring loop"""
        self.running = True
        last_block = None
        
        def signal_handler(_sig, _frame):
            # Disable alternate screen buffer before exiting
            print("\033[?1049l", end='', flush=True)
            print("\033[?25h", end='', flush=True)  # Show cursor
            print(f"\n\n{Colors.YELLOW}Stopping monitor...{Colors.RESET}")
            self.running = False
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        print("Starting monitor...")
        sys.stdout.flush()
        
        try:
            while self.running:
                try:
                    # Get current block
                    current_block = self.substrate.get_block_number(self.substrate.get_chain_head())
                    
                    # Check if new block arrived
                    if last_block is not None and current_block > last_block:
                        # New block! Parse it and remove mined transactions
                        block_hash = self.substrate.get_block_hash(current_block)
                        block_ext_hashes = self.get_block_extrinsic_hashes(block_hash)
                        
                        # Remove transactions that were included in this block
                        removed = []
                        for ext_hex in list(self.mempool_txs.keys()):
                            if ext_hex in block_ext_hashes:
                                removed.append(ext_hex)
                                del self.mempool_txs[ext_hex]
                        
                        # Parse block data
                        self.last_block_data = self.parse_block_stake_transactions(current_block)
                        
                        last_block = current_block
                    elif last_block is None:
                        # First run
                        self.last_block_data = self.parse_block_stake_transactions(current_block)
                        last_block = current_block
                    
                    # Get current mempool
                    pending = self.get_pending_extrinsics()
                    current_pending = set(pending)
                    
                    # Add new transactions to tracked mempool
                    for ext_hex in pending:
                        if ext_hex not in self.mempool_txs:
                            parsed = self.parse_extrinsic(ext_hex)
                            if parsed:  # It's a stake operation
                                self.mempool_txs[ext_hex] = {
                                    'parsed': parsed,
                                    'time': datetime.now()
                                }
                    
                    # Remove transactions that are no longer in mempool (dropped)
                    for ext_hex in list(self.mempool_txs.keys()):
                        if ext_hex not in current_pending:
                            del self.mempool_txs[ext_hex]
                    
                    # Update display
                    self.display_screen(current_block)
                    
                    # Check every 0.2 seconds
                    time.sleep(0.2)
                    
                except Exception as e:
                    print(f"{Colors.RED}Error: {e}{Colors.RESET}")
                    time.sleep(1)
        
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Interrupted by user{Colors.RESET}")
            self.running = False
        
        finally:
            # Disable alternate screen buffer and restore normal screen
            print("\033[?1049l", end='', flush=True)
            print("\033[?25h", end='', flush=True)  # Show cursor
            print("\n" + "="*120)
            print("Monitoring stopped")
            print("="*120)


if __name__ == "__main__":
    import json
    import os
    
    # Load whitelist from white_list.json file
    whitelist = {}
    whitelist_file = "white_list.json"
    
    if os.path.exists(whitelist_file):
        try:
            with open(whitelist_file, 'r', encoding='utf-8') as f:
                whitelist = json.load(f)
                if whitelist:
                    print(f"{Colors.CYAN}✓ Loaded {len(whitelist)} address mappings from {whitelist_file}{Colors.RESET}")
        except json.JSONDecodeError as e:
            print(f"{Colors.YELLOW}⚠ Invalid JSON in {whitelist_file}: {e}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.YELLOW}⚠ Could not load whitelist file: {e}{Colors.RESET}")
    else:
        print(f"{Colors.DIM}ℹ {whitelist_file} not found, no whitelist loaded{Colors.RESET}")
    
    monitor = MempoolMonitor(whitelist=whitelist)
    monitor.monitor()
