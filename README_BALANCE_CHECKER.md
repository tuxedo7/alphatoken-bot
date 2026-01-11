# Bittensor Balance Checker

A comprehensive tool to check and monitor your Bittensor wallet balance with support for both bittensor 9.x and 10.x.

## Features

✅ **One-time Balance Check** - Quick balance snapshot  
✅ **Continuous Monitoring** - Real-time balance updates  
✅ **Subnet Breakdown** - See stakes per subnet  
✅ **Screen Refresh** - Clean display updates in monitor mode  
✅ **PM2 Support** - Run as background service  
✅ **Multi-version Support** - Works with bittensor 9.x and 10.x  

## Quick Start

### One-Time Balance Check
```bash
python3 check_balance.py
```

### Continuous Monitoring (refreshes every 10 seconds)
```bash
python3 check_balance.py --monitor
```

### Custom Check Interval (refreshes every 5 seconds)
```bash
python3 check_balance.py --monitor --interval 5
```

## Display Features

The tool shows:
- 🟢 **Free Balance** - Available TAO (green)
- 🟡 **Staked Balance** - Total staked TAO (yellow)
- 🔵 **Subnet Breakdown** - Stakes per subnet (cyan)
- 🔴 **Total Balance** - Combined balance (red/bold)

### Monitor Mode Features
- **Auto-refresh**: Screen clears and updates every interval
- **Live timestamps**: Each check shows current date/time
- **Check counter**: Tracks number of balance checks
- **Clean exit**: Press Ctrl+C to stop gracefully

## Configuration

### Using .env file (recommended)
Create a `.env` file:
```env
WALLET_NAME=my_wallet
WALLET_PASSWORD=my_password  # Optional, only if encrypted
```

### Using command line
```bash
python3 check_balance.py 5D1tX2W1wuDhP8Kn5m79s3VSUA82VUjg6ivGp6wGt497zKRe
```

### Using environment variables
```bash
export WALLET_ADDRESS=5D1tX2W1wuDhP8Kn5m79s3VSUA82VUjg6ivGp6wGt497zKRe
python3 check_balance.py
```

## Running with PM2

### Quick Start
```bash
pm2 start ecosystem.config.js
```

### Custom Configuration
```bash
# Monitor every 5 seconds
pm2 start check_balance.py --name balance-5s --interpreter python3 -- --monitor --interval 5

# Monitor every 60 seconds
pm2 start check_balance.py --name balance-1m --interpreter python3 -- --monitor --interval 60

# Using virtual environment Python
pm2 start check_balance.py --name balance-checker \
  --interpreter /root/btcli_venv/bin/python -- --monitor --interval 10
```

### PM2 Management Commands
```bash
# View logs (real-time)
pm2 logs balance-checker

# View logs (last 200 lines)
pm2 logs balance-checker --lines 200

# List running processes
pm2 list

# Stop monitoring
pm2 stop balance-checker

# Restart
pm2 restart balance-checker

# Delete from PM2
pm2 delete balance-checker

# View detailed info
pm2 show balance-checker

# Monitor dashboard
pm2 monit
```

### Auto-start on System Reboot
```bash
pm2 save
pm2 startup
# Follow the instructions printed
```

## Output Example

### One-time Check
```
================================================================================
BITTENSOR WALLET BALANCE
Network: finney
================================================================================

Wallet Address:
  5D1tX2W1wuDhP8Kn5m79s3VSUA82VUjg6ivGp6wGt497zKRe

Fetching balances...

Free Balance:            19.433291871 TAO
Staked Balance:           0.010098493 TAO
  Breakdown by Subnet:
    Subnet  67:        0.010098493 TAO  (Validator: 5HGJhgUXAk...D7oueJFe)
--------------------------------------------------------------------------------
Total Balance:           19.443390364 TAO
```

### Monitor Mode
```
================================================================================
BITTENSOR BALANCE MONITOR
Network: finney
================================================================================

Wallet Address:
  5D1tX2W1wuDhP8Kn5m79s3VSUA82VUjg6ivGp6wGt497zKRe

Check interval: 5 seconds | Press Ctrl+C to stop
[Check #1] 2025-12-10 14:30:45
================================================================================

Free Balance:            19.433291871 TAO
Staked Balance:           0.010098493 TAO
  Breakdown by Subnet:
    Subnet  67:        0.010098493 TAO  (Validator: 5HGJhgUXAk...D7oueJFe)
--------------------------------------------------------------------------------
Total Balance:           19.443390364 TAO

⏳ Next check in 5s...
```
*Screen clears and refreshes after each interval*

## Technical Details

### Supported Bittensor Versions
- **9.x**: Uses `bt.subtensor()` with `get_stake_for_coldkey()`
- **10.x**: Uses `bt.Subtensor()` with `get_stake_info_for_coldkey()`

The script automatically detects your bittensor version and uses the appropriate API.

### Alpha Token Conversion
For dynamic subnets, the tool automatically converts alpha tokens to TAO using the current subnet price.

### Requirements
```
bittensor>=9.12.2
python-dotenv>=1.2.1
substrate-interface>=1.7.0
```

## Troubleshooting

### "Module 'bittensor' has no attribute 'async_subtensor'"
This means you're using bittensor 10.x. The script handles this automatically.

### "No wallet address available"
Make sure you have either:
- `WALLET_NAME` in `.env` file
- `WALLET_ADDRESS` in `.env` file
- Passed address as command line argument

### Stake balance shows 0 but you have stakes
- Check if stakes are on dynamic subnets (require alpha to TAO conversion)
- Verify network is set to correct chain (default: finney)

### PM2 logs not showing colors
```bash
pm2 logs balance-checker --raw
```

## Files

- `check_balance.py` - Main script
- `ecosystem.config.js` - PM2 configuration
- `PM2_GUIDE.md` - Detailed PM2 instructions
- `README_BALANCE_CHECKER.md` - This file
- `.env` - Configuration (create this)
- `logs/` - PM2 log files

## License

Part of the Bittensor ecosystem tools.

