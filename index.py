import os
import sys
import asyncio
import bittensor as bt
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration from environment variables
WALLET_NAME = os.getenv("WALLET_NAME")
WALLET_PASSWORD = os.getenv("WALLET_PASSWORD")
NETWORK = os.getenv("NETWORK", "finney")  # test, finney, or main
SUBNET_ID = int(os.getenv("SUBNET_ID", "71"))  # Subnet to stake on
VALIDATOR_HOTKEY_RAW = os.getenv("VALIDATOR_HOTKEY", "").strip()  # Optional: specific validator hotkey
STAKE_AMOUNT_TAO = float(os.getenv("STAKE_AMOUNT_TAO", "1"))  # Amount of TAO to stake
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "20"))  # Check stake every N seconds

# Trading Strategy Configuration
PROFIT_THRESHOLD = float(os.getenv("PROFIT_THRESHOLD", "0.5"))  # Unstake when profit >= X% (in TAO)
BUY_THRESHOLD = float(os.getenv("BUY_THRESHOLD", "-1.0"))  # Stake when price drops X% from entry
SELL_THRESHOLD = float(os.getenv("SELL_THRESHOLD", "0.5"))  # Unstake when price rises X% from entry
PROFIT_COMPARISON_THRESHOLD = float(os.getenv("PROFIT_COMPARISON_THRESHOLD", "2.0"))  # Unstake when recent profit is X% higher than previous profit

# Price Protection Configuration (Strict Safe Mode by default)
# See: https://docs.learnbittensor.org/learn/price-protection
SAFE_STAKING = os.getenv("SAFE_STAKING", "true").lower() == "true"  # Enable price protection (default: True)
ALLOW_PARTIAL_STAKE = os.getenv("ALLOW_PARTIAL_STAKE", "false").lower() == "true"  # Allow partial execution (default: False - Strict mode)
RATE_TOLERANCE = float(os.getenv("RATE_TOLERANCE", "0.02"))  # Price tolerance: 0.02 = 2% (default: 2%)

# Minimum transaction amount (0.0005 TAO)
MIN_STAKE_AMOUNT = 0.0005


def is_valid_ss58_address(address):
    """Check if a string is a valid SS58 address format."""
    if not address or not isinstance(address, str):
        return False
    # SS58 addresses typically start with '5' and are 48 characters long
    # Basic validation: starts with digit and is reasonable length
    if len(address) < 40 or len(address) > 50:
        return False
    if not address[0].isdigit():
        return False
    # Check if it contains only alphanumeric characters (SS58 format)
    if not all(c.isalnum() for c in address):
        return False
    return True


# Normalize VALIDATOR_HOTKEY - treat empty, "default", or invalid addresses as None
if VALIDATOR_HOTKEY_RAW and VALIDATOR_HOTKEY_RAW.lower() != "default":
    if is_valid_ss58_address(VALIDATOR_HOTKEY_RAW):
        VALIDATOR_HOTKEY = VALIDATOR_HOTKEY_RAW
    else:
        print(f"⚠️ Invalid validator hotkey format: '{VALIDATOR_HOTKEY_RAW}'. Auto-selecting top validator instead.")
        VALIDATOR_HOTKEY = None
else:
    VALIDATOR_HOTKEY = None


