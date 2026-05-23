# PostgreSQL Memory Crisis - Diagnosis & Resolution Guide

**Server:** ubuntu-16gb-fsn1-1 (16GB RAM, 0GB Swap initially)
**Database:** PostgreSQL 17 with pgvector (Container: ts8kss040c8sckso4kgssccs)

---

## Problem Summary

### Symptoms
- PostgreSQL processes being killed by Linux OOM (Out of Memory) Killer
- Frequent database restarts and recovery cycles
- Application experiencing 500 errors during database downtime
- Server with 16GB RAM showing only 1.7GB available

### Root Causes
1. **Zero swap space** - No buffer for memory spikes
2. **PostgreSQL over-configured** - 4GB shared_buffers + 32MB work_mem × 100 connections = potential 11-14GB
3. **Memory contention** - 40+ Docker containers competing for 16GB RAM
4. **Write-heavy workload** - Hundreds of thousands of bulk inserts causing checkpoint storms

### Evidence from `dmesg`
```
Out of memory: Killed process 1887997 (postgres) total-vm:4596384kB, anon-rss:29884kB, file-rss:0kB, shmem-rss:4287752kB
Out of memory: Killed process 1934340 (postgres) total-vm:4579620kB, anon-rss:12976kB, file-rss:128kB, shmem-rss:3658784kB
```

---

## Original Configuration

**File:** `/data/coolify/databases/ts8kss040c8sckso4kgssccs/custom-postgres.conf`

```ini
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 32MB
maintenance_work_mem = 512MB
random_page_cost = 1.1
effective_io_concurrency = 200
```

**Memory Calculation (Worst Case):**
- `shared_buffers`: 4GB (fixed)
- `work_mem`: 32MB × 100 connections × 2-3 operations = 6.4-9.6GB
- `maintenance_work_mem`: 512MB
- Connection overhead: ~100MB
- **Total PostgreSQL: 11-14GB**
- **Other containers: ~12GB**
- **Grand Total: 23-26GB on 15GB system** ❌

---

## Immediate Actions Taken

### 1. Added 8GB Swap Space
```bash
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Why:** Provides emergency overflow space to prevent immediate OOM kills.

### 2. Reduced PostgreSQL Memory Footprint

**New Configuration:**
```ini
shared_buffers = 2GB
effective_cache_size = 12GB
work_mem = 8MB
maintenance_work_mem = 512MB
random_page_cost = 1.1
effective_io_concurrency = 200
listen_addresses = '*'
```

**Results:**
- PostgreSQL memory: 4.5GB → 2.3GB (saved 2.2GB)
- System stabilized - no more OOM kills
- Active connections: 23/100 (healthy)

---

## PostgreSQL Configuration Parameters Explained

### Memory Settings

| Parameter | Old | New | Purpose | Impact |
|-----------|-----|-----|---------|--------|
| `shared_buffers` | 4GB | 2GB | PostgreSQL's main memory cache for data pages. Allocated at startup. | **Critical**: Reduces fixed memory allocation by 2GB |
| `work_mem` | 32MB | 8MB | Memory for sorting, hash joins per operation. Can multiply by connections. | **Critical**: Worst case reduced from 6.4GB to 1.6GB |
| `maintenance_work_mem` | 512MB | 512MB | Memory for VACUUM, CREATE INDEX, etc. | Kept - needed for bulk operations |
| `effective_cache_size` | 12GB | 12GB | Hint to planner about OS cache available. Doesn't allocate memory. | Kept - planning hint only |

### I/O Settings (SSD Optimized)

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `random_page_cost` | 1.1 | Cost of random disk access (lower = SSD). Default is 4.0 for HDD. |
| `effective_io_concurrency` | 200 | Parallel I/O operations (good for SSD). Default is 1. |

### Write Performance Settings (Optional - Not Currently Applied)

| Parameter | Suggested | Purpose | Risk |
|-----------|-----------|---------|------|
| `checkpoint_timeout` | 30min | How often to write dirty buffers to disk. Default: 5min. | Longer = less I/O, but more recovery time |
| `max_wal_size` | 4GB | Max size of WAL before forcing checkpoint. Default: 1GB. | Larger = fewer checkpoints during bulk loads |
| `min_wal_size` | 1GB | Keep this much WAL space preallocated. | Reduces allocation overhead |
| `wal_compression` | on | Compress WAL records. | Less disk I/O, slightly more CPU |
| `wal_buffers` | 16MB | WAL write buffer. Default: -1 (auto, typically 16MB). | Smoother write patterns |
| `synchronous_commit` | off | Don't wait for WAL flush on commit. | ⚠️ **Risk**: Can lose last few transactions on crash |
| `max_connections` | 100 | Maximum concurrent connections. | Each connection uses RAM (base + work_mem) |

---

## Container Resource Usage (Before Fix)

```
CONTAINER                    CPU %     MEM USAGE         MEM %
ts8kss040c8sckso4kgssccs     364.39%   4.495GiB          29.48%  ← PostgreSQL
redis-iwwc8cg4cwcc40css4     1.33%     1.627GiB          10.67%
worker-r44gkg0wco0cs0owskc   4.62%     1.216GiB          7.98%
api-r44gkg0wco0cs0owskc      0.81%     982.2MiB          6.29%
worker-iwwc8cg4cwcc40css4    20.20%    941.9MiB          6.03%

