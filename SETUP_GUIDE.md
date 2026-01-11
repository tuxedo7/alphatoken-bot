# Setup Guide for check_balance.py

## Quick Setup

### Step 1: Install Dependencies

```bash
pip3 install substrateinterface python-dotenv
```

### Step 2: Create .env File

Create a file named `.env` in the same directory as `check_balance.py`:

```bash
nano .env
```

### Step 3: Add Your Wallet Configuration

Choose ONE of these methods:

#### Method 1: Using Wallet Name (Recommended)

```bash
WALLET_NAME=my_wallet
```

If your wallet is encrypted, also add:
```bash
WALLET_PASSWORD=your_password_here
```

#### Method 2: Using Direct Address (Simplest)

```bash
WALLET_ADDRESS=5GrwvaEF5zXb26Fz9rcQpDWS4IpkExNKPHcm2SyT6jgdhsU
```

### Step 4: Run the Script

```bash
python3 check_balance.py
```

## How It Works

### Using WALLET_NAME

The script will:
1. Look for your wallet in `~/.bittensor/wallets/WALLET_NAME/`
2. Try to read the public key from `coldkeypub.txt` or `coldkeypub`
3. If not found, read the `coldkey` JSON file
4. If `ss58Address` is in the JSON, use it (no decryption needed)
5. If password is provided, decrypt the coldkey to get the address
6. Once address is found, query the blockchain for balances

### Using WALLET_ADDRESS

The script will:
1. Use the address directly
2. Query the blockchain for balances

## Finding Your Wallet Information

### Method 1: List Your Wallets

```bash
btcli wallet list
```

This shows all your wallets and their addresses. You can:
- Copy the coldkey address and use it as `WALLET_ADDRESS`
- OR note the wallet name and use it as `WALLET_NAME`

### Method 2: Check Wallet Directory

```bash
ls ~/.bittensor/wallets/
```

Shows available wallet names. Then check a specific wallet:

```bash
ls -la ~/.bittensor/wallets/YOUR_WALLET_NAME/
```

You should see files like:
- `coldkey` - The encrypted private key
- `coldkeypub.txt` or `coldkeypub` - The public key/address (if exists)

## Example .env Files

### Example 1: Unencrypted Wallet

```bash
WALLET_NAME=my_wallet
```

### Example 2: Encrypted Wallet

```bash
WALLET_NAME=my_wallet
WALLET_PASSWORD=mySecurePassword123
```

### Example 3: Direct Address (No Password Needed)

```bash
WALLET_ADDRESS=5GrwvaEF5zXb26Fz9rcQpDWS4IpkExNKPHcm2SyT6jgdhsU
```

### Example 4: Custom Wallet Path

```bash
WALLET_NAME=my_wallet
WALLET_PATH=/custom/path/to/wallets
```

## Output Example

```
✓ Loaded .env file

Loading wallet: my_wallet
Wallet directory: /root/.bittensor/wallets/my_wallet
✓ Loaded address from coldkey file

================================================================================
BITTENSOR WALLET BALANCE
Network: finney
================================================================================

Wallet Address:
  5GrwvaEF5zXb26Fz9rcQpDWS4IpkExNKPHcm2SyT6jgdhsU

Fetching balances...

Free Balance:              12.345678900 TAO
Staked Balance:           123.456789000 TAO
--------------------------------------------------------------------------------
Total Balance:            135.802467900 TAO
```

## Troubleshooting

### Problem: "Wallet directory not found"

**Check wallet exists:**
```bash
ls -la ~/.bittensor/wallets/
```

**Create wallet if needed:**
```bash
btcli wallet new_coldkey --wallet.name my_wallet
```

### Problem: "Failed to decrypt wallet"

**Check your password is correct in .env:**
```bash
cat .env | grep WALLET_PASSWORD
```

**Or get the address without password:**
```bash
btcli wallet list
# Copy the address and use WALLET_ADDRESS instead
```

### Problem: "Could not load wallet address"

**Solution: Use direct address method**

1. Get your address:
```bash
btcli wallet list
```

2. Update .env to use the address directly:
```bash
echo "WALLET_ADDRESS=5GrwvaEF..." > .env
```

3. Run again:
```bash
python3 check_balance.py
```

### Problem: Module not found errors

**Install dependencies:**
```bash
pip3 install substrateinterface python-dotenv
```

**If using system Python:**
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install substrateinterface python-dotenv
python3 check_balance.py
```

## Security Notes

- The `.env` file contains sensitive information (password)
- Never commit `.env` to git
- Keep file permissions secure: `chmod 600 .env`
- The script only reads your password to decrypt the local wallet file
- No passwords or keys are transmitted anywhere

## Alternative Usage (Without .env)

You can also pass the address directly:

```bash
python3 check_balance.py 5GrwvaEF5zXb26Fz9rcQpDWS4IpkExNKPHcm2SyT6jgdhsU
```

Or set environment variables:

```bash
export WALLET_NAME=my_wallet
export WALLET_PASSWORD=my_password
python3 check_balance.py
```

## Support

If you're still having issues:

1. Check your wallet exists and you can see it with `btcli wallet list`
2. Try using `WALLET_ADDRESS` directly instead of `WALLET_NAME`
3. Check file permissions on your wallet directory
4. Make sure `.env` file is in the same directory as the script

