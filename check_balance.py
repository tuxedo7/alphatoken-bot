#!/usr/bin/env python3
"""
Bittensor Wallet Balance Checker
Check free, staked, and total TAO balance for your wallet
"""

from substrateinterface import SubstrateInterface
import sys
import os
import json
import asyncio
from datetime import datetime
import signal

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

try:
    import bittensor as bt
    HAS_BITTENSOR = True
except ImportError:
    HAS_BITTENSOR = False
    print("Warning: bittensor SDK not found. Stake balance may not work correctly.")
    print("Install with: pip install bittensor")

# ANSI color codes
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def clear_screen():
    """Clear the terminal screen"""
    os.system('clear' if os.name != 'nt' else 'cls')

class WalletChecker:
    def __init__(self, network='finney'):
        self.substrate = SubstrateInterface(url=self._get_url(network))
        self.network = network
        self._subtensor = None  # Cache subtensor instance
        self._stake_cache = {}  # Cache stake data: {coldkey: {'data': dict, 'timestamp': float}}
        self._cache_ttl = 3.0  # Cache TTL in seconds (3 seconds default)
    
    def _get_url(self, network):
        urls = {
            'finney': 'wss://entrypoint-finney.opentensor.ai:443',
            'test': 'wss://test.finney.opentensor.ai:443',
            'local': 'ws://127.0.0.1:9944'
        }
        return urls.get(network, urls['finney'])
    
    def set_cache_ttl(self, ttl_seconds):
        """Set the cache TTL for stake data
        
        Args:
            ttl_seconds: Time-to-live in seconds (default: 3.0)
        """
        self._cache_ttl = max(0.0, float(ttl_seconds))
    
    def clear_cache(self):
        """Clear the stake data cache"""
        self._stake_cache.clear()
    
    def get_free_balance(self, address):
        """Get free (unstaked) TAO balance"""
        try:
            result = self.substrate.query(
                module='System',
                storage_function='Account',
                params=[address]
            )
            if result and result.value:
                free_balance = result.value['data']['free']
                return free_balance / 1e9  # Convert from Rao to TAO
            return 0.0
        except Exception as e:
            print(f"Error getting free balance: {e}")
            return 0.0
    
    async def get_staked_balance_async(self, coldkey):
        """Get staked TAO across all subnets using bittensor SDK
        
        Returns:
            dict: {
                'total': float,
                'by_subnet': [
                    {'netuid': int, 'hotkey': str, 'stake_tao': float},
                    ...
                ]
            }
        """
        if not HAS_BITTENSOR:
            print("⚠️ Bittensor SDK not available. Cannot retrieve stake balance.")
            return {'total': 0.0, 'by_subnet': []}
        
        # Check cache first
        import time
        current_time = time.time()
        if coldkey in self._stake_cache:
            cached = self._stake_cache[coldkey]
            if current_time - cached['timestamp'] < self._cache_ttl:
                return cached['data']
        
        try:
            # Bittensor 10.0.0+ uses synchronous API, wrap it in async
            # Bittensor 9.x uses async_subtensor
            if hasattr(bt, 'async_subtensor'):
                # Version 9.x - use sync API wrapped in executor
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._get_staked_balance_sync_v9,
                    coldkey
                )
            else:
                # Version 10.0.0+ uses synchronous subtensor API
                # Run the synchronous calls in a thread pool to avoid blocking
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._get_staked_balance_sync_v10,
                    coldkey
                )
            
            # Cache the result
            self._stake_cache[coldkey] = {
                'data': result,
                'timestamp': current_time
            }
            
            return result
                
        except Exception as e:
            print(f"Error getting staked balance: {e}")
            import traceback
            traceback.print_exc()
            return {'total': 0.0, 'by_subnet': []}
    
    def _get_staked_balance_sync_v9(self, coldkey):
        """Get staked balance using bittensor 9.x synchronous API"""
        try:
            # Reuse cached subtensor instance or create new one
            if self._subtensor is None:
                self._subtensor = bt.subtensor(network=self.network)
            subtensor = self._subtensor
            
            # Get all stakes for this coldkey
            all_stakes = subtensor.get_stake_for_coldkey(coldkey)
            
            if all_stakes is None:
                return {'total': 0.0, 'by_subnet': []}
            
            total_staked_tao = 0.0
            subnet_stakes = []
            
            # Sum up stakes across all subnets
            # Cache subnet info to avoid repeated queries
            subnet_cache = {}
            for stake_info in all_stakes:
                if stake_info and stake_info.stake:
                    try:
                        # Try direct conversion first (faster)
                        stake_tao_float = float(stake_info.stake.tao)
                        # Only query subnet if we need alpha conversion
                        if stake_tao_float > 0 and hasattr(stake_info, 'netuid'):
                            netuid = stake_info.netuid
                            # Check if we need alpha conversion (only for certain subnets)
                            # Most subnets use TAO directly, so skip subnet query if possible
                            if netuid not in subnet_cache:
                                try:
                                    subnet_cache[netuid] = subtensor.subnet(netuid=netuid)
                                except:
                                    subnet_cache[netuid] = None
                            
                            subnet_info = subnet_cache[netuid]
                            if subnet_info and hasattr(subnet_info, 'alpha_to_tao'):
                                try:
                                    stake_tao = subnet_info.alpha_to_tao(stake_info.stake)
                                    stake_tao_float = float(stake_tao.tao)
                                except:
                                    pass  # Use direct conversion if alpha conversion fails
                        
                        total_staked_tao += stake_tao_float
                        
                        subnet_stakes.append({
                            'netuid': getattr(stake_info, 'netuid', 0),
                            'hotkey': getattr(stake_info, 'hotkey_ss58', 'unknown'),
                            'stake_tao': stake_tao_float
                        })
                    except Exception:
                        pass
            
            return {'total': total_staked_tao, 'by_subnet': subnet_stakes}
            
        except Exception as e:
            print(f"Error in sync v9 stake retrieval: {e}")
            import traceback
            traceback.print_exc()
            return {'total': 0.0, 'by_subnet': []}

    def _get_staked_balance_sync_v10(self, coldkey):
        """Get staked balance using bittensor 10.0.0+ synchronous API"""
        try:
            # Reuse cached subtensor instance or create new one
            if self._subtensor is None:
                self._subtensor = bt.Subtensor(network=self.network)
            subtensor = self._subtensor
            
            # Get stake info for this coldkey
            # Returns list of StakeInfo objects
            stake_infos = subtensor.get_stake_info_for_coldkey(coldkey_ss58=coldkey)
            
            if not stake_infos:
                return {'total': 0.0, 'by_subnet': []}
            
            total_staked_tao = 0.0
            subnet_stakes = []
            
            # Sum up all stakes
            # Cache subnet info to avoid repeated queries
            subnet_cache = {}
            for stake_info in stake_infos:
                if stake_info and stake_info.stake:
                    # In v10, stake_info.stake is already a Balance object
                    # Try direct conversion first (faster)
                    try:
                        stake_tao_float = float(stake_info.stake.tao)
                        
                        # Only query subnet if we need alpha conversion
                        if hasattr(stake_info, 'netuid') and stake_info.netuid is not None:
                            netuid = stake_info.netuid
                            # Check if we need alpha conversion (only for certain subnets)
                            # Most subnets use TAO directly, so skip subnet query if possible
                            if netuid not in subnet_cache:
                                try:
                                    subnet_cache[netuid] = subtensor.subnet(netuid=netuid)
                                except:
                                    subnet_cache[netuid] = None
                            
                            subnet_info = subnet_cache[netuid]
                            if subnet_info and hasattr(subnet_info, 'alpha_to_tao'):
                                try:
                                    stake_tao = subnet_info.alpha_to_tao(stake_info.stake)
                                    stake_tao_float = float(stake_tao.tao)
                                except:
                                    pass  # Use direct conversion if alpha conversion fails
                        
                        total_staked_tao += stake_tao_float
                        
                        subnet_stakes.append({
                            'netuid': getattr(stake_info, 'netuid', 0),
                            'hotkey': getattr(stake_info, 'hotkey_ss58', 'unknown'),
                            'stake_tao': stake_tao_float
                        })
                    except Exception:
                        pass
            
            return {'total': total_staked_tao, 'by_subnet': subnet_stakes}
            
        except Exception as e:
            print(f"Error in sync v10 stake retrieval: {e}")
            import traceback
            traceback.print_exc()
            return {'total': 0.0, 'by_subnet': []}
    
    async def check_wallet(self, address, show_header=True):
        """Check wallet balance and display
        
        Returns:
            dict: Balance information including total, free, staked, and breakdown
        """
        if show_header:
            print("="*60)
            print(f"{Colors.BOLD}BITTENSOR WALLET BALANCE{Colors.RESET}")
            print(f"Network: {self.network}")
            print("="*60)
            print()
            
            # Display wallet address
            print(f"{Colors.CYAN}Wallet Address:{Colors.RESET}")
            print(f"  {address}")
            print()
            
            print("Fetching balances...")
        
        # Get balances
        free_balance = self.get_free_balance(address)
        stake_data = await self.get_staked_balance_async(address)
        
        # Handle both old float format and new dict format
        if isinstance(stake_data, dict):
            staked_balance = stake_data['total']
            subnet_stakes = stake_data['by_subnet']
        else:
            # Fallback for old format
            staked_balance = stake_data
            subnet_stakes = []
        
        total_balance = free_balance + staked_balance
        
        # Display balances
        if show_header:
            print()
        print(f"{Colors.GREEN}Free Balance:    {free_balance:>20,.9f} TAO{Colors.RESET}")
        
        # Display staked balance breakdown by subnet (only show stakes > 0.01 TAO)
        if subnet_stakes:
            print(f"{Colors.YELLOW}Staked Balance:  {staked_balance:>20,.9f} TAO{Colors.RESET}")
            # Filter stakes to only show those over 0.01 TAO
            significant_stakes = [stake for stake in subnet_stakes if stake['stake_tao'] > 0.01]
            if significant_stakes:
                print(f"  {Colors.CYAN}Breakdown by Subnet (stakes > 0.01 TAO):{Colors.RESET}")
                for stake in significant_stakes:
                    netuid = stake['netuid']
                    hotkey_short = stake['hotkey'][:10] + "..." + stake['hotkey'][-8:] if len(stake['hotkey']) > 20 else stake['hotkey']
                    stake_tao = stake['stake_tao']
                    print(f"    Subnet {netuid:>3}: {stake_tao:>18,.9f} TAO  (Validator: {hotkey_short})")
        else:
            print(f"{Colors.YELLOW}Staked Balance:  {staked_balance:>20,.9f} TAO{Colors.RESET}")
        
        print("-"*60)
        print(f"{Colors.BOLD}{Colors.RED}Total Balance:   {total_balance:>20,.9f} TAO{Colors.RESET}")
        print()
        
        return {
            'total': total_balance,
            'free': free_balance,
            'staked': staked_balance,
            'subnet_stakes': subnet_stakes
        }
    
    async def monitor_balance(self, address, interval=10):
        """Monitor balance changes over time
        
        Args:
            address: Wallet address to monitor
            interval: Check interval in seconds (default: 10)
        """
        check_count = 0
        
        try:
            while True:
                check_count += 1
                
                # Clear screen before displaying new data
                clear_screen()
                
                # Display header
                print("="*60)
                print(f"{Colors.BOLD}BITTENSOR BALANCE MONITOR{Colors.RESET}")
                print(f"Network: {self.network}")
                print("="*60)
                print()
                print(f"{Colors.CYAN}Wallet Address:{Colors.RESET}")
                print(f"  {address}")
                print()
                print(f"Check interval: {interval} seconds | Press Ctrl+C to stop")
                print(f"{Colors.CYAN}[Check #{check_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")
                print("="*60)
                print()
                
                # Get current balance
                await self.check_wallet(address, show_header=False)
                
                # Wait for next check
                print(f"⏳ Next check in {interval}s...")
                
                await asyncio.sleep(interval)
                
        except (KeyboardInterrupt, asyncio.CancelledError):
            # Handle graceful shutdown from Ctrl+C or PM2 stop
            clear_screen()
            print(f"\n{Colors.YELLOW}⚠️  Monitoring stopped{Colors.RESET}")
            print(f"Total checks performed: {check_count}")
            print()
        except Exception as e:
            # Handle any other unexpected errors
            clear_screen()
            print(f"\n{Colors.RED}❌ Error during monitoring: {e}{Colors.RESET}")
            print(f"Total checks performed: {check_count}")
            print()

