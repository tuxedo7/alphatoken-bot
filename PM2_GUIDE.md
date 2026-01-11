# PM2 Guide for monitoring_mempool.py

## Setup

The `ecosystem.config.js` file is already configured with logging for `monitoring_mempool.py`.

## Commands

### Start the mempool monitor
```bash
pm2 start ecosystem.config.js --only mempool-monitor
```

Or start all apps:
```bash
pm2 start ecosystem.config.js
```

### Stop the mempool monitor
```bash
pm2 stop mempool-monitor
```

### Restart the mempool monitor
```bash
pm2 restart mempool-monitor
```

### View logs
```bash
# View all logs (real-time)
pm2 logs mempool-monitor

# View only output logs
pm2 logs mempool-monitor --out

# View only error logs
pm2 logs mempool-monitor --err

# View last 100 lines
pm2 logs mempool-monitor --lines 100
```

### View status
```bash
pm2 status
```

### View detailed info
```bash
pm2 show mempool-monitor
```

### Delete from pm2
```bash
pm2 delete mempool-monitor
```

## Log Files

Logs are saved to:
- **Combined logs**: `./logs/mempool-monitor-combined.log`
- **Output logs**: `./logs/mempool-monitor-out.log`
- **Error logs**: `./logs/mempool-monitor-error.log`

## Auto-start on system reboot

To make pm2 start automatically on system reboot:
```bash
pm2 startup
pm2 save
```

## Useful PM2 Commands

```bash
# Monitor in real-time
pm2 monit

# View logs without colors (better for files)
pm2 logs mempool-monitor --nostream --lines 1000 > mempool-logs.txt

# Clear all logs
pm2 flush mempool-monitor

# Reload app (zero-downtime restart)
pm2 reload mempool-monitor
```