Total: ~16.2GB on 15GB system
```

**After Fix:**
```
ts8kss040c8sckso4kgssccs     527.29%   2.31GiB           15.15%  ← Reduced by 2GB
```

---

## Measuring Your App's Needs

### Current Workload Profile

**Phase 1: Bulk Loading (Current)**
- Hundreds of thousands of INSERT operations
- Duplicate key violations (needs ON CONFLICT handling)
- Deadlocks (concurrent updates to same rows)
- High disk I/O (4.6TB read / 934GB written)
- CPU: 364-527% (using 3.6-5.3 cores)

**Phase 2: Normal Operations (Future)**
- Aggregation queries (total points per day, per feature)
- Read-heavy workload
- Lower write volume

### Key Metrics to Monitor

#### 1. Memory Usage
```bash
# Overall system memory
free -h

# PostgreSQL container memory
docker stats --no-stream | grep ts8kss

# Check for OOM kills
dmesg | grep -i "out of memory" | tail -10

# Swap usage (should stay low < 2GB)
swapon --show
```

#### 2. Database Connection & Activity
```bash
# Active connections
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT count(*) FROM pg_stat_activity;\""

# Connection states
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT state, count(*) FROM pg_stat_activity GROUP BY state;\""

# Long-running queries
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT pid, now() - query_start AS duration, state, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY duration DESC LIMIT 10;\""
```

#### 3. Write Performance & Checkpoints
```bash
# Checkpoint activity
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT * FROM pg_stat_bgwriter;\""

# WAL statistics
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT * FROM pg_stat_wal;\""
```

#### 4. Query Performance
```bash
# Enable pg_stat_statements (if not already)
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"CREATE EXTENSION IF NOT EXISTS pg_stat_statements;\""

# Top 10 slowest queries
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT calls, mean_exec_time, total_exec_time, query FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;\""
```

#### 5. Disk I/O
```bash
# Docker I/O stats
docker stats --no-stream | grep -E "ts8kss|redis"

# Linux I/O wait
iostat -x 1 5