class StakeTracker:
    def __init__(self, wallet, subtensor, netuid, validator_hotkey=None):
        self.wallet = wallet
        self.subtensor = subtensor
        self.netuid = netuid
        self.validator_hotkey = validator_hotkey
        self.original_stake_amount = None
        self.original_stake_tao = None
        self.stake_timestamp = None
        self.entry_price = None  # Alpha/TAO price when we first staked
        self.has_stake = False  # Whether we currently have a stake
        self.tmp = 0.0
        self.tmp_profit = 0.0
        self.previous_profit = None  # Track previous profit percentage for comparison

    async def stake_initial_amount(self, amount_tao):
        """Stake TAO to get alpha tokens for the subnet."""
        amount = bt.Balance.from_tao(amount_tao)
        
        if amount_tao < MIN_STAKE_AMOUNT:
            raise ValueError(f"Stake amount must be at least {MIN_STAKE_AMOUNT} TAO")
        
        print(f"\n{'='*60}")
        print(f"💰 STAKING {amount_tao} TAO to subnet {self.netuid}")
        print(f"{'='*60}")
        
        # If validator_hotkey is specified, stake to that validator
        # Otherwise, find a top validator
        if self.validator_hotkey:
            hotkey = self.validator_hotkey
            print(f"📌 Staking to specified validator: {hotkey}")
        else:
            # Get top validators for this subnet
            metagraph = await self.subtensor.metagraph(self.netuid)
            # Find validators (UIDs with stake)
            validator_stakes = []
            for uid in range(len(metagraph.hotkeys)):
                if metagraph.stake[uid] > 0:  # Validator has stake
                    validator_stakes.append((uid, metagraph.hotkeys[uid], metagraph.stake[uid]))
            
            # Sort by stake (descending) and take top validator
            validator_stakes.sort(key=lambda x: x[2], reverse=True)
            if not validator_stakes:
                raise ValueError(f"No validators found in subnet {self.netuid}")
            
            hotkey = validator_stakes[0][1]
            print(f"📌 Using top validator: {hotkey} (UID: {validator_stakes[0][0]})")
            self.validator_hotkey = hotkey
        
        # Perform the stake
        print(f"⏳ Staking {amount} to {hotkey} on subnet {self.netuid}...")
        start_time = time.time()
        
        try:
            # Use price protection for safe staking
            # Strict Safe Mode: reject transaction if price moves beyond tolerance
            # See: https://docs.learnbittensor.org/learn/price-protection
            print(f"🛡️  Price Protection: {'ENABLED' if SAFE_STAKING else 'DISABLED'}")
            if SAFE_STAKING:
                print(f"   Mode: {'PARTIAL' if ALLOW_PARTIAL_STAKE else 'STRICT SAFE'}")
                print(f"   Tolerance: {RATE_TOLERANCE*100:.2f}%")
            
            result = await self.subtensor.add_stake(
                wallet=self.wallet,
                netuid=self.netuid,
                hotkey_ss58=hotkey,
                amount=amount,
                wait_for_inclusion=True,
                wait_for_finalization=True,
                safe_staking=SAFE_STAKING,
                rate_tolerance=RATE_TOLERANCE,
                allow_partial_stake=ALLOW_PARTIAL_STAKE
            )
            
            elapsed = time.time() - start_time
            
            if result:
                print(f"✅ Successfully staked {amount} in {elapsed:.2f}s")
                
                # Get the actual stake amount after staking (in TAO)
                await asyncio.sleep(2)  # Wait a bit for blockchain to update
                current_stake_tao = await self.get_current_stake()
                
                if current_stake_tao is None:
                    print("⚠️ Could not retrieve stake amount after staking")
                    return False
                
                self.original_stake_amount = current_stake_tao
                # Store original stake as TAO (float)
                self.original_stake_tao = float(current_stake_tao.tao)
                self.stake_timestamp = datetime.now()
                self.has_stake = True
                
                # Get entry price (alpha/TAO ratio when we staked)
                subnet_info = await self.subtensor.subnet(netuid=self.netuid)
                self.entry_price = float(subnet_info.price.tao)
                
                print(f"📊 Original stake recorded: {self.original_stake_tao:.6f} TAO")
                print(f"📊 Entry price: {self.entry_price:.6f} TAO per Alpha")
                return True
            else:
                print(f"❌ Failed to stake")
                return False
                
        except Exception as e:
            error_msg = str(e)
            if "Price exceeded tolerance" in error_msg or "exceeded tolerance" in error_msg or "tolerance" in error_msg.lower():
                print(f"🛡️  Price Protection: Transaction rejected - price moved beyond {RATE_TOLERANCE*100:.2f}% tolerance")
                print(f"💡 This protects you from adverse price movements. Try again later or adjust tolerance.")
            else:
                print(f"❌ Error during staking: {e}")
            return False
    
    async def get_current_stake(self):
        """Get current stake amount in TAO equivalent (converts alpha tokens to TAO)."""
        if not self.validator_hotkey:
            raise ValueError("Validator hotkey not set")
        
        try:
            # Get stake in alpha tokens
            stake_alpha = await self.subtensor.get_stake(
                coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                hotkey_ss58=self.validator_hotkey,
                netuid=self.netuid
            )
            
            # Convert alpha tokens to TAO using subnet price
            subnet_info = await self.subtensor.subnet(netuid=self.netuid)
            stake_tao = subnet_info.alpha_to_tao(stake_alpha)
            
            return stake_tao
        except Exception as e:
            print(f"❌ Error getting stake: {e}")
            return None
    
    async def get_current_price(self):
        """Get current Alpha/TAO price ratio."""
        try:
            subnet_info = await self.subtensor.subnet(netuid=self.netuid)
            return float(subnet_info.price.tao)
        except Exception as e:
            print(f"❌ Error getting current price: {e}")
            return None
    
    async def check_and_trade(self):
        """Monitor price and execute trades based on price movements.
        
        Trading Strategy:
        1. If we have a stake: Check if price has risen enough to profit (SELL)
        2. If we don't have a stake: Check if price has dropped enough to buy (BUY)
        3. Track profit in TAO terms
        """
        # Get current price
        current_price = await self.get_current_price()
        if current_price is None:
            print("⚠️ Could not retrieve current price.")
            return False
        
        # Check if we have a stake
        if self.has_stake:
            # We have alpha tokens - check if we should sell
            if self.entry_price is None or self.original_stake_tao is None:
                print("⚠️ Missing entry price or original stake. Cannot evaluate trade.")
                return False
            
            # Get current stake value in TAO
            current_stake_tao_balance = await self.get_current_stake()
            if current_stake_tao_balance is None:
                print("⚠️ Could not retrieve current stake.")
                return False
            
            current_stake_tao = float(current_stake_tao_balance.tao)
            original_stake_tao = self.original_stake_tao
            
            # Calculate profit in TAO
            profit_tao = current_stake_tao - original_stake_tao
            profit_percent = (profit_tao / original_stake_tao) * 100 if original_stake_tao > 0 else 0.0
            
            # Calculate price change from entry
            price_change_percent = ((current_price - self.entry_price) / self.entry_price) * 100 if self.entry_price > 0 else 0.0
            
            # Calculate target TAO based on profit threshold
            target_tao = original_stake_tao * (1 + PROFIT_THRESHOLD / 100)
            
            print(f"\n{'='*60}")
            print(f"📊 PRICE MONITORING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            print(f"Current Price:  {current_price:.6f} TAO per Alpha")
            print(f"Entry Price:    {self.entry_price:.6f} TAO per Alpha")
            print(f"Price Change:   {price_change_percent:+.2f}%")
            print(f"\nOriginal TAO:   {original_stake_tao:.6f} TAO")
            print(f"Current Value:  {current_stake_tao:.6f} TAO")
            print(f"Target TAO:     {target_tao:.6f} TAO (at {PROFIT_THRESHOLD}% profit)")
            print(f"Profit/Loss:     {profit_tao:+.6f} TAO ({profit_percent:+.2f}%)")
            print(f"\nSell Threshold: {SELL_THRESHOLD}% price increase")
            print(f"Profit Target:  {PROFIT_THRESHOLD}% TAO profit")
            
            # Decision logic: Sell if ANY of:
            # 1. Price drops from peak (take profit on reversal), OR
            # 2. Profit reaches new high above threshold, OR
            # 3. Recent profit is 3% higher than previous profit
            should_sell = False
            reason = ""
            
            # Update peak trackers first (always track peaks)
            if price_change_percent > self.tmp:
                self.tmp = price_change_percent  # Track highest price change
            
            if profit_percent > self.tmp_profit:
                self.tmp_profit = profit_percent  # Track highest profit
            
            # Check if price is dropping from peak
            if price_change_percent < self.tmp:
                if price_change_percent > self.tmp - 0.5 and price_change_percent > SELL_THRESHOLD:
                    should_sell = True
                    reason = f"Price dropping from peak ({self.tmp:.2f}% -> {price_change_percent:.2f}%, above {SELL_THRESHOLD}% threshold)"
            
            # Check if recent profit is 2% higher than previous profit
            if self.previous_profit is not None and not should_sell:
                profit_increase = profit_percent - self.previous_profit
                if profit_increase >= PROFIT_COMPARISON_THRESHOLD:
                    should_sell = True
                    reason = f"Recent profit ({profit_percent:.2f}%) is {profit_increase:.2f}% higher than previous profit ({self.previous_profit:.2f}%)"
            
            print(f"current profit {profit_tao} and percentage {profit_percent} and price change percent is {price_change_percent}")
            if self.previous_profit is not None:
                print(f"Previous profit: {self.previous_profit:.2f}%, Profit increase: {profit_percent - self.previous_profit:.2f}%")
            
            
            
            if should_sell:
                print(f"\n🎯 SELL SIGNAL: {reason}")
                print(f"💰 Unstaking alpha tokens to realize {profit_tao:+.6f} TAO profit...")
                # Update previous_profit before unstaking
                self.previous_profit = profit_percent
                return await self.unstake_all()
            else:
                print(f"\n⏳ Holding position...")
                waiting_messages = []
                if price_change_percent < SELL_THRESHOLD:
                    waiting_messages.append(f"{SELL_THRESHOLD - price_change_percent:.2f}% more price increase")
                if profit_percent < PROFIT_THRESHOLD:
                    waiting_messages.append(f"{PROFIT_THRESHOLD - profit_percent:.2f}% more profit")
                if self.previous_profit is not None and profit_percent - self.previous_profit < PROFIT_COMPARISON_THRESHOLD:
                    waiting_messages.append(f"{PROFIT_COMPARISON_THRESHOLD - (profit_percent - self.previous_profit):.2f}% more profit increase vs previous")
                if waiting_messages:
                    print(f"   Waiting for: {', '.join(waiting_messages)}")
                # Update previous_profit after check (even if not selling)
                self.previous_profit = profit_percent
                return False
        else:
            # We don't have a stake - check if we should buy
            if self.original_stake_tao is None:
                # First time - we need to stake
                print(f"\n{'='*60}")
                print(f"📊 PRICE MONITORING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*60}")
                print(f"Current Price:  {current_price:.6f} TAO per Alpha")
                print(f"💰 No stake yet. Staking initial amount...")
                return await self.stake_initial_amount(STAKE_AMOUNT_TAO)
            
            # We previously had a stake but sold it - check if price dropped enough to buy again
            if self.entry_price is None:
                # No previous entry price - stake now
                print(f"\n{'='*60}")
                print(f"📊 PRICE MONITORING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*60}")
                print(f"Current Price:  {current_price:.6f} TAO per Alpha")
                print(f"💰 No previous entry price. Staking...")
                return await self.stake_initial_amount(STAKE_AMOUNT_TAO)
            
            # Calculate price change from previous entry
            price_change_percent = ((current_price - self.entry_price) / self.entry_price) * 100 if self.entry_price > 0 else 0.0
            
            print(f"\n{'='*60}")
            print(f"📊 PRICE MONITORING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            print(f"Current Price:   {current_price:.6f} TAO per Alpha")
            print(f"Previous Entry:  {self.entry_price:.6f} TAO per Alpha")
            print(f"Price Change:    {price_change_percent:+.2f}%")
            print(f"Buy Threshold:   {BUY_THRESHOLD}% price drop")
            
            # Buy if price has dropped enough
            if price_change_percent <= BUY_THRESHOLD:
                print(f"\n🎯 BUY SIGNAL: Price dropped {price_change_percent:.2f}% (threshold: {BUY_THRESHOLD}%)")
                print(f"💰 Staking TAO to buy alpha tokens at lower price...")
                return await self.stake_initial_amount(STAKE_AMOUNT_TAO)
            else:
                print(f"\n⏳ Waiting for better entry price...")
                print(f"   Need {BUY_THRESHOLD - price_change_percent:.2f}% more drop")
                return False
    
    async def unstake_all(self):
        """Unstake all alpha tokens back to TAO."""
        if not self.validator_hotkey:
            print("❌ No validator hotkey set")
            return False
        
        # Get stake in TAO for display
        current_stake_tao_balance = await self.get_current_stake()
        if current_stake_tao_balance is None:
            print("❌ Could not retrieve current stake")
            return False

        # Extract TAO value as float
        current_stake_tao = float(current_stake_tao_balance.tao)

        if current_stake_tao < MIN_STAKE_AMOUNT:
            print(f"⚠️ Stake amount ({current_stake_tao:.6f} TAO) is below minimum unstake amount ({MIN_STAKE_AMOUNT} TAO)")
            return False
        
        # Get the actual alpha stake amount for unstaking (get it fresh right before unstaking)
        # This ensures we have the exact current amount
        try:
            stake_alpha = await self.subtensor.get_stake(
                coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                hotkey_ss58=self.validator_hotkey,
                netuid=self.netuid
            )
            
            # Verify we have a valid stake amount
            if stake_alpha is None:
                print("❌ No alpha stake found to unstake")
                return False
                
            # Check if the stake amount is valid (has non-zero value)
            if stake_alpha.rao == 0:
                print("❌ Alpha stake amount is zero")
                return False
            
            # Wait a moment to ensure blockchain state is consistent
            await asyncio.sleep(1)
            
            # Get the amount again right before unstaking to ensure we have the latest value
            stake_alpha_final = await self.subtensor.get_stake(
                coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                hotkey_ss58=self.validator_hotkey,
                netuid=self.netuid
            )
            
            if stake_alpha_final is None or stake_alpha_final.rao == 0:
                print("❌ No valid stake found right before unstaking")
                return False
            
            # Unstake 99.9% to account for any rounding/precision issues
            # This ensures we never try to unstake more than available
            unstake_rao = int(stake_alpha_final.rao * 0.999)
            unstake_amount = bt.Balance.from_rao(unstake_rao).set_unit(netuid=self.netuid)
            
            print(f"📊 Original alpha stake: {str(stake_alpha_final)} ({stake_alpha_final.rao} RAO)")
            print(f"📊 Unstaking 99.9%: {str(unstake_amount)} ({unstake_rao} RAO)")
        except Exception as e:
            print(f"❌ Error getting alpha stake amount: {e}")
            return False
        
        print(f"\n{'='*60}")
        print(f"🔄 UNSTAKING {current_stake_tao:.6f} TAO ({str(unstake_amount)}) from subnet {self.netuid}")
        print(f"{'='*60}")
        print(f"⏳ Unstaking from validator: {self.validator_hotkey}")
        
        start_time = time.time()
        
        try:
            # Use price protection for safe unstaking
            # Strict Safe Mode: reject transaction if price moves beyond tolerance
            # See: https://docs.learnbittensor.org/learn/price-protection
            print(f"🛡️  Price Protection: {'ENABLED' if SAFE_STAKING else 'DISABLED'}")
            if SAFE_STAKING:
                print(f"   Mode: {'PARTIAL' if ALLOW_PARTIAL_STAKE else 'STRICT SAFE'}")
                print(f"   Tolerance: {RATE_TOLERANCE*100:.2f}%")
            
            # For unstaking, always use partial safe mode to allow partial execution
            # This prevents PriceLimitExceeded errors when unstaking large amounts
            # The system will unstake as much as possible within tolerance
            unstake_allow_partial = True  # Always allow partial unstaking to avoid price limit errors
            
            print(f"📊 Attempting to unstake: {unstake_amount.rao} RAO (alpha tokens)")
            print(f"   Using PARTIAL mode to unstake maximum amount within {RATE_TOLERANCE*100:.2f}% tolerance")
            
            # Retry logic for outdated transactions
            max_retries = 3
            retry_delay = 2  # seconds
            result = False
            
            for attempt in range(max_retries):
                try:
                    result = await self.subtensor.unstake(
                        wallet=self.wallet,
                        netuid=self.netuid,
                        hotkey_ss58=self.validator_hotkey,
                        amount=unstake_amount,  # Use 99.9% to avoid rounding issues
                        wait_for_inclusion=True,
                        wait_for_finalization=False,  # Don't wait for finalization to avoid timeout
                        safe_staking=SAFE_STAKING,
                        rate_tolerance=RATE_TOLERANCE,
                        allow_partial_stake=unstake_allow_partial  # Use partial mode for unstaking
                    )
                    
                    if result:
                        break  # Success, exit retry loop
                    elif attempt < max_retries - 1:
                        print(f"⚠️  Unstake attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        # Get fresh stake amount for retry
                        stake_alpha_retry = await self.subtensor.get_stake(
                            coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                            hotkey_ss58=self.validator_hotkey,
                            netuid=self.netuid
                        )
                        if stake_alpha_retry and stake_alpha_retry.rao > 0:
                            unstake_rao_retry = int(stake_alpha_retry.rao * 0.999)
                            unstake_amount = bt.Balance.from_rao(unstake_rao_retry).set_unit(netuid=self.netuid)
                            print(f"📊 Retry: Updated unstake amount to {unstake_amount.rao} RAO")
                except Exception as e:
                    error_msg = str(e)
                    if "outdated" in error_msg.lower() or "Invalid Transaction" in error_msg:
                        if attempt < max_retries - 1:
                            print(f"⚠️  Transaction outdated (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                            await asyncio.sleep(retry_delay)
                            # Get fresh stake amount for retry
                            try:
                                stake_alpha_retry = await self.subtensor.get_stake(
                                    coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                                    hotkey_ss58=self.validator_hotkey,
                                    netuid=self.netuid
                                )
                                if stake_alpha_retry and stake_alpha_retry.rao > 0:
                                    unstake_rao_retry = int(stake_alpha_retry.rao * 0.999)
                                    unstake_amount = bt.Balance.from_rao(unstake_rao_retry).set_unit(netuid=self.netuid)
                                    print(f"📊 Retry: Updated unstake amount to {unstake_amount.rao} RAO")
                            except:
                                pass
                            continue
                        else:
                            raise  # Re-raise if all retries exhausted
                    else:
                        raise  # Re-raise non-outdated errors
            
            elapsed = time.time() - start_time
            
            if result:
                # Wait a moment for blockchain to update
                await asyncio.sleep(2)
                
                # Check how much was actually unstaked (might be partial)
                remaining_stake_tao_balance = await self.get_current_stake()
                if remaining_stake_tao_balance:
                    remaining_stake_tao = float(remaining_stake_tao_balance.tao)
                    unstaked_tao = current_stake_tao - remaining_stake_tao
                    
                    if remaining_stake_tao < MIN_STAKE_AMOUNT:
                        # Effectively fully unstaked (dust remaining)
                        print(f"✅ Successfully unstaked {current_stake_tao:.6f} TAO in {elapsed:.2f}s")
                        
                        # Calculate final profit in TAO
                        final_profit_tao = float(current_stake_tao) - float(self.original_stake_tao)
                        final_profit_percent = (final_profit_tao / float(self.original_stake_tao)) * 100 if self.original_stake_tao > 0 else 0.0
                        
                        print(f"\n💰 FINAL PROFIT: {final_profit_tao:+.6f} TAO ({final_profit_percent:+.2f}%)")
                        print(f"📅 Duration: {datetime.now() - self.stake_timestamp}")
                        
                        # Update entry price for next buy decision
                        subnet_info = await self.subtensor.subnet(netuid=self.netuid)
                        self.entry_price = float(subnet_info.price.tao)
                        
                        # Reset stake status and peak trackers for next cycle
                        self.has_stake = False
                        self.tmp = 0.0
                        self.tmp_profit = 0.0
                        self.previous_profit = None
                    else:
                        # Partial unstake - some amount remains
                        print(f"✅ Partially unstaked {unstaked_tao:.6f} TAO in {elapsed:.2f}s")
                        print(f"📊 Remaining stake: {remaining_stake_tao:.6f} TAO (will continue monitoring)")
                        
                        # Calculate profit on what was unstaked
                        unstake_ratio = unstaked_tao / current_stake_tao if current_stake_tao > 0 else 0
                        final_profit_tao = unstaked_tao - (float(self.original_stake_tao) * unstake_ratio)
                        final_profit_percent = (final_profit_tao / float(self.original_stake_tao)) * 100 if self.original_stake_tao > 0 else 0.0
                        
                        print(f"\n💰 PARTIAL PROFIT: {final_profit_tao:+.6f} TAO ({final_profit_percent:+.2f}%)")
                        print(f"💡 Remaining stake will be monitored for next unstake opportunity")
                        
                        # Update original stake to remaining amount for next cycle
                        self.original_stake_tao = remaining_stake_tao
                        
                        # Update entry price but keep stake active
                        subnet_info = await self.subtensor.subnet(netuid=self.netuid)
                        self.entry_price = float(subnet_info.price.tao)
                        
                        # Reset peak trackers for next cycle
                        self.tmp = 0.0
                        self.tmp_profit = 0.0
                        self.previous_profit = None
                else:
                    # Couldn't get remaining stake, assume fully unstaked
                    print(f"✅ Successfully unstaked {current_stake_tao:.6f} TAO in {elapsed:.2f}s")
                    
                    final_profit_tao = float(current_stake_tao) - float(self.original_stake_tao)
                    final_profit_percent = (final_profit_tao / float(self.original_stake_tao)) * 100 if self.original_stake_tao > 0 else 0.0
                    
                    print(f"\n💰 FINAL PROFIT: {final_profit_tao:+.6f} TAO ({final_profit_percent:+.2f}%)")
                    print(f"📅 Duration: {datetime.now() - self.stake_timestamp}")
                    
                    subnet_info = await self.subtensor.subnet(netuid=self.netuid)
                    self.entry_price = float(subnet_info.price.tao)
                    
                    self.has_stake = False
                    self.tmp = 0.0
                    self.tmp_profit = 0.0
                
                return True
            else:
                print(f"❌ Failed to unstake")
                return False
                
        except Exception as e:
            error_msg = str(e)
            
            # Handle outdated transaction errors
            if "outdated" in error_msg.lower() or "Invalid Transaction" in error_msg:
                print(f"⚠️  Transaction outdated error: {error_msg}")
                print(f"💡 This usually happens when the transaction takes too long to submit.")
                print(f"💡 The script will retry on the next check cycle.")
                return False
            
            # Handle price limit errors
            if "PriceLimitExceeded" in error_msg or "Price exceeded tolerance" in error_msg or "exceeded tolerance" in error_msg or "tolerance" in error_msg.lower():
                print(f"🛡️  Price Protection: Transaction rejected - price would move beyond {RATE_TOLERANCE*100:.2f}% tolerance")
                print(f"💡 Even partial unstaking would exceed price tolerance. This protects you from adverse price movements.")
                print(f"💡 Options:")
                print(f"   1. Wait for better market conditions (price may stabilize)")
                print(f"   2. Increase RATE_TOLERANCE (currently {RATE_TOLERANCE*100:.2f}%)")
                print(f"   3. Unstake in smaller amounts manually")
                print(f"   4. Disable price protection (not recommended for mainnet)")
                
                # Try unstaking a smaller amount (50%) if partial mode is enabled
                if SAFE_STAKING and unstake_allow_partial:
                    print(f"\n⚠️  Attempting to unstake 50% of stake to reduce price impact...")
                    try:
                        # Get current stake again
                        stake_alpha_small = await self.subtensor.get_stake(
                            coldkey_ss58=self.wallet.coldkeypub.ss58_address,
                            hotkey_ss58=self.validator_hotkey,
                            netuid=self.netuid
                        )
                        
                        if stake_alpha_small and stake_alpha_small.rao > 0:
                            # Try unstaking 50% instead
                            small_unstake_rao = int(stake_alpha_small.rao * 0.5)
                            small_unstake_amount = bt.Balance.from_rao(small_unstake_rao).set_unit(netuid=self.netuid)
                            
                            print(f"📊 Attempting to unstake 50%: {small_unstake_amount.rao} RAO")
                            
                            result = await self.subtensor.unstake(
                                wallet=self.wallet,
                                netuid=self.netuid,
                                hotkey_ss58=self.validator_hotkey,
                                amount=small_unstake_amount,
                                wait_for_inclusion=True,
                                wait_for_finalization=True,
                                safe_staking=True,
                                rate_tolerance=RATE_TOLERANCE,
                                allow_partial_stake=True
                            )
                            
                            if result:
                                print(f"✅ Successfully unstaked 50% of stake")
                                # Continue monitoring remaining stake
                                await asyncio.sleep(2)
                                remaining_stake_tao_balance = await self.get_current_stake()
                                if remaining_stake_tao_balance:
                                    remaining_stake_tao = float(remaining_stake_tao_balance.tao)
                                    unstaked_tao = current_stake_tao - remaining_stake_tao
                                    
                                    print(f"📊 Unstaked: {unstaked_tao:.6f} TAO, Remaining: {remaining_stake_tao:.6f} TAO")
                                    
                                    # Update original stake to remaining amount
                                    self.original_stake_tao = remaining_stake_tao
                                    
                                    # Update entry price
                                    subnet_info = await self.subtensor.subnet(netuid=self.netuid)
                                    self.entry_price = float(subnet_info.price.tao)
                                    
                                    # Reset peak trackers
                                    self.tmp = 0.0
                                    self.tmp_profit = 0.0
                                    
                                    return True
                            else:
                                print(f"❌ Even 50% unstake failed due to price limit")
                        else:
                            print(f"❌ Could not get stake amount for smaller unstake")
                    except Exception as e2:
                        print(f"❌ Error during smaller unstake attempt: {e2}")
                
                return False
            else:
                print(f"❌ Error during unstaking: {e}")
                return False
    
    async def monitor_continuously(self):
        """Monitor price continuously and execute trades based on strategy."""
        print(f"\n{'='*60}")
        print(f"🔍 STARTING CONTINUOUS PRICE MONITORING & TRADING")
        print(f"{'='*60}")
        print(f"Check interval: {CHECK_INTERVAL} seconds")
        print(f"Buy Threshold:  {BUY_THRESHOLD}% price drop")
        print(f"Sell Threshold:  {SELL_THRESHOLD}% price increase")
        print(f"Profit Target:   {PROFIT_THRESHOLD}% TAO profit")
        print(f"Profit Comparison: Unstake when profit is {PROFIT_COMPARISON_THRESHOLD}% higher than previous profit")
        print(f"Press Ctrl+C to stop\n")
        
        try:
            while True:
                # Check price and execute trades
                await self.check_and_trade()
                
                # Wait before next check
                print(f"\n⏳ Waiting {CHECK_INTERVAL} seconds until next check...")
                await asyncio.sleep(CHECK_INTERVAL)
                
        except KeyboardInterrupt:
            print("\n\n⚠️ Monitoring stopped by user")
            if self.has_stake:
                print("💡 Current stake remains active. Run the script again to monitor or unstake manually.")
            else:
                print("💡 No active stake. Run the script again to start trading.")


async def main():
    """Main function to run the auto stake/unstake script."""
    # Validate configuration
    if not WALLET_NAME:
        sys.exit("❌ WALLET_NAME not specified in environment variables")
    
    if STAKE_AMOUNT_TAO < MIN_STAKE_AMOUNT:
        sys.exit(f"❌ STAKE_AMOUNT_TAO must be at least {MIN_STAKE_AMOUNT} TAO")
    
    print(f"\n{'='*60}")
    print(f"🤖 BITTENSOR AUTO STAKE/UNSTAKE SCRIPT")
    print(f"{'='*60}")
    print(f"Wallet: {WALLET_NAME}")
    print(f"Network: {NETWORK}")
    print(f"Subnet: {SUBNET_ID}")
    print(f"Stake Amount: {STAKE_AMOUNT_TAO} TAO")
    print(f"Check Interval: {CHECK_INTERVAL} seconds")
    print(f"Price Protection: {'ENABLED' if SAFE_STAKING else 'DISABLED'}")
    if SAFE_STAKING:
        print(f"  Mode: {'PARTIAL SAFE' if ALLOW_PARTIAL_STAKE else 'STRICT SAFE'}")
        print(f"  Tolerance: {RATE_TOLERANCE*100:.2f}%")
    if VALIDATOR_HOTKEY:
        print(f"Validator: {VALIDATOR_HOTKEY}")
    else:
        print(f"Validator: Top validator (auto-selected)")
    
    # Initialize wallet and subtensor
    wallet = bt.wallet(name=WALLET_NAME)
    
    if WALLET_PASSWORD:
        wallet.coldkey_file.decrypt(WALLET_PASSWORD)
    else:
        wallet.unlock_coldkey()
    
    async with bt.async_subtensor(network=NETWORK) as subtensor:
        # Check balance
        balance = await subtensor.get_balance(wallet.coldkeypub.ss58_address)
        print(f"\n💰 Coldkey Balance: {balance}")
        
        # if balance.tao < STAKE_AMOUNT_TAO:
        #     sys.exit(f"❌ Insufficient balance. Need {STAKE_AMOUNT_TAO} TAO, have {balance.tao} TAO")
        
        # Check for existing stakes on this subnet
        print(f"\n🔍 Checking for existing stakes on subnet {SUBNET_ID}...")
        try:
            all_stakes = await subtensor.get_stake_for_coldkey(wallet.coldkeypub.ss58_address)
            # Filter stakes for this subnet
            subnet_stakes = [s for s in all_stakes if s and s.netuid == SUBNET_ID]
            
            # Convert alpha stakes to TAO for comparison
            subnet_info = await subtensor.subnet(netuid=SUBNET_ID)
            stakes_with_tao = []
            for stake_info in subnet_stakes:
                stake_tao = subnet_info.alpha_to_tao(stake_info.stake)
                if stake_tao.tao >= MIN_STAKE_AMOUNT:
                    stakes_with_tao.append((stake_info, stake_tao))
            
            if stakes_with_tao:
                print(f"📊 Found {len(stakes_with_tao)} existing stake(s) on subnet {SUBNET_ID}:")
                for stake_info, stake_tao in stakes_with_tao:
                    print(f"  - Validator: {stake_info.hotkey_ss58}, Stake: {stake_tao.tao:.6f} TAO")
                
                # If a specific validator is requested, try to use that stake
                if VALIDATOR_HOTKEY:
                    matching = next(((s, t) for s, t in stakes_with_tao if s.hotkey_ss58 == VALIDATOR_HOTKEY), None)
                    if matching:
                        stake_info, stake_tao = matching
                        print(f"\n✅ Using existing stake to validator {VALIDATOR_HOTKEY}")
                        tracker = StakeTracker(
                            wallet=wallet,
                            subtensor=subtensor,
                            netuid=SUBNET_ID,
                            validator_hotkey=VALIDATOR_HOTKEY
                        )
                        tracker.original_stake_amount = stake_tao
                        # Store original stake as TAO (float)
                        tracker.original_stake_tao = float(stake_tao.tao)
                        tracker.stake_timestamp = datetime.now()
                        tracker.has_stake = True
                        # Get entry price
                        tracker.entry_price = float(subnet_info.price.tao)
                    else:
                        print(f"\n⚠️ No existing stake found for validator {VALIDATOR_HOTKEY}")
                        print(f"💰 Staking to requested validator...")
                        tracker = StakeTracker(
                            wallet=wallet,
                            subtensor=subtensor,
                            netuid=SUBNET_ID,
                            validator_hotkey=VALIDATOR_HOTKEY
                        )
                        if not await tracker.stake_initial_amount(STAKE_AMOUNT_TAO):
                            sys.exit("❌ Failed to stake initial amount")
                else:
                    # Use the largest existing stake for monitoring (by TAO value)
                    largest_stake_info, largest_stake_tao = max(stakes_with_tao, key=lambda x: x[1].tao)
                    print(f"\n✅ Using largest existing stake: {largest_stake_tao.tao:.6f} TAO to validator {largest_stake_info.hotkey_ss58}")
                    tracker = StakeTracker(
                        wallet=wallet,
                        subtensor=subtensor,
                        netuid=SUBNET_ID,
                        validator_hotkey=largest_stake_info.hotkey_ss58
                    )
                    tracker.original_stake_amount = largest_stake_tao
                    # Store original stake as TAO (float)
                    tracker.original_stake_tao = float(largest_stake_tao.tao)
                    tracker.stake_timestamp = datetime.now()
                    tracker.has_stake = True
                    # Get entry price
                    tracker.entry_price = float(subnet_info.price.tao)
            else:
                # No existing stakes, create new stake
                print(f"📊 No existing stakes found on subnet {SUBNET_ID}")
                tracker = StakeTracker(
                    wallet=wallet,
                    subtensor=subtensor,
                    netuid=SUBNET_ID,
                    validator_hotkey=VALIDATOR_HOTKEY
                )
                if not await tracker.stake_initial_amount(STAKE_AMOUNT_TAO):
                    sys.exit("❌ Failed to stake initial amount")
        except Exception as e:
            print(f"⚠️ Error checking existing stakes: {e}")
            print("💰 Proceeding with new stake...")
            tracker = StakeTracker(
                wallet=wallet,
                subtensor=subtensor,
                netuid=SUBNET_ID,
                validator_hotkey=VALIDATOR_HOTKEY
            )
            if not await tracker.stake_initial_amount(STAKE_AMOUNT_TAO):
                sys.exit("❌ Failed to stake initial amount")
        
        # Start monitoring
        await tracker.monitor_continuously()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Script interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