def get_address_from_wallet_name(wallet_name, wallet_password=None, wallet_path=None):
    """Get coldkey address from wallet name and password"""
    
    # Default wallet path
    if not wallet_path:
        wallet_path = os.path.expanduser("~/.bittensor/wallets")
    
    wallet_dir = os.path.join(wallet_path, wallet_name)
    
    print(f"Loading wallet: {wallet_name}")
    print(f"Wallet directory: {wallet_dir}")
    
    if not os.path.exists(wallet_dir):
        print(f"{Colors.RED}✗ Wallet directory not found{Colors.RESET}")
        
        # List available wallets
        if os.path.exists(wallet_path):
            available = [d for d in os.listdir(wallet_path) 
                       if os.path.isdir(os.path.join(wallet_path, d))]
            if available:
                print(f"\nAvailable wallets in {wallet_path}:")
                for w in available:
                    print(f"  - {w}")
        return None
    
    # Method 1: Try reading from public key text file
    possible_pub_files = [
        os.path.join(wallet_dir, "coldkeypub.txt"),
        os.path.join(wallet_dir, "coldkeypub"),
        os.path.join(wallet_dir, "coldkey.pub"),
    ]
    
    for pub_file in possible_pub_files:
        if os.path.exists(pub_file):
            try:
                with open(pub_file, 'r') as f:
                    address = f.read().strip()
                    if address and address.startswith('5') and len(address) > 40:
                        print(f"✓ Loaded address from {os.path.basename(pub_file)}")
                        return address
            except Exception as e:
                pass
    
    # Method 2: Try reading from coldkey JSON file
    coldkey_file = os.path.join(wallet_dir, "coldkey")
    if not os.path.exists(coldkey_file):
        coldkey_file = os.path.join(wallet_dir, "coldkey.json")
    
    if os.path.exists(coldkey_file):
        try:
            with open(coldkey_file, 'r') as f:
                keyfile_data = json.load(f)
            
            # Check if ss58Address is in the JSON (available without decryption)
            if 'ss58Address' in keyfile_data:
                address = keyfile_data['ss58Address']
                if address and address.startswith('5'):
                    print(f"✓ Loaded address from coldkey file")
                    return address
            
            # If we need to decrypt
            if wallet_password:
                try:
                    from substrateinterface import Keypair
                    keypair = Keypair.create_from_encrypted_json(keyfile_data, wallet_password)
                    address = keypair.ss58_address
                    print(f"✓ Decrypted coldkey and loaded address")
                    return address
                except Exception as e:
                    print(f"{Colors.RED}✗ Failed to decrypt wallet: {e}{Colors.RESET}")
                    print("Check that WALLET_PASSWORD is correct")
            else:
                # Try to get public key without decryption
                if 'publicKey' in keyfile_data:
                    try:
                        from substrateinterface import Keypair
                        public_key = keyfile_data['publicKey']
                        if public_key.startswith('0x'):
                            public_key = public_key[2:]
                        keypair = Keypair(public_key=bytes.fromhex(public_key), ss58_format=42)
                        address = keypair.ss58_address
                        print(f"✓ Derived address from public key")
                        return address
                    except Exception as e:
                        pass
                
                print(f"{Colors.YELLOW}⚠ Wallet may be encrypted but no password provided{Colors.RESET}")
                
        except json.JSONDecodeError as e:
            print(f"Error reading coldkey file: {e}")
        except Exception as e:
            print(f"Error processing coldkey file: {e}")
    
    # Method 3: Try using bittensor SDK if available
    if HAS_BITTENSOR:
        try:
            print("\nTrying bittensor SDK...")
            wallet = bt.wallet(name=wallet_name, path=wallet_path)
            
            # Try to access coldkey
            if wallet_password:
                try:
                    coldkey = wallet.coldkey
                    address = coldkey.ss58_address
                    print(f"✓ Loaded via bittensor SDK")
                    return address
                except:
                    pass
            
            # Try coldkeypub
            if hasattr(wallet, 'coldkeypub') and wallet.coldkeypub:
                address = wallet.coldkeypub.ss58_address
                print(f"✓ Loaded via bittensor SDK (coldkeypub)")
                return address
                
        except Exception as e:
            print(f"Bittensor SDK failed: {e}")
    
    print(f"{Colors.RED}✗ Could not load wallet address{Colors.RESET}")
    return None

