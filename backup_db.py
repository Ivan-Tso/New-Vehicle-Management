#!/usr/bin/env python3
"""
Database backup script for Vehicle Management System.
Run daily via cron: 0 2 * * * cd /path && python3 backup_db.py
"""
import os
import sys

# Add project directory to path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# Import the Flask app to access config
from app import app, backup_db

def main():
    """Run database backup."""
    backup_dir = os.environ.get('BACKUP_DIR', os.path.join(PROJECT_DIR, 'backups'))
    keep_days = int(os.environ.get('BACKUP_KEEP_DAYS', '7'))
    
    success, result = backup_db(backup_dir=backup_dir, keep_days=keep_days)
    
    if success:
        print(f"✓ Backup successful: {result}")
        return 0
    else:
        print(f"✗ Backup failed: {result}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