# Disk space usage
df -h
du -sh /var/lib/docker/volumes/postgres-data-ts8kss040c8sckso4kgssccs/
```

---

## Choosing Server Specs for Dedicated Database

### Minimum Requirements (Based on Current Usage)

**For PostgreSQL Only:**
```
RAM:     8GB minimum, 16GB recommended
CPU:     4-6 cores (you're using 3.6-5.3 cores during bulk load)
Disk:    500GB SSD (NVMe preferred)
         - Check current DB size: docker exec ts8kss040c8sckso4kgssccs \
           bash -c "psql -U postgres -c \"SELECT pg_size_pretty(pg_database_size('postgres'));\""
Network: 1Gbps minimum
```

**For PostgreSQL + Redis:**
```
RAM:     16GB minimum, 24GB recommended
         - PostgreSQL: 8GB
         - Redis: 2-4GB
         - OS + overhead: 4GB
         - Buffer: 4-8GB
CPU:     6-8 cores
Disk:    Same as above
```

### Configuration for Different Server Sizes

#### 8GB RAM Server (PostgreSQL Only)
```ini
shared_buffers = 2GB               # 25% of RAM
effective_cache_size = 6GB         # 75% of RAM
work_mem = 8MB
maintenance_work_mem = 512MB
max_connections = 50               # Reduced for smaller server
```

#### 16GB RAM Server (PostgreSQL Only)
```ini
shared_buffers = 4GB               # 25% of RAM
effective_cache_size = 12GB        # 75% of RAM
work_mem = 16MB
maintenance_work_mem = 1GB
max_connections = 100
```

#### 16GB RAM Server (PostgreSQL + Redis)
```ini
# PostgreSQL
shared_buffers = 3GB               # Leave room for Redis
effective_cache_size = 10GB
work_mem = 12MB
maintenance_work_mem = 768MB
max_connections = 75

# Redis (via docker-compose or config)
maxmemory = 4GB
maxmemory-policy = allkeys-lru     # Evict least recently used keys
```

#### 32GB RAM Server (PostgreSQL + Redis + Room to Grow)
```ini
# PostgreSQL
shared_buffers = 8GB               # 25% of RAM
effective_cache_size = 24GB        # 75% of RAM
work_mem = 32MB
maintenance_work_mem = 2GB
max_connections = 100

# Redis
maxmemory = 8GB
```

---

## Optimization Roadmap

### Phase 1: Immediate (Done ✓)
- [x] Add swap space (8GB)
- [x] Reduce shared_buffers to 2GB
- [x] Reduce work_mem to 8MB
- [x] Monitor for OOM kills

### Phase 2: During Bulk Loading (Optional)
Consider adding these settings for faster bulk inserts:
```ini
checkpoint_timeout = 30min
max_wal_size = 4GB
wal_compression = on
```

**Application-level optimizations:**
```python
# Use bulk_create with batch_size
Model.objects.bulk_create(objects, batch_size=1000, ignore_conflicts=True)

# Use ON CONFLICT in raw SQL
INSERT INTO table (col1, col2) VALUES (%s, %s)
ON CONFLICT (unique_col) DO UPDATE SET col2 = EXCLUDED.col2;

# Use COPY for fastest bulk loading
with connection.cursor() as cursor:
    cursor.copy_from(file_obj, 'table_name', sep=',', columns=['col1', 'col2'])
```

### Phase 3: Post-Bulk Loading
- Revert checkpoint settings to defaults
- Add indexes after bulk loading (faster than maintaining them during inserts)
- Run VACUUM ANALYZE to update statistics
```bash
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"VACUUM ANALYZE;\""
```

### Phase 4: Production Optimization (For Aggregations)
```ini
# Tune for read-heavy analytical queries
shared_buffers = 4GB              # Back to 4GB if separate server
work_mem = 64MB                   # Higher for complex aggregations
effective_cache_size = 12GB
random_page_cost = 1.1            # SSD
```

**Add materialized views for common aggregations:**
```sql
CREATE MATERIALIZED VIEW daily_points_summary AS
SELECT date, feature_id, SUM(points) as total_points
FROM points_table
GROUP BY date, feature_id;

-- Refresh periodically (e.g., hourly via cron)
REFRESH MATERIALIZED VIEW CONCURRENTLY daily_points_summary;
```

**Add appropriate indexes:**
```sql
CREATE INDEX idx_points_date ON points_table(date);
CREATE INDEX idx_points_feature ON points_table(feature_id);
CREATE INDEX idx_points_date_feature ON points_table(date, feature_id);
```

---

## Server Selection Decision Matrix

| Scenario | Best Choice | Specs | Estimated Cost |
|----------|-------------|-------|----------------|
| Current workload continues on shared server | Keep current + swap | 16GB, existing | $0 extra |
| Separate DB, moderate growth | Dedicated 16GB | 16GB RAM, 4-6 cores, 500GB SSD | $50-80/mo |
| DB + Redis separate | Dedicated 24GB | 24GB RAM, 6-8 cores, 500GB SSD | $80-120/mo |
| Future-proof with headroom | Dedicated 32GB | 32GB RAM, 8 cores, 1TB NVMe | $120-180/mo |
| Performance critical | Dedicated 64GB | 64GB RAM, 16 cores, 2TB NVMe | $250-400/mo |

### Provider Recommendations
- **Hetzner** (your current provider): Good price/performance, European data centers
- **DigitalOcean**: Managed PostgreSQL available (handles backups, updates)
- **AWS RDS / Aurora**: Managed, auto-scaling, expensive but reliable
- **Linode/Akamai**: Similar to Hetzner pricing

---

## Monitoring Commands (Copy-Paste Ready)

### Daily Check (Run Every Morning)
```bash
# Check for OOM kills since yesterday
dmesg -T | grep -i "out of memory" | tail -10

# Memory status
free -h
swapon --show

# Top memory consumers
docker stats --no-stream | head -10

# PostgreSQL health
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT count(*) FROM pg_stat_activity;\""
```

### Weekly Performance Review
```bash
# Database size growth
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT pg_size_pretty(pg_database_size('postgres'));\""

# Table sizes
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size FROM pg_tables ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC LIMIT 10;\""

# Slowest queries this week
docker exec ts8kss040c8sckso4kgssccs bash -c \
  "psql -U postgres -c \"SELECT calls, mean_exec_time, query FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;\""
```

### Real-Time Monitoring
```bash
# Watch memory every 5 seconds
watch -n 5 'free -h && echo "---" && docker stats --no-stream | head -10'

# Live PostgreSQL activity
watch -n 2 'docker exec ts8kss040c8sckso4kgssccs bash -c "psql -U postgres -c \"SELECT count(*), state FROM pg_stat_activity GROUP BY state;\""'
```

---

## Troubleshooting Checklist

### If PostgreSQL Gets Killed Again

1. **Check dmesg for OOM killer:**
   ```bash
   dmesg -T | grep -i "out of memory" | tail -20
   ```

2. **Verify swap is active:**
   ```bash
   swapon --show
   # Should show /swapfile with 8GB
   ```

3. **Check current memory allocation:**
   ```bash
   docker exec ts8kss040c8sckso4kgssccs bash -c "psql -U postgres -c 'SHOW shared_buffers;'"
   docker exec ts8kss040c8sckso4kgssccs bash -c "psql -U postgres -c 'SHOW work_mem;'"
   ```

4. **Identify memory hogs:**
   ```bash
   docker stats --no-stream | sort -k4 -h -r | head -10
   ```

5. **Reduce max_connections if needed:**
   - Edit: `/data/coolify/databases/ts8kss040c8sckso4kgssccs/custom-postgres.conf`
   - Add: `max_connections = 50`
   - Restart: `docker restart ts8kss040c8sckso4kgssccs`

### If Queries Are Slow

1. **Check for lock contention:**
   ```bash
   docker exec ts8kss040c8sckso4kgssccs bash -c \
     "psql -U postgres -c \"SELECT * FROM pg_locks WHERE NOT granted;\""
   ```

2. **Identify blocking queries:**
   ```bash
   docker exec ts8kss040c8sckso4kgssccs bash -c \
     "psql -U postgres -c \"SELECT pid, query FROM pg_stat_activity WHERE state = 'active' AND wait_event IS NOT NULL;\""
   ```

3. **Check for missing indexes:**
   ```bash
   docker exec ts8kss040c8sckso4kgssccs bash -c \
     "psql -U postgres -c \"SELECT schemaname, tablename, attname, n_distinct, correlation FROM pg_stats WHERE schemaname NOT IN ('pg_catalog', 'information_schema') ORDER BY abs(correlation) LIMIT 20;\""
   ```

---

## Summary & Next Steps

### What Was Changed
1. ✅ Added 8GB swap space for emergency overflow
2. ✅ Reduced `shared_buffers` from 4GB → 2GB
3. ✅ Reduced `work_mem` from 32MB → 8MB
4. ✅ PostgreSQL memory footprint: 4.5GB → 2.3GB

### Current Status
- System stable with no OOM kills
- Swap providing safety net
- PostgreSQL using ~2.3GB RAM
- 23 active connections (healthy)

### Recommended Next Steps

**Short Term (This Week):**
1. Monitor daily using commands in "Monitoring Commands" section
2. Watch for OOM kills in dmesg
3. Track swap usage (should stay < 2GB)

**Medium Term (2-4 Weeks):**
1. Complete bulk loading phase
2. Measure actual query performance for aggregations
3. Decide: Keep shared server or move to dedicated?
4. If moving: Provision 16GB dedicated server, test with current config

**Long Term (1-3 Months):**
1. Optimize application queries (add indexes, materialized views)
2. Implement connection pooling via PgBouncer (already have it)
3. Consider read replicas if read load is very high
4. Set up automated backups and monitoring (Prometheus + Grafana)

---

## Quick Reference: Config File Locations

- **PostgreSQL Config:** `/data/coolify/databases/ts8kss040c8sckso4kgssccs/custom-postgres.conf`
- **Docker Compose:** `/data/coolify/databases/ts8kss040c8sckso4kgssccs/docker-compose.yml`
- **Backup Config:** `/data/coolify/databases/ts8kss040c8sckso4kgssccs/custom-postgres.conf.backup`
- **Swap File:** `/swapfile` (8GB)
- **fstab Entry:** `/etc/fstab` (last line)

## Container Details
- **Name:** ts8kss040c8sckso4kgssccs
- **Image:** pgvector/pgvector:pg17
- **Port:** 2314:5432
- **Volume:** postgres-data-ts8kss040c8sckso4kgssccs

---

**Document Version:** 1.0
**Last Updated:** February 7, 2026
**Author:** System Administrator (with GitHub Copilot assistance)
