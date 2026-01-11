#!/usr/bin/env python3
"""
Alpha Token Monitor - Watches .env file and executes buy/sell operations

Monitors .env file for:
- STAKE_NETUID + STAKE_AMOUNT: Buy alpha tokens (stake) when netuid changes
- UNSTAKE_NETUID + UNSTAKE_AMOUNT: Sell alpha tokens (unstake)

Rules:
- Buy only when stake_netuid changes from previous value
- Buy only once per unique stake_netuid
- If stake_amount is empty, skip buying
- Unstake only once per unstake_netuid/unstake_amount combination
- If unstake_amount is empty, unstake all alpha tokens in that netuid
"""

import os
import sys
import asyncio
import bittensor as bt
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Minimum transaction amount
MIN_STAKE_AMOUNT = 0.01
# Transaction fee buffer
TX_FEE_BUFFER = 0.01  # Reserve 0.01 TAO for transaction fees
# Polling interval for .env file (seconds)
POLL_INTERVAL = 0.5
# Price protection tolerance (percentage, default 2.0%)
PRICE_TOLERANCE_PERCENT = float(os.getenv("PRICE_TOLERANCE_PERCENT", "2.0"))


class AlphaMonitor:
    def __init__(self):
        self.env_file = Path(".env")
        self.last_env_mtime = 0
        self.previous_stake_netuid = None
        self.executed_stakes = set()  # Track executed (netuid, amount) combinations
        self.executed_unstakes = set()  # Track executed (netuid, amount) combinations
        
        # Load initial config
        load_dotenv()
        self.wallet_name = os.getenv("WALLET_NAME")
        self.wallet_password = os.getenv("WALLET_PASSWORD")
        self.network = os.getenv("NETWORK", "finney")
        
        if not self.wallet_name:
            sys.exit("❌ WALLET_NAME not specified in environment variables")
        
        # Initialize wallet
        self.wallet = bt.wallet(name=self.wallet_name)
        if self.wallet_password:
            self.wallet.coldkey_file.decrypt(self.wallet_password)
        else:
            self.wallet.unlock_coldkey()
        
        print(f"✅ Initialized wallet: {self.wallet_name}")
        print(f"✅ Network: {self.network}")
        print(f"✅ Monitoring .env file: {self.env_file.absolute()}")
        print(f"{'='*60}\n")
    
    def get_env_values(self):
        """Load and return current env values"""
        load_dotenv(override=True)  # Reload to get latest values
        
        stake_netuid = os.getenv("STAKE_NETUID")
        stake_amount = os.getenv("STAKE_AMOUNT")
        unstake_netuid = os.getenv("UNSTAKE_NETUID")
        unstake_amount = os.getenv("UNSTAKE_AMOUNT")
        
        # Convert to appropriate types
        try:
            stake_netuid = int(stake_netuid) if stake_netuid else None
        except (ValueError, TypeError):
            stake_netuid = None
        
        try:
            unstake_netuid = int(unstake_netuid) if unstake_netuid else None
        except (ValueError, TypeError):
            unstake_netuid = None
        
        try:
            stake_amount = float(stake_amount) if stake_amount and stake_amount.strip() else None
        except (ValueError, TypeError):
            stake_amount = None
        
        try:
            unstake_amount = float(unstake_amount) if unstake_amount and unstake_amount.strip() else None
        except (ValueError, TypeError):
            unstake_amount = None
        
        return stake_netuid, stake_amount, unstake_netuid, unstake_amount
    
    def env_file_changed(self):
        """Check if .env file has been modified"""
        if not self.env_file.exists():
            return False
        
        current_mtime = self.env_file.stat().st_mtime
        if current_mtime != self.last_env_mtime:
            self.last_env_mtime = current_mtime
            return True
        return False
    
    async def buy_alpha_tokens(self, subtensor, netuid, tao_amount):
        """Buy alpha tokens by staking TAO to a subnet using high-level API"""
        print(f"\n{'='*60}")
        print(f"💰 BUYING ALPHA TOKENS")
        print(f"{'='*60}")
        print(f"NetUID: {netuid}")
        print(f"TAO Amount: {tao_amount} TAO")
        
        # Check balance
        balance = await subtensor.get_balance(self.wallet.coldkeypub.ss58_address)
        required_amount = float(tao_amount) + TX_FEE_BUFFER
        
        if balance.tao < required_amount:
            print(f"❌ Insufficient balance. Need {required_amount:.6f} TAO, have {balance.tao:.6f} TAO")
            return False
        
        print(f"💰 Available Balance: {balance.tao:.6f} TAO")
        print(f"💰 Required: {required_amount:.6f} TAO")
        
        # Get subnet info to convert TAO to alpha tokens
        try:
            subnet_info = await subtensor.subnet(netuid=netuid)
            current_price = float(subnet_info.price.tao)
            print(f"📊 Current Alpha/TAO Price: {current_price:.9f} TAO per Alpha")
            
            # Calculate alpha token amount from TAO
            alpha_amount = tao_amount / current_price
            print(f"📊 Will receive approximately {alpha_amount:.6f} Alpha tokens")
        except Exception as e:
            print(f"❌ Error getting subnet price: {e}")
            return False
        
        # Get top validator for this subnet
        print(f"\n🔍 Finding top validator for subnet {netuid}...")
        try:
            metagraph = await subtensor.metagraph(netuid)
            validator_stakes = []
            for uid in range(len(metagraph.hotkeys)):
                if metagraph.stake[uid] > 0:
                    validator_stakes.append((uid, metagraph.hotkeys[uid], metagraph.stake[uid]))
            
            if not validator_stakes:
                print(f"❌ No validators found in subnet {netuid}")
                return False
            
            validator_stakes.sort(key=lambda x: x[2], reverse=True)
            hotkey = validator_stakes[0][1]
            print(f"✅ Using top validator: {hotkey} (UID: {validator_stakes[0][0]})")
        except Exception as e:
            print(f"❌ Error finding validator: {e}")
            return False
        
        # Perform the stake using force_batch for maximum speed
        amount = bt.Balance.from_tao(tao_amount)
        tolerance_multiplier = 1.0 + (PRICE_TOLERANCE_PERCENT / 100.0)
        max_price = current_price * tolerance_multiplier
        print(f"\n⏳ Staking {amount} to {hotkey} on subnet {netuid} using force_batch...")
        print(f"🚀 Fast mode: Using force_batch for immediate execution")
        print(f"🛡️  Price Protection: ENABLED")
        print(f"   Max Price: {max_price:.9f} TAO per Alpha ({PRICE_TOLERANCE_PERCENT}% tolerance)")
        
        try:
            # Calculate max_price for price protection (already calculated above)
            
            # Create the add_stake_limit call with price protection
            stake_call = await subtensor.substrate.compose_call(
                call_module='SubtensorModule',
                call_function='add_stake_limit',
                call_params={
                    'netuid': netuid,
                    'hotkey': hotkey,
                    'amount_staked': amount.rao,
                    'max_price': int(max_price * 1e9)  # Convert to RAO
                }
            )
            
            # Create force_batch call to wrap the stake call for speed
            batch_call = await subtensor.substrate.compose_call(
                call_module='Utility',
                call_function='force_batch',
                call_params={
                    'calls': [stake_call]
                }
            )
            
            # Execute the batch call
            extrinsic = await subtensor.substrate.create_signed_extrinsic(
                call=batch_call,
                keypair=self.wallet.coldkey
            )
            
            print(f"📤 Submitting force_batch transaction...")
            receipt = await subtensor.substrate.submit_extrinsic(
                extrinsic=extrinsic,
                wait_for_inclusion=True,
                wait_for_finalization=False  # Don't wait for finalization for maximum speed
            )
            
            if receipt.is_success:
                print(f"✅ Successfully bought alpha tokens!")
                print(f"   Staked: {amount} TAO")
                print(f"   Validator: {hotkey}")
                print(f"   Subnet: {netuid}")
                print(f"   Method: force_batch > add_stake_limit (FAST MODE)")
                return True
            else:
                print(f"❌ Transaction failed")
                return False
                
        except Exception as e:
            error_msg = str(e)
            if "PriceLimitExceeded" in error_msg or "price" in error_msg.lower() or "exceeded" in error_msg.lower():
                print(f"🛡️  Price Protection: Transaction rejected - price moved beyond {PRICE_TOLERANCE_PERCENT}% tolerance")
                print(f"💡 The price moved beyond the max_price limit during execution.")
                print(f"💡 Current tolerance: {PRICE_TOLERANCE_PERCENT}% (set via PRICE_TOLERANCE_PERCENT env var)")
                print(f"💡 This protects you from adverse price movements. Try again later or increase tolerance.")
            else:
                print(f"❌ Error during buy: {e}")
                if "--debug" in sys.argv:
                    import traceback
                    traceback.print_exc()
            return False
    
    async def sell_alpha_tokens(self, subtensor, netuid, tao_amount=None):
        """Sell alpha tokens by unstaking from a subnet
        
        Args:
            subtensor: Subtensor instance
            netuid: NetUID to unstake from
            tao_amount: TAO amount to unstake (None = unstake all)
        """
        print(f"\n{'='*60}")
        print(f"💰 SELLING ALPHA TOKENS")
        print(f"{'='*60}")
        print(f"NetUID: {netuid}")
        if tao_amount:
            print(f"TAO Amount: {tao_amount} TAO (target)")
        else:
            print(f"TAO Amount: ALL (unstake everything)")
        
        # Find existing stakes on this subnet
        print(f"\n🔍 Finding existing stakes on subnet {netuid}...")
        try:
            all_stakes = await subtensor.get_stake_for_coldkey(self.wallet.coldkeypub.ss58_address)
            if all_stakes is None:
                all_stakes = []
            
            subnet_stakes = [s for s in all_stakes if s and s.netuid == netuid]
            
            if not subnet_stakes:
                print(f"❌ No stakes found on subnet {netuid}")
                return False
            
            # Get subnet info for conversion
            subnet_info = await subtensor.subnet(netuid=netuid)
            current_price = float(subnet_info.price.tao)
            print(f"📊 Current Alpha/TAO Price: {current_price:.9f} TAO per Alpha")
            
            # Convert stakes to TAO
            stakes_with_tao = []
            total_tao = 0.0
            for stake_info in subnet_stakes:
                stake_tao = subnet_info.alpha_to_tao(stake_info.stake)
                if stake_tao.tao >= MIN_STAKE_AMOUNT:
                    stakes_with_tao.append((stake_info, stake_tao))
                    total_tao += float(stake_tao.tao)
            
            if not stakes_with_tao:
                print(f"❌ No valid stakes found on subnet {netuid}")
                return False
            
            print(f"📊 Found {len(stakes_with_tao)} stake(s) on subnet {netuid}:")
            for stake_info, stake_tao in stakes_with_tao:
                print(f"  - Validator: {stake_info.hotkey_ss58}, Stake: {stake_tao.tao:.6f} TAO")
            print(f"📊 Total stake: {total_tao:.6f} TAO")
            
            # Determine which stakes to unstake
            if tao_amount is None:
                # Unstake all - unstake from all validators
                print(f"\n📊 Unstaking ALL alpha tokens from subnet {netuid}")
                targets = stakes_with_tao  # Unstake all
            else:
                # Unstake specific amount - find matching stakes
                target_tao = float(tao_amount)
                if target_tao > total_tao:
                    print(f"⚠️  Requested {target_tao:.6f} TAO but only {total_tao:.6f} TAO available. Unstaking all.")
                    targets = stakes_with_tao
                else:
                    # Find stakes that match or sum to target
                    targets = []
                    remaining = target_tao
                    for stake_info, stake_tao in sorted(stakes_with_tao, key=lambda x: x[1].tao, reverse=True):
                        if remaining <= 0:
                            break
                        stake_tao_val = float(stake_tao.tao)
                        if stake_tao_val <= remaining:
                            targets.append((stake_info, stake_tao))
                            remaining -= stake_tao_val
                        else:
                            # Partial unstake from this validator
                            targets.append((stake_info, stake_tao))
                            remaining = 0
                            break
            
            # Unstake from each target validator
            success_count = 0
            for stake_info, stake_tao in targets:
                hotkey = stake_info.hotkey_ss58
                current_stake_tao = float(stake_tao.tao)
                
                # Get actual alpha stake
                try:
                    stake_alpha = await subtensor.get_stake(
                        coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                        hotkey_ss58=hotkey,
                        netuid=netuid
                    )
                    
                    if stake_alpha is None or stake_alpha.rao == 0:
                        print(f"⚠️  No valid alpha stake found for validator {hotkey}, skipping")
                        continue
                    
                    # Calculate amount to unstake
                    if tao_amount and current_stake_tao > float(tao_amount):
                        # Partial unstake
                        unstake_ratio = float(tao_amount) / current_stake_tao
                        unstake_rao = int(stake_alpha.rao * unstake_ratio * 0.999)
                        print(f"📊 Unstaking {unstake_ratio*100:.2f}% from {hotkey} ({float(tao_amount):.6f} TAO target)")
                    else:
                        # Unstake all from this validator
                        unstake_rao = int(stake_alpha.rao * 0.999)
                        print(f"📊 Unstaking all from {hotkey} ({current_stake_tao:.6f} TAO)")
                    
                    unstake_amount = bt.Balance.from_rao(unstake_rao).set_unit(netuid=netuid)
                    
                except Exception as e:
                    print(f"❌ Error getting stake amount for {hotkey}: {e}")
                    continue
                
                # Perform the unstake using force_batch for maximum speed
                print(f"\n⏳ Unstaking from validator {hotkey} on subnet {netuid}...")
                print(f"🚀 Fast mode: Using force_batch for immediate execution")
                print(f"🛡️  Price Protection: ENABLED")
                
                # Set min_price for price protection
                tolerance_multiplier = 1.0 - (PRICE_TOLERANCE_PERCENT / 100.0)
                min_price = current_price * tolerance_multiplier
                print(f"📊 Min Price Limit: {min_price:.9f} TAO per Alpha ({PRICE_TOLERANCE_PERCENT}% tolerance)")
                
                try:
                    # Use remove_stake_full_limit for full unstake, or remove_stake_limit for partial
                    if unstake_rao >= stake_alpha.rao * 0.99:
                        # Unstake all - use remove_stake_full_limit
                        unstake_call = await subtensor.substrate.compose_call(
                            call_module='SubtensorModule',
                            call_function='remove_stake_full_limit',
                            call_params={
                                'netuid': netuid,
                                'hotkey': hotkey,
                                'min_price': int(min_price * 1e9)  # Convert to RAO
                            }
                        )
                    else:
                        # Partial unstake - use remove_stake_limit
                        unstake_call = await subtensor.substrate.compose_call(
                            call_module='SubtensorModule',
                            call_function='remove_stake_limit',
                            call_params={
                                'netuid': netuid,
                                'hotkey': hotkey,
                                'amount': unstake_rao,
                                'min_price': int(min_price * 1e9)  # Convert to RAO
                            }
                        )
                    
                    # Wrap in force_batch for maximum speed
                    batch_call = await subtensor.substrate.compose_call(
                        call_module='Utility',
                        call_function='force_batch',
                        call_params={
                            'calls': [unstake_call]
                        }
                    )
                    
                    # Execute the batch call
                    extrinsic = await subtensor.substrate.create_signed_extrinsic(
                        call=batch_call,
                        keypair=self.wallet.coldkey
                    )
                    
                    print(f"📤 Submitting force_batch transaction...")
                    receipt = await subtensor.substrate.submit_extrinsic(
                        extrinsic=extrinsic,
                        wait_for_inclusion=True,
                        wait_for_finalization=False  # Don't wait for finalization for maximum speed
                    )
                    
                    if receipt.is_success:
                        print(f"✅ Successfully unstaked from {hotkey}!")
                        print(f"   Method: force_batch > remove_stake_limit (FAST MODE)")
                        success_count += 1
                    else:
                        print(f"❌ Failed to unstake from {hotkey}")
                        
                except Exception as e:
                    error_msg = str(e)
                    if "PriceLimitExceeded" in error_msg or "price" in error_msg.lower() or "exceeded" in error_msg.lower():
                        print(f"🛡️  Price Protection: Transaction rejected - price moved beyond {PRICE_TOLERANCE_PERCENT}% tolerance for {hotkey}")
                        print(f"💡 The price moved beyond the min_price limit during execution.")
                        print(f"💡 Current tolerance: {PRICE_TOLERANCE_PERCENT}% (set via PRICE_TOLERANCE_PERCENT env var)")
                        print(f"💡 This protects you from adverse price movements. Try again later or increase tolerance.")
                    else:
                        print(f"❌ Error unstaking from {hotkey}: {e}")
                        if "--debug" in sys.argv:
                            import traceback
                            traceback.print_exc()
            
            if success_count > 0:
                print(f"\n✅ Successfully sold alpha tokens from {success_count} validator(s)!")
                return True
            else:
                print(f"\n❌ Failed to sell alpha tokens")
                return False
                
        except Exception as e:
            print(f"❌ Error finding stakes: {e}")
            if "--debug" in sys.argv:
                import traceback
                traceback.print_exc()
            return False
    
    async def process_changes(self, subtensor):
        """Process .env file changes and execute operations"""
        stake_netuid, stake_amount, unstake_netuid, unstake_amount = self.get_env_values()
        
        # Handle stake operation
        if stake_netuid is not None:
            # Check if stake_netuid changed
            if stake_netuid != self.previous_stake_netuid:
                # NetUID changed, check if we should buy
                if stake_amount is not None and stake_amount >= MIN_STAKE_AMOUNT:
                    # Check if we already executed this combination
                    operation_key = (stake_netuid, stake_amount)
                    if operation_key not in self.executed_stakes:
                        print(f"\n🔄 Detected new stake operation: NetUID={stake_netuid}, Amount={stake_amount} TAO")
                        success = await self.buy_alpha_tokens(subtensor, stake_netuid, stake_amount)
                        if success:
                            self.executed_stakes.add(operation_key)
                            self.previous_stake_netuid = stake_netuid
                        else:
                            print(f"⚠️  Buy operation failed, will retry on next change")
                elif stake_amount is None or stake_amount == 0:
                    print(f"ℹ️  stake_netuid={stake_netuid} but stake_amount is empty, skipping buy")
                    # Update previous_stake_netuid even if we don't buy
                    self.previous_stake_netuid = stake_netuid
                else:
                    print(f"⚠️  stake_amount {stake_amount} is below minimum {MIN_STAKE_AMOUNT} TAO")
            else:
                # Same netuid, check if amount changed
                operation_key = (stake_netuid, stake_amount) if stake_amount else None
                if operation_key and operation_key not in self.executed_stakes:
                    if stake_amount is not None and stake_amount >= MIN_STAKE_AMOUNT:
                        print(f"\n🔄 Detected stake amount change: NetUID={stake_netuid}, Amount={stake_amount} TAO")
                        success = await self.buy_alpha_tokens(subtensor, stake_netuid, stake_amount)
                        if success:
                            self.executed_stakes.add(operation_key)
        
        # Handle unstake operation
        if unstake_netuid is not None:
            # Create operation key
            operation_key = (unstake_netuid, unstake_amount if unstake_amount else "ALL")
            
            if operation_key not in self.executed_unstakes:
                print(f"\n🔄 Detected unstake operation: NetUID={unstake_netuid}, Amount={unstake_amount if unstake_amount else 'ALL'} TAO")
                success = await self.sell_alpha_tokens(subtensor, unstake_netuid, unstake_amount)
                if success:
                    self.executed_unstakes.add(operation_key)
                else:
                    print(f"⚠️  Unstake operation failed, will retry on next change")
    
    async def monitor_loop(self):
        """Main monitoring loop"""
        print(f"🚀 Starting monitor loop (checking every {POLL_INTERVAL}s)...")
        print(f"Press Ctrl+C to stop\n")
        
        async with bt.async_subtensor(network=self.network) as subtensor:
            # Initial balance check
            balance = await subtensor.get_balance(self.wallet.coldkeypub.ss58_address)
            print(f"💰 Initial Balance: {balance.tao:.6f} TAO\n")
            
            try:
                while True:
                    # Check if .env file changed
                    if self.env_file_changed():
                        await self.process_changes(subtensor)
                    
                    await asyncio.sleep(POLL_INTERVAL)
                    
            except KeyboardInterrupt:
                print(f"\n\n⚠️  Monitor stopped by user")
            except Exception as e:
                print(f"\n❌ Fatal error: {e}")
                if "--debug" in sys.argv:
                    import traceback
                    traceback.print_exc()
                raise


async def main():
    """Main entry point"""
    monitor = AlphaMonitor()
    await monitor.monitor_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