async def main():
    """Main function"""
    
    # Parse command line arguments
    monitor_mode = '--monitor' in sys.argv
    interval = 10  # default interval
    
    # Check for --interval argument
    for i, arg in enumerate(sys.argv):
        if arg == '--interval' and i + 1 < len(sys.argv):
            try:
                interval = int(sys.argv[i + 1])
            except ValueError:
                print(f"{Colors.RED}✗ Invalid interval value. Using default: 10s{Colors.RESET}")
    
    print()
    
    # Show if .env file was loaded
    if HAS_DOTENV and os.path.exists('.env'):
        print(f"{Colors.CYAN}✓ Loaded .env file{Colors.RESET}")
    
    # Get wallet info from environment
    wallet_name = os.getenv('WALLET_NAME') or os.getenv('BITTENSOR_WALLET_NAME')
    wallet_password = os.getenv('WALLET_PASSWORD')
    wallet_path = os.getenv('WALLET_PATH')
    wallet_address = os.getenv('WALLET_ADDRESS') or os.getenv('COLDKEY_ADDRESS')
    
    address = None
    
    # Try to get address from wallet name
    if wallet_name:
        print()
        address = get_address_from_wallet_name(wallet_name, wallet_password, wallet_path)
        
        if not address:
            print()
            print(f"{Colors.RED}Failed to load wallet from WALLET_NAME{Colors.RESET}")
            print()
            print("Troubleshooting:")
            print("  1. Check wallet exists: ls -la ~/.bittensor/wallets/")
            print(f"  2. Check wallet files: ls -la ~/.bittensor/wallets/{wallet_name}/")
            print("  3. Verify WALLET_NAME in .env is correct")
            print("  4. Add WALLET_PASSWORD if wallet is encrypted")
            print("  5. Or use WALLET_ADDRESS=<your_address> instead")
            print()
            sys.exit(1)
    
    # Try to get direct address from env
    elif wallet_address:
        address = wallet_address
        print(f"Using direct address from WALLET_ADDRESS")
    
    # Try command line argument (non-flag argument)
    elif len(sys.argv) >= 2:
        for arg in sys.argv[1:]:
            if not arg.startswith('--') and not arg.isdigit():
                address = arg
                print(f"Using address from command line")
                break
    
    # Show usage if no address
    if not address:
        print("Usage:")
        print("  python3 check_balance.py [ADDRESS] [OPTIONS]")
        print()
        print("Options:")
        print("  --monitor          Monitor balance continuously and show rate of change")
        print("  --interval N       Check interval in seconds (default: 10, only with --monitor)")
        print()
        print("Configuration (.env file):")
        print("  Method 1 - Using wallet name:")
        print("    WALLET_NAME=my_wallet")
        print("    WALLET_PASSWORD=your_password  # Optional, only if wallet is encrypted")
        print()
        print("  Method 2 - Using direct address:")
        print("    WALLET_ADDRESS=5GrwvaEF5zXb26Fz9rcQpDWS4IpkExNKPHcm...")
        print()
        print("  Method 3 - Command line:")
        print("    python3 check_balance.py 5GrwvaEF5zXb26Fz9rcQpDWS4IpkExNKPHcm...")
        print()
        print("Examples:")
        print("  python3 check_balance.py                         # One-time check using .env")
        print("  python3 check_balance.py --monitor               # Continuous monitoring")
        print("  python3 check_balance.py --monitor --interval 5  # Monitor every 5 seconds")
        print()
        print("Environment variables:")
        print("  WALLET_NAME       - Name of wallet in ~/.bittensor/wallets/")
        print("  WALLET_PASSWORD   - Password (only if wallet is encrypted)")
        print("  WALLET_PATH       - Custom wallet directory (optional)")
        print("  WALLET_ADDRESS    - Direct coldkey address (alternative to WALLET_NAME)")
        print()
        print("To get your coldkey address:")
        print("  btcli wallet list")
        print()
        sys.exit(1)
    
    # Check or monitor the balance
    print()
    checker = WalletChecker(network='finney')
    
    if monitor_mode:
        await checker.monitor_balance(address, interval=interval)
    else:
        await checker.check_wallet(address)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        # Handle graceful shutdown
        pass

