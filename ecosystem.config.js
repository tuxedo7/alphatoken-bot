module.exports = {
  apps: [
    {
      name: 'balance-checker',
      script: 'check_balance.py',
      interpreter: 'python3',
      args: '--monitor --interval 5',
      cwd: '/root/bittensor-alphatoken-buysell',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production'
      },
      error_file: './logs/balance-checker-error.log',
      out_file: './logs/balance-checker-out.log',
      log_file: './logs/balance-checker-combined.log',
      time: true,
      merge_logs: true
    },
    {
      name: 'mempool-monitor',
      script: 'monitoring_mempool.py',
      interpreter: 'python3',
      cwd: '/root/bittensor-alphatoken-buysell',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production'
      },
      error_file: './logs/mempool-monitor-error.log',
      out_file: './logs/mempool-monitor-out.log',
      log_file: './logs/mempool-monitor-combined.log',
      time: true,
      merge_logs: true
    }
  ]
};

